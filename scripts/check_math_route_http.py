"""Temporarily serve a local checkpoint and replay a held-out fold over real HTTP."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from train_math_route import online_summary, read_rows, route_summary, write_json


def request(url, payload=None):
    req = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--fold", type=int, default=0)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.serve:
        import uvicorn
        from laya import Router
        from laya.serve import create_app
        router = Router(models={"multilingual": args.checkpoint}, device="cuda", default="multilingual")
        router.preload(["multilingual"])
        uvicorn.run(create_app(router), host="127.0.0.1", port=args.port)
        return
    # Refuse an existing listener; never stop or replace someone else's service.
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", args.port))
    out = Path(args.out)
    if out.exists():
        raise FileExistsError(out)
    base = "http://127.0.0.1:%d" % args.port
    evaluation_path = Path(args.checkpoint) / "routing-runtime-evaluation.json"
    evaluation = json.loads(evaluation_path.read_text()) if evaluation_path.exists() else None
    threshold = evaluation["calibrationSelected"]["threshold"] if evaluation else None
    score = online_summary if evaluation and evaluation.get("objective") == "online-recall" else route_summary
    expected = {r["stateSha256"]: r for r in evaluation["samples"]["test"]} if evaluation else {}
    rows = read_rows(Path(args.data) / ("fold-%d/test.jsonl" % args.fold))
    held_out_count = len(rows)
    training_risk_replay = bool(evaluation and evaluation.get("riskCalibrationIsTrainingReplay"))
    if training_risk_replay:
        rows += [r for r in read_rows(Path(args.data) / ("fold-%d/calibration.jsonl" % args.fold))
                 if r["expected"]["math_route"] == "online"]
        expected.update({r["stateSha256"]: r for r in evaluation["samples"]["calibration"] if r["gold"] == "online"})
    samples, errors = [], []
    log_path = out.with_suffix(".log")
    with log_path.open("x") as log:
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--serve"],
                                stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 50
            while True:
                if proc.poll() is not None:
                    raise RuntimeError("test server exited; inspect " + str(log_path))
                try:
                    health = request(base + "/health")
                    break
                except URLError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("test server startup timeout")
                    time.sleep(0.2)
            for row in rows:
                result = request(base + "/v1/systemone", {"model": "multilingual", "state": row["state"],
                                                         "questions": row["questions"]})
                qhash = hashlib.sha256(row["state"].encode()).hexdigest()
                p = result["answers"]["math_route"]["probabilities"]["local"]
                if result.get("usage", {}).get("truncated"):
                    errors.append({"stateSha256": qhash, "error": "HTTP input truncated"})
                if qhash in expected and abs(p - expected[qhash]["pLocal"]) > 0.001:
                    errors.append({"stateSha256": qhash, "error": "probability mismatch"})
                samples.append({"stateSha256": qhash, "gold": row["expected"]["math_route"], "pLocal": p,
                                "pOnline": result["answers"]["math_route"]["probabilities"]["online"]})
                if qhash in expected and score is online_summary:
                    actual_online = samples[-1]["pOnline"] >= threshold
                    expected_online = expected[qhash]["pOnline"] >= threshold
                    if actual_online != expected_online:
                        errors.append({"stateSha256": qhash, "error": "threshold decision mismatch"})
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
    report = {"checkpoint": args.checkpoint, "health": health, "httpRequests": len(samples),
              "testArgmax": score(samples[:held_out_count], 0.5), "testSelected": score(samples[:held_out_count], threshold),
              "errors": errors, "samples": samples[:held_out_count], "testServerStopped": True,
              "note": "Temporary localhost service; thresholds applied client-side; rounded API probabilities may affect boundary decisions."}
    if training_risk_replay:
        report.update(trainingRiskReplaySelected=score(samples[held_out_count:], threshold),
                      trainingRiskReplayDefault=score(samples[held_out_count:], 0.5),
                      trainingRiskReplaySamples=samples[held_out_count:], unseenRiskEvaluationAvailable=False)
    write_json(out, report)
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}), flush=True)
    if errors:
        raise RuntimeError("HTTP replay checks failed")


if __name__ == "__main__":
    main()
