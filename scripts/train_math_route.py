"""Audited math-route training with explicit, disjoint calibration and test splits."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expand_training(rows, online_repeat):
    if online_repeat < 1:
        raise ValueError("online_repeat must be positive")
    expanded = []
    for row in rows:
        label = row["expected"]["math_route"]
        if label not in ("local", "online"):
            raise ValueError("unknown math_route label")
        expanded.extend([row] * (online_repeat if label == "online" else 1))
    return expanded


def route_summary(samples, threshold):
    allowed = [row for row in samples if threshold is not None and row["pLocal"] >= threshold]
    unsafe = sum(row["gold"] == "online" for row in allowed)
    return {"threshold": threshold, "items": len(samples), "localCount": len(allowed),
            "localCoverage": len(allowed) / len(samples), "unsafeLocalCount": unsafe,
            "historicallySafeFraction": (len(allowed) - unsafe) / len(allowed) if allowed else None}


def routing_evaluation(records, rows, fitted):
    """Export canonical local probabilities; labels never enter inference input."""
    from laya.common import temp_bucket
    samples = []
    for (qt, logits, _target, k), row in zip(records, rows):
        scale = fitted.get("temperature_by_options", {}).get(temp_bucket(qt, k), fitted["temperature"][qt])
        z = [float(v) / scale for v in logits[:k]]
        probs = [math.exp(v - max(z)) for v in z]
        labels = list(row["questions"]["math_route"]["criteria"])
        samples.append({"stateSha256": hashlib.sha256(row["state"].encode()).hexdigest(),
                        "gold": row["expected"]["math_route"],
                        "pLocal": probs[labels.index("local")] / sum(probs)})
    return samples


def summarize_routing(samples):
    candidates = [route_summary(samples["calibration"], t)
                  for t in sorted({s["pLocal"] for s in samples["calibration"]})]
    eligible = [r for r in candidates if r["localCount"] >= 10 and r["historicallySafeFraction"] >= 0.98]
    selected = max(eligible, key=lambda r: r["localCount"]) if eligible else route_summary(samples["calibration"], None)
    return {"developmentOnly": True,
            "thresholdSelection": "calibration only; empirical safe fraction >= .98; minimum 10 local",
            "note": "Historical label agreement is not a guarantee of 98% solver correctness on new questions.",
            "calibrationSelected": selected,
            "testSelected": route_summary(samples["test"], selected["threshold"]),
            "testArgmax": route_summary(samples["test"], 0.5), "samples": samples}


def prepare(source, output, online_repeat):
    """Derive a new snapshot; never modify the original export or held-out rows."""
    manifest = json.loads((source / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError("source checksum mismatch: " + name)
    audit = {row["questionId"]: row for row in read_rows(source / "label_audit.jsonl")}
    for fold in manifest["folds"]:
        groups = []
        for split in ("train", "calibration", "test"):
            ids = fold["splits"][split]["questionIds"]
            rows = read_rows(source / ("fold-%d/%s.jsonl" % (fold["fold"], split)))
            if len(ids) != len(rows):
                raise ValueError("manifest row count mismatch")
            for qid, row in zip(ids, rows):
                if audit[qid]["label"] != row["expected"]["math_route"]:
                    raise ValueError("audit label mismatch")
                if hashlib.sha256(row["state"].encode()).hexdigest() != audit[qid]["questionSha256"]:
                    raise ValueError("audit text mismatch")
            groups.append({audit[qid]["groupId"] for qid in ids})
        if any(groups[i] & groups[j] for i in range(3) for j in range(i)):
            raise ValueError("group leakage between splits")
    output.mkdir(parents=True, exist_ok=False)
    counts = {}
    for name in manifest["files"]:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith("/train.jsonl"):
            rows = expand_training(read_rows(source / name), online_repeat)
            target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            counts[name] = dict(Counter(row["expected"]["math_route"] for row in rows))
        else:
            target.write_bytes((source / name).read_bytes())
    write_json(output / "manifest.json", {
        "sourceManifestSha256": hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest(),
        "sourceManifest": manifest, "onlineRepeat": online_repeat, "trainCounts": counts,
        "files": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in manifest["files"]},
    })
    return counts


def run(args):
    import torch
    from transformers import AutoTokenizer
    from laya.common import build_sequence, uses_parallel_layout
    from laya.calibrate import fit_temperature_map
    from laya.train import (TrainConfig, calibration_records, calibration_report, evaluate_records,
                            items_from_rows, load_checkpoint, save_checkpoint, to_internal, train_model)

    root = Path(args.data)
    manifest = json.loads((root / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("data checksum mismatch: " + name)
    fold = root / ("fold-%d" % args.fold)
    rows = {name: read_rows(fold / (name + ".jsonl")) for name in ("train", "calibration", "test")}
    for left, right in (("train", "calibration"), ("train", "test"), ("calibration", "test")):
        if {row["state"] for row in rows[left]} & {row["state"] for row in rows[right]}:
            raise ValueError("overlapping split texts")
    base = Path(args.base)
    cfg = json.loads((base / "rl_agent_config.json").read_text())
    tok = AutoTokenizer.from_pretrained(base / "tokenizer", local_files_only=True)
    max_len = args.max_len or cfg["max_len"]
    head_max_len = cfg["head_max_len"]
    lengths = []
    for row in read_rows(root / "all_labeled.jsonl"):
        ids, markers, stats = build_sequence(tok, row["state"], to_internal("math_route", row["questions"]["math_route"]),
                                            max_len, head_max_len, return_truncation_stats=True)
        if len(markers) != 2:
            raise ValueError("options missing from token sequence")
        lengths.append(dict(stats, sequence_tokens=len(ids)))
    report = {"tokenizer": {"items": len(lengths), "max_len": max_len, "head_max_len": head_max_len,
                            "max_state_tokens": max(s["state_tokens"] for s in lengths),
                            "max_sequence_tokens": max(s["sequence_tokens"] for s in lengths),
                            "truncated": sum(s["truncated"] for s in lengths)},
              "fold": args.fold, "counts": {name: dict(Counter(r["expected"]["math_route"] for r in data))
                                             for name, data in rows.items()},
              "dataManifestSha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
              "base": str(base), "baseWeightsSha256": file_sha256(base / "model.safetensors"),
              "baseConfigSha256": file_sha256(base / "rl_agent_config.json"), "developmentOnly": True}
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if report["tokenizer"]["truncated"]:
        raise ValueError("tokenizer check found truncation; increase max_len within encoder capacity before training")
    if args.dry_run:
        return
    out = Path(args.out)
    if not args.evaluate_only:
        out.mkdir(parents=True, exist_ok=False)
    if args.evaluate_only and args.runtime:
        import laya
        agent = laya.load(str(base), device=args.device)
        samples = {}
        for split in ("calibration", "test"):
            samples[split] = []
            for row in rows[split]:
                result = agent.predict(row["state"], row["questions"])
                if result["usage"].get("truncated"):
                    raise ValueError("runtime prediction truncated input")
                samples[split].append({"stateSha256": hashlib.sha256(row["state"].encode()).hexdigest(),
                                       "gold": row["expected"]["math_route"],
                                       "pLocal": result["answers"]["math_route"]["probabilities"]["local"]})
        evaluation = summarize_routing(samples)
        evaluation.update(inference="laya.Agent.predict; one question per call; API-rounded probabilities",
                          dtype=str(agent.dtype_for(1)), base=str(base), baseWeightsSha256=report["baseWeightsSha256"])
        with (out / "routing-runtime-evaluation.json").open("x", encoding="utf-8") as f:
            json.dump(evaluation, f, ensure_ascii=False, indent=2)
        print(json.dumps({k: v for k, v in evaluation.items() if k != "samples"}), flush=True)
        return
    torch.manual_seed(args.seed)
    model, tok, cfg = load_checkpoint(str(base))
    device = torch.device(args.device)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    model.to(device).eval()
    items = {}
    for name, data in rows.items():
        items[name], skipped = items_from_rows(tok, data, max_len, head_max_len)
        if skipped or len(items[name]) != len(data):
            raise ValueError("invalid training items: " + repr(skipped))
    parallel = uses_parallel_layout(cfg)
    def records(split):
        return calibration_records(model, tok, items[split], device, max_len, head_max_len,
                                   batch_size=args.micro_batch, parallel=parallel)
    if args.evaluate_only:
        samples = {name: routing_evaluation(records(name), rows[name], cfg) for name in ("calibration", "test")}
        evaluation = summarize_routing(samples)
        with (out / "routing-evaluation.json").open("x", encoding="utf-8") as f:
            json.dump(evaluation, f, ensure_ascii=False, indent=2)
        print(json.dumps({k: v for k, v in evaluation.items() if k != "samples"}), flush=True)
        return
    started = time.monotonic()
    report["beforeTest"] = evaluate_records(records("test"), cfg["temperature"], cfg.get("temperature_by_options"))
    config = TrainConfig(epochs=args.epochs, micro_batch=args.micro_batch, grad_accum=args.grad_accum,
                         loss="soft-ce", freeze_encoder=not args.full, head_lr=1e-4, encoder_lr=1e-5,
                         shuffle_options=("choice",), seed=args.seed, log_every=10,
                         max_len=max_len, head_max_len=head_max_len)
    report["trainingConfig"] = asdict(config)
    report["loss"] = train_model(model, tok, items["train"], config, device, max_len, head_max_len, parallel=parallel)
    report["encoderFrozen"] = all(not p.requires_grad for p in model.encoder.parameters())
    report["trainableParameters"] = sum(p.numel() for p in model.parameters() if p.requires_grad)
    calibrated = records("calibration")
    fitted = fit_temperature_map(calibrated)
    report["calibration"] = calibration_report(calibrated, fitted["temperature"])
    report["temperatureFit"] = fitted
    report["afterTest"] = evaluate_records(records("test"), fitted["temperature"], fitted["temperature_by_options"])
    report["elapsedSeconds"] = time.monotonic() - started
    if device.type == "cuda":
        torch.cuda.synchronize(device)
        report["peakAllocatedMiB"] = torch.cuda.max_memory_allocated(device) / 1024 ** 2
        report["peakReservedMiB"] = torch.cuda.max_memory_reserved(device) / 1024 ** 2
    cfg.update(max_len=max_len, fine_tuned=True, temperature=fitted["temperature"])
    cfg.pop("temperature_by_options", None)
    if fitted["temperature_by_options"]:
        cfg["temperature_by_options"] = fitted["temperature_by_options"]
    cfg["training"] = {"mathRoute": report}
    save_checkpoint(model, tok, cfg, str(out))
    (out / "questions.json").write_bytes((root / "questions.json").read_bytes())
    write_json(out / "report.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source", required=True)
    prep.add_argument("--out", required=True)
    prep.add_argument("--online-repeat", type=int, default=3)
    train = sub.add_parser("train")
    train.add_argument("--data", required=True)
    train.add_argument("--base", required=True, help="local multilingual checkpoint directory")
    train.add_argument("--out", required=True)
    train.add_argument("--fold", type=int, choices=range(5), default=0)
    train.add_argument("--epochs", type=int, default=1)
    train.add_argument("--micro-batch", type=int, default=2)
    train.add_argument("--grad-accum", type=int, default=8)
    train.add_argument("--max-len", type=int)
    train.add_argument("--seed", type=int, default=20261010)
    train.add_argument("--device", default="cuda")
    train.add_argument("--full", action="store_true", help="unfreeze encoder (default: frozen)")
    train.add_argument("--dry-run", action="store_true", help="verify data and tokenizer only; no checkpoint load/training")
    train.add_argument("--evaluate-only", action="store_true", help="evaluate --base without training; save new routing-evaluation.json in --out")
    train.add_argument("--runtime", action="store_true", help="with --evaluate-only: use Agent.predict, identical to serving precision and rounding")
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare(Path(args.source), Path(args.out), args.online_repeat)))
    else:
        run(args)


if __name__ == "__main__":
    main()
