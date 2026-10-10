"""Sequential five-fold frozen-encoder comparison; never select a model using test scores."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from train_math_route import file_sha256, write_json


def aggregate(evaluations):
    result = {}
    for name in ("testSelected", "testArgmax"):
        rows = [evaluation[name] for evaluation in evaluations]
        total = sum(row["items"] for row in rows)
        local = sum(row["localCount"] for row in rows)
        unsafe = sum(row["unsafeLocalCount"] for row in rows)
        result[name] = {"items": total, "localCount": local, "localCoverage": local / total,
                        "unsafeLocalCount": unsafe,
                        "historicallySafeFraction": (local - unsafe) / local if local else None}
        if all("riskCount" in row for row in rows):
            risk = sum(row["riskCount"] for row in rows)
            safe = sum(row["safeCount"] for row in rows)
            false_online = sum(row["falseOnlineCount"] for row in rows)
            result[name].update(riskCount=risk, safeCount=safe, falseOnlineCount=false_online,
                                onlineRecall=(risk - unsafe) / risk if risk else None,
                                localFalseOnlineRate=false_online / safe if safe else None)
    samples = [row for evaluation in evaluations for row in evaluation["samples"]["test"]]
    if len({row["stateSha256"] for row in samples}) != len(samples):
        raise ValueError("test questions duplicated across folds")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-1x", required=True)
    parser.add_argument("--data-3x", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--baseline-only", action="store_true", help="five-fold threshold replay of original weights, no training")
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--objective", choices=("local-safe", "online-recall"), default="local-safe")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    script = Path(__file__).with_name("train_math_route.py")
    base = Path(args.base)
    hashes = {name: file_sha256(base / name) for name in ("model.safetensors", "rl_agent_config.json")}
    summary = {"base": str(base), "baseHashes": hashes, "epochs": 0 if args.baseline_only else args.epochs,
               "objective": args.objective, "runtime": args.runtime,
               "developmentOnly": True, "variants": {},
               "note": "Same fixed splits/base/seed/epochs. Oversampling increases optimizer updates. No test-based selection or production deployment."}
    # Both variants must have byte-identical held-out files and original labels.
    for fold in range(5):
        for split in ("calibration", "test"):
            name = "fold-%d/%s.jsonl" % (fold, split)
            if (Path(args.data_1x) / name).read_bytes() != (Path(args.data_3x) / name).read_bytes():
                raise ValueError("comparison has different held-out files: " + name)
    variants = (("original", args.data_1x),) if args.baseline_only else (("online1x", args.data_1x), ("online3x", args.data_3x))
    for variant, data in variants:
        evaluations, folds = [], []
        for fold in range(5):
            checkpoint = out / variant / ("fold-%d" % fold)
            common = [sys.executable, "-u", str(script), "train", "--data", data,
                      "--fold", str(fold), "--out", str(checkpoint), "--objective", args.objective]
            log = out / ("%s-fold-%d.log" % (variant, fold))
            print("Running %s fold %d" % (variant, fold), flush=True)
            with log.open("x") as f:
                if args.baseline_only:
                    checkpoint.mkdir(parents=True)
                else:
                    subprocess.run(common + ["--base", str(base), "--epochs", str(args.epochs)],
                                   stdout=f, stderr=subprocess.STDOUT, check=True)
                subprocess.run(common + ["--base", str(base if args.baseline_only else checkpoint), "--evaluate-only"]
                               + (["--runtime"] if args.runtime else []),
                               stdout=f, stderr=subprocess.STDOUT, check=True)
            evaluation = json.loads((checkpoint / ("routing-runtime-evaluation.json" if args.runtime else "routing-evaluation.json")).read_text())
            report = json.loads((checkpoint / "report.json").read_text()) if not args.baseline_only else {}
            evaluations.append(evaluation)
            folds.append({"fold": fold, "checkpoint": str(checkpoint),
                          "accuracy": report.get("afterTest", {}).get("accuracy"),
                          "peakAllocatedMiB": report.get("peakAllocatedMiB"),
                          "elapsedSeconds": report.get("elapsedSeconds"),
                          "calibration": report.get("calibration"),
                          "calibrationSelected": evaluation["calibrationSelected"],
                          "testSelected": evaluation["testSelected"], "testArgmax": evaluation["testArgmax"]})
            if evaluation.get("riskCalibrationIsTrainingReplay"):
                folds[-1].update(trainingRiskReplaySelected=evaluation["trainingRiskReplaySelected"],
                                 trainingRiskReplayDefault=evaluation["trainingRiskReplayDefault"])
                summary.update(protocol="all-online-in-train", unseenRiskEvaluationAvailable=False,
                               riskCalibrationIsTrainingReplay=True)
            print(json.dumps(folds[-1]), flush=True)
        summary["variants"][variant] = {"folds": folds, "aggregate": aggregate(evaluations)}
        write_json(out / "summary.json", summary)
    if hashes != {name: file_sha256(base / name) for name in hashes}:
        raise ValueError("original model files changed during experiment")
    summary["originalModelUnchanged"] = True
    write_json(out / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
