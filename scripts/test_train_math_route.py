"""Offline regression checks for train-only oversampling and snapshot integrity."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from train_math_route import expand_training, prepare, read_rows, route_summary, summarize_routing, write_json
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
        manifest = {"folds": [{"fold": 0, "splits": splits}],
                    "files": {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in source.rglob("*.jsonl")}}
        write_json(source / "manifest.json", manifest)
        output = Path(tmp) / "output"
        prepare(source, output, 3)
        assert len(read_rows(output / "fold-0/train.jsonl")) == 3
        for split in ("calibration", "test"):
            name = "fold-0/%s.jsonl" % split
            assert (source / name).read_bytes() == (output / name).read_bytes()
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
