"""Offline regression checks for train-only oversampling and snapshot integrity."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from train_math_route import (expand_training, prepare, read_rows, route_summary, summarize_routing,
                              summarize_online_routing, write_json)
from benchmark_math_route import aggregate


def main():
    rows = [{"state": "a", "expected": {"math_route": "local"}},
            {"state": "b", "expected": {"math_route": "online"}}]
    assert len(expand_training(rows, 1)) == 2
    expanded = expand_training(rows, 3)
    assert expanded == [rows[0], rows[1], rows[1], rows[1]]
    assert len(rows) == 2
    samples = [{"pLocal": 0.7, "gold": "local"}, {"pLocal": 0.6, "gold": "online"}]
    assert route_summary(samples, 0.7)["localCount"] == 1
    assert route_summary(samples, 0.6)["unsafeLocalCount"] == 1
    assert route_summary(samples, None)["historicallySafeFraction"] is None
    calibration = [{"gold": "local", "pLocal": 0.7}] * 10 + [{"gold": "online", "pLocal": 0.6}]
    routing = summarize_routing({"calibration": calibration, "test": [{"gold": "online", "pLocal": 0.8}]})
    assert routing["calibrationSelected"]["threshold"] == 0.7
    assert routing["testSelected"]["unsafeLocalCount"] == 1  # test labels cannot alter the threshold
    assert summarize_routing({"calibration": samples, "test": samples})["calibrationSelected"]["threshold"] is None
    risk_samples = [{"gold": "online", "pLocal": 0.8, "pOnline": 0.2},
                    {"gold": "online", "pLocal": 0.5, "pOnline": 0.5},
                    {"gold": "local", "pLocal": 0.9, "pOnline": 0.1},
                    {"gold": "local", "pLocal": 0.6, "pOnline": 0.4}]
    risk_routing = summarize_online_routing({"calibration": risk_samples,
                                           "test": [{"gold": "online", "pLocal": 0.99, "pOnline": 0.01}]})
    assert risk_routing["calibrationSelected"]["threshold"] == 0.2
    assert risk_routing["calibrationSelected"]["onlineRecall"] == 1.0
    assert risk_routing["calibrationSelected"]["falseOnlineCount"] == 1
    assert risk_routing["testSelected"]["unsafeLocalCount"] == 1
    assert summarize_online_routing({"calibration": samples[:1], "test": risk_samples})["testSelected"]["onlineRecall"] == 1.0
    evaluation = {"testSelected": route_summary(samples, 0.7), "testArgmax": route_summary(samples, 0.5),
                  "samples": {"test": [dict(row, stateSha256=str(i)) for i, row in enumerate(samples)]}}
    assert aggregate([evaluation])["testSelected"]["localCoverage"] == 0.5
    assert aggregate([evaluation])["testArgmax"]["unsafeLocalCount"] == 1
    try:
        aggregate([evaluation, evaluation])
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate out-of-fold test questions accepted")
    try:
        expand_training(rows, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid repeat accepted")
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "source"
        (source / "fold-0").mkdir(parents=True)
        audits, splits = [], {}
        for i, split in enumerate(("train", "calibration", "test")):
            row = {"state": str(i), "expected": {"math_route": "online"}}
            (source / "fold-0" / (split + ".jsonl")).write_text(json.dumps(row) + "\n")
            audits.append({"questionId": str(i), "groupId": str(i), "label": "online",
                           "questionSha256": hashlib.sha256(str(i).encode()).hexdigest()})
            splits[split] = {"questionIds": [str(i)]}
        audit_path = source / "label_audit.jsonl"
        audit_path.write_text("".join(json.dumps(row) + "\n" for row in audits))
        write_json(source / "questions.json", {"math_route": {"instructions": "old"}})
        manifest = {"folds": [{"fold": 0, "splits": splits}],
                    "files": {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in source.rglob("*.jsonl")}}
        manifest["files"]["questions.json"] = hashlib.sha256((source / "questions.json").read_bytes()).hexdigest()
        (source / "all_labeled.jsonl").write_text("".join((source / ("fold-0/%s.jsonl" % split)).read_text()
                                                       for split in ("train", "calibration", "test")))
        manifest["files"]["all_labeled.jsonl"] = hashlib.sha256((source / "all_labeled.jsonl").read_bytes()).hexdigest()
        write_json(source / "manifest.json", manifest)
        output = Path(tmp) / "output"
        prepare(source, output, 3)
        assert len(read_rows(output / "fold-0/train.jsonl")) == 3
        for split in ("calibration", "test"):
            name = "fold-0/%s.jsonl" % split
            assert (source / name).read_bytes() == (output / name).read_bytes()
        replacement = Path(tmp) / "questions.json"
        write_json(replacement, {"math_route": {"instructions": "risk"}})
        changed = Path(tmp) / "changed-prompt"
        prepare(source, changed, 3, replacement)
        for split in ("calibration", "test"):
            before = read_rows(source / ("fold-0/%s.jsonl" % split))
            after = read_rows(changed / ("fold-0/%s.jsonl" % split))
            assert [(r["state"], r["expected"]) for r in before] == [(r["state"], r["expected"]) for r in after]
            assert after[0]["questions"]["math_route"]["instructions"] == "risk"
        all_online = Path(tmp) / "all-online"
        prepare(source, all_online, 3, replacement, all_online_train=True)
        assert len(read_rows(all_online / "fold-0/train.jsonl")) == 9
        assert len(read_rows(all_online / "fold-0/calibration.jsonl")) == 3
        assert read_rows(all_online / "fold-0/test.jsonl") == []
        all_manifest = json.loads((all_online / "manifest.json").read_text())
        assert all_manifest["riskCalibrationIsTrainingReplay"] is True
        assert len(all_manifest["effectiveFolds"][0]["trainingRiskQuestionIds"]) == 3
        try:
            prepare(source, output, 3)
        except FileExistsError:
            pass
        else:
            raise AssertionError("overwrite allowed")
        (source / "fold-0/train.jsonl").write_text("corrupt")
        try:
            prepare(source, Path(tmp) / "bad", 3)
        except ValueError:
            pass
        else:
            raise AssertionError("checksum mismatch accepted")
    print("math training preparation checks passed")


if __name__ == "__main__":
    main()
