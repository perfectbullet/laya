"""Re-evaluate completed five-fold runs using the serving Agent, not FP32 training forwards."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from benchmark_math_route import aggregate
from train_math_route import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--original-run", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    script = Path(__file__).with_name("train_math_route.py")
    summary = {"developmentOnly": True, "variants": {}, "inference": "Agent.predict, serving precision and rounding"}
    output = Path(args.run) / "summary-runtime.json"
    if output.exists():
        raise FileExistsError(output)
    for variant in ("original", "online1x", "online3x"):
        evaluations, folds = [], []
        for fold in range(5):
            root = Path(args.original_run if variant == "original" else args.run)
            checkpoint = root / variant / ("fold-%d" % fold)
            base = args.base if variant == "original" else str(checkpoint)
            print("Runtime replay %s fold %d" % (variant, fold), flush=True)
            with (checkpoint / "runtime-replay.log").open("x") as f:
                subprocess.run([sys.executable, "-u", str(script), "train", "--data", args.data,
                                "--base", base, "--out", str(checkpoint), "--fold", str(fold),
                                "--evaluate-only", "--runtime"], stdout=f, stderr=subprocess.STDOUT, check=True)
            evaluation = json.loads((checkpoint / "routing-runtime-evaluation.json").read_text())
            evaluations.append(evaluation)
            folds.append({"fold": fold, "dtype": evaluation["dtype"],
                          "calibrationSelected": evaluation["calibrationSelected"],
                          "testSelected": evaluation["testSelected"], "testArgmax": evaluation["testArgmax"]})
            print(json.dumps(folds[-1]), flush=True)
        summary["variants"][variant] = {"folds": folds, "aggregate": aggregate(evaluations)}
        write_json(output, summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
