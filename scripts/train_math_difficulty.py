"""Read-only Mongo export and disjoint five-fold difficulty fine-tuning on local hardware."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import unicodedata

from train_math_route import file_sha256, read_rows, write_json

LABELS = ("simple", "medium", "difficult")
MAPPING = {"简单": "simple", "中等": "medium", "困难": "difficult", "压轴": "difficult"}
QUESTIONS = {"math_difficulty": {
    "type": "choice",
    "instructions": "仅根据数学题题面判断解题难度，选择简单、中等或困难。不要假设有外部难度标注，"
                    "不要解题或输出答案。综合考虑知识点、推理步骤、条件分析和方法选择；"
                    "不要仅因题面长或公式多就判为困难。压轴题归为困难。",
    "criteria": {
        "simple": "简单：基础概念、直接代入或常规计算，方法明确，推理步骤少。",
        "medium": "中等：需要若干推理或计算步骤、常规方法组合或一定的条件分析，但不需要复杂综合。",
        "difficult": "困难：需要复杂综合、关键方法构造、深入分类讨论或较长证明推导；包含压轴题。",
    },
}}


def normalized_text(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def filter_excluded(rows, question_ids):
    excluded_ids = set(question_ids)
    unknown = excluded_ids - {r["questionId"] for r in rows}
    if unknown:
        raise ValueError("unknown excluded question IDs: " + repr(sorted(unknown)))
    kept = [r for r in rows if r["questionId"] not in excluded_ids]
    excluded = [{"questionId": r["questionId"], "label": r["label"],
                 "reason": "explicit_input_length_exclusion"} for r in rows if r["questionId"] in excluded_ids]
    return kept, excluded


def final_rows(rows, seed):
    if len({r["questionId"] for r in rows}) != len(rows):
        raise ValueError("duplicate IDs in final training data")
    return {"train": balanced(rows, seed), "calibration": [], "test": list(rows)}


def balanced(rows, seed):
    """Oversample only training rows to equal class counts; never create new unique cases."""
    rng = random.Random(seed)
    groups = {label: [r for r in rows if r["expected"]["math_difficulty"] == label] for label in LABELS}
    if any(not group for group in groups.values()):
        raise ValueError("training split missing a difficulty class")
    target = max(map(len, groups.values()))
    result = []
    for group in groups.values():
        result.extend(group)
        remaining = target - len(group)
        while remaining:
            cycle = list(group)
            rng.shuffle(cycle)
            result.extend(cycle[:remaining])
            remaining -= min(remaining, len(cycle))
    rng.shuffle(result)
    return result


def export(args):
    from prepare_math_route_data import assign_folds, write_jsonl
    from experiment_math_laya_route import load_config, mongo_database, utc_now
    out = Path(args.out)
    if out.exists():
        raise FileExistsError(out)
    db = mongo_database(load_config(args.env_file))
    try:
        questions = list(db.questions.find({}, {"_id": 0, "id": 1, "question": 1,
                                              "difficulty": 1, "math_type": 1, "image_path": 1}))
        evaluations = list(db.evaluations.find({"pipelineVersion": "evaluator-v1"},
                           {"_id": 0, "runId": 1, "questionId": 1, "math.verdict": 1, "runtime.status": 1}))
        runs = {r["id"]: r for r in db.runs.find({"id": {"$in": [e["runId"] for e in evaluations]}},
                                              {"_id": 0, "id": 1, "questionId": 1, "model": 1})}
        database = db.name
    finally:
        db.client.close()
    by_eval = defaultdict(Counter)
    for e in evaluations:
        run = runs.get(e["runId"], {})
        if run.get("model") == "nvidia/Qwen3.6-35B-A3B-NVFP4":
            if run.get("questionId") != e["questionId"]:
                raise ValueError("run/evaluation question mismatch")
            by_eval[e["questionId"]][e["math"]["verdict"]] += 1
    rows, seen = [], set()
    for q in sorted(questions, key=lambda q: q["id"]):
        if q["id"] in seen or q.get("difficulty") not in MAPPING or not q.get("question", "").strip():
            raise ValueError("duplicate ID, unknown difficulty or missing text")
        seen.add(q["id"])
        text = q["question"]
        rows.append({"questionId": q["id"], "text": text, "label": MAPPING[q["difficulty"]],
                     "originalDifficulty": q["difficulty"], "mathType": q.get("math_type", "unknown"),
                     "groupId": hashlib.sha256(normalized_text(text).encode()).hexdigest(),
                     "hasImagePath": bool(q.get("image_path")), "localEvaluation": dict(by_eval[q["id"]])})
    source_count = len(rows)
    rows, excluded = filter_excluded(rows, args.exclude_question_id)
    groups = defaultdict(set)
    for row in rows:
        groups[row["groupId"]].add(row["label"])
    if any(len(labels) != 1 for labels in groups.values()):
        raise ValueError("duplicate text has conflicting difficulty labels")
    assignment = assign_folds(rows, args.seed)
    samples = {r["questionId"]: {"state": r["text"], "questions": QUESTIONS,
               "expected": {"math_difficulty": r["label"]}, "questionId": r["questionId"]} for r in rows}
    out.mkdir(parents=True)
    write_json(out / "questions.json", QUESTIONS)
    write_jsonl(out / "all_labeled.jsonl", list(samples.values()))
    write_jsonl(out / "audit.jsonl", [{k: v for k, v in r.items() if k != "text"} for r in rows])
    write_jsonl(out / "excluded.jsonl", excluded)
    folds = []
    for fold in range(5):
        folder = out / ("fold-%d" % fold)
        folder.mkdir()
        counts = {}
        for split in ("train", "calibration", "test"):
            buckets = {fold} if split == "test" else {(fold + 1) % 5}
            selected = [samples[r["questionId"]] for r in rows if
                        (assignment[r["questionId"]] not in {fold, (fold + 1) % 5} if split == "train"
                         else assignment[r["questionId"]] in buckets)]
            original = dict(Counter(r["expected"]["math_difficulty"] for r in selected))
            if split == "train":
                selected = balanced(selected, args.seed + fold)
            write_jsonl(folder / (split + ".jsonl"), selected)
            counts[split] = {"unique": original, "rows": dict(Counter(r["expected"]["math_difficulty"] for r in selected))}
        folds.append(counts)
    write_json(out / "manifest.json", {"createdAt": utc_now().isoformat(), "database": database,
               "seed": args.seed, "labels": dict(Counter(r["label"] for r in rows)), "folds": folds,
               "sourceQuestions": source_count, "includedQuestions": len(rows), "excluded": excluded,
               "promptVersion": "math-difficulty-threeclass-v1", "localModel": "nvidia/Qwen3.6-35B-A3B-NVFP4",
               "pipelineVersion": "evaluator-v1", "developmentOnly": True,
               "notes": ["Difficulty labels are targets, never inference inputs.",
                         "Image paths may identify screenshots, not necessarily missing visual conditions; not sent to model.",
                         "Exact duplicate groups stay in one bucket; related variants require manual review.",
                         "Only historical evaluated questions can be used for solver-error estimates."],
               "files": {str(p.relative_to(out)): file_sha256(p) for p in out.rglob("*") if p.is_file()}})
    print((out / "manifest.json").read_text(), flush=True)


def metrics(samples, audit):
    confusion = {gold: {pred: 0 for pred in LABELS} for gold in LABELS}
    for s in samples:
        confusion[s["gold"]][s["choice"]] += 1
    recall = {label: confusion[label][label] / sum(confusion[label].values()) if sum(confusion[label].values()) else None
              for label in LABELS}
    policies = {}
    for name, allow in (("simple_only", {"simple"}), ("simple_medium", {"simple", "medium"})):
        selected = [s for s in samples if s["choice"] in allow]
        verdicts = Counter()
        evaluated = 0
        wrong_questions = 0
        for s in selected:
            ev = audit[s["questionId"]]["localEvaluation"]
            verdicts.update(ev)
            evaluated += bool(ev)
            wrong_questions += bool(ev.get("incorrect"))
        resolved = verdicts["correct"] + verdicts["incorrect"]
        policies[name] = {"localQuestions": len(selected), "localCoverage": len(selected) / len(samples),
                          "evaluatedLocalQuestions": evaluated, "unevaluatedLocalQuestions": len(selected) - evaluated,
                          "knownIncorrectQuestions": wrong_questions, "attemptVerdicts": dict(verdicts),
                          "resolvedAttemptErrorRate": verdicts["incorrect"] / resolved if resolved else None,
                          "note": "Historical local-attempt error on evaluated subset; not end-to-end routing accuracy."}
    return {"items": len(samples), "accuracy": sum(s["gold"] == s["choice"] for s in samples) / len(samples),
            "macroRecall": sum(r for r in recall.values() if r is not None) / sum(r is not None for r in recall.values()),
            "recall": recall, "confusion": confusion, "policies": policies}


def runtime(agent, rows):
    result = []
    for row in rows:
        response = agent.predict(row["state"], row["questions"])
        if response["usage"].get("truncated"):
            raise ValueError("runtime input truncated: " + row["questionId"] + " " + json.dumps(response["usage"]))
        answer = response["answers"]["math_difficulty"]
        result.append({"questionId": row["questionId"], "gold": row["expected"]["math_difficulty"],
                       "choice": answer["choice"], "probabilities": answer["probabilities"]})
    return result


def train(args):
    import torch
    import laya
    from laya.calibrate import records_from_labeled, fit_temperature_map
    from laya.common import build_sequence
    from laya.train import TrainConfig, load_checkpoint, save_checkpoint, items_from_rows, to_internal, train_model
    root, base, out = Path(args.data), Path(args.base), Path(args.out)
    manifest = json.loads((root / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        if file_sha256(root / name) != digest:
            raise ValueError("snapshot changed: " + name)
    final = args.command == "final"
    if final:
        # No independent test remains: "test" here is only the explicitly marked training replay.
        rows = final_rows(read_rows(root / "all_labeled.jsonl"), args.seed)
    else:
        rows = {s: read_rows(root / ("fold-%d/%s.jsonl" % (args.fold, s))) for s in ("train", "calibration", "test")}
        sets = [{normalized_text(r["state"]) for r in rows[s]} for s in rows]
        if any(sets[i] & sets[j] for i in range(3) for j in range(i)):
            raise ValueError("split leakage")
    audit = {r["questionId"]: r for r in read_rows(root / "audit.jsonl")}
    out.mkdir(parents=True, exist_ok=False)
    torch.manual_seed(args.seed)
    original = laya.load(str(base), device="cuda")
    baseline = runtime(original, rows["test"])
    del original
    gc.collect()
    torch.cuda.empty_cache()
    model, tok, cfg = load_checkpoint(str(base))
    lengths = []
    for row in read_rows(root / "all_labeled.jsonl"):
        ids, _, stats = build_sequence(tok, row["state"], to_internal("math_difficulty", QUESTIONS["math_difficulty"]),
                                      1024, 256, return_truncation_stats=True)
        if stats["truncated"]:
            raise ValueError("tokenizer input truncated")
        lengths.append(len(ids))
    items, skipped = items_from_rows(tok, rows["train"], 1024, 256)
    if skipped or len(items) != len(rows["train"]):
        raise ValueError("invalid training items")
    config = TrainConfig(epochs=args.epochs, micro_batch=2, grad_accum=8, loss="soft-ce", freeze_encoder=True,
                         head_lr=1e-4, shuffle_options=("choice",), seed=args.seed, max_len=1024, head_max_len=256,
                         log_every=100)
    device = torch.device("cuda")
    model.to(device)
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    losses = train_model(model, tok, items, config, device, 1024, 256)
    report = {"fold": None if final else args.fold, "config": asdict(config), "loss": losses,
              "protocol": "all-data-final" if final else "disjoint-fivefold", "developmentOnly": True,
              "independentEvaluationAvailable": not final,
              "uniqueTrainingQuestions": len({r["questionId"] for r in rows["train"]}),
              "trainingRows": len(rows["train"]),
              "trainingClassCounts": dict(Counter(r["expected"]["math_difficulty"] for r in rows["train"])),
              "elapsedSeconds": time.monotonic() - started, "maxSequenceTokens": max(lengths),
              "peakAllocatedMiB": torch.cuda.max_memory_allocated() / 1024 ** 2,
              "dataManifestSha256": file_sha256(root / "manifest.json"), "baseWeightSha256": file_sha256(base / "model.safetensors"),
              "baseConfigSha256": file_sha256(base / "rl_agent_config.json")}
    cfg.update(max_len=1024, head_max_len=256, temperature=[1.0, 1.0, 1.0], fine_tuned=True)
    cfg.pop("temperature_by_options", None)
    save_checkpoint(model, tok, cfg, str(out))
    write_json(out / "questions.json", QUESTIONS)
    del model, tok, items
    gc.collect()
    torch.cuda.empty_cache()
    agent = laya.load(str(out), device="cuda")
    pairs = [(r["state"], r["questions"], {"math_difficulty": [float(label == r["expected"]["math_difficulty"])
              for label in LABELS]}) for r in rows["calibration"]]
    fitted = ({"temperature": [1.0, 1.0, 1.0], "temperature_by_options": {}} if final
              else fit_temperature_map(records_from_labeled(agent, pairs)))
    report.update(temperatureFit=fitted, calibrationDtype=None if final else str(agent.dtype_for(1)),
                  calibrationStatus="not-fitted-no-independent-data" if final else "independent-runtime-logits",
                  probabilitiesCalibrated=not final)
    cfg.update(temperature=fitted["temperature"], temperature_by_options=fitted["temperature_by_options"])
    cfg["training"] = {"mathDifficulty": report}
    write_json(out / "rl_agent_config.json", cfg)
    del agent
    gc.collect()
    torch.cuda.empty_cache()
    agent = laya.load(str(out), device="cuda")
    samples = runtime(agent, rows["test"])
    report.update({"baselineTrainingReplay" if final else "baseline": metrics(baseline, audit),
                   "trainingReplay" if final else "trained": metrics(samples, audit)})
    if final:
        assert file_sha256(base / "model.safetensors") == report["baseWeightSha256"]
        assert file_sha256(base / "rl_agent_config.json") == report["baseConfigSha256"]
        report["originalModelUnchanged"] = True
        cfg["training"] = {"mathDifficulty": report}
        write_json(out / "rl_agent_config.json", cfg)
    write_json(out / "report.json", report)
    write_json(out / "runtime-evaluation.json", {"baselineTrainingReplay" if final else "baseline": baseline,
               "trainingReplay" if final else "trained": samples,
               "independentEvaluationAvailable": not final})
    print(json.dumps(report, ensure_ascii=False), flush=True)


def benchmark(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    base = Path(args.base)
    hashes = {n: file_sha256(base / n) for n in ("model.safetensors", "rl_agent_config.json")}
    samples = {"baseline": [], "trained": []}
    for fold in range(5):
        print("Running difficulty fold", fold, flush=True)
        with (out / ("fold-%d.log" % fold)).open("x") as log:
            subprocess.run([sys.executable, "-u", __file__, "train", "--data", args.data, "--base", args.base,
                            "--out", str(out / ("fold-%d" % fold)), "--fold", str(fold), "--epochs", str(args.epochs),
                            "--seed", str(args.seed)], stdout=log, stderr=subprocess.STDOUT, check=True)
        ev = json.loads((out / ("fold-%d" % fold) / "runtime-evaluation.json").read_text())
        for name in samples:
            samples[name].extend(ev[name])
        print(json.dumps(json.loads((out / ("fold-%d" % fold) / "report.json").read_text())["trained"]), flush=True)
    if any(len({r["questionId"] for r in group}) != len(group) for group in samples.values()):
        raise ValueError("test IDs repeated across folds")
    if hashes != {n: file_sha256(base / n) for n in hashes}:
        raise ValueError("original checkpoint changed")
    audit = {r["questionId"]: r for r in read_rows(Path(args.data) / "audit.jsonl")}
    summary = {"epochs": args.epochs, "baseHashes": hashes, "originalModelUnchanged": True,
               "developmentOnly": True, "sampling": "train-only equal-class oversampling",
               **{name: metrics(group, audit) for name, group in samples.items()}}
    write_json(out / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "train", "benchmark", "final"))
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--data")
    parser.add_argument("--base")
    parser.add_argument("--out", required=True)
    parser.add_argument("--fold", type=int, default=0)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261010)
    parser.add_argument("--exclude-question-id", action="append", default=[],
                        help="export only: exclude an audited overlength question ID; repeat for multiple IDs")
    args = parser.parse_args()
    if args.epochs < 1 or not 0 <= args.fold < 5:
        parser.error("invalid epochs/fold")
    {"export": export, "train": train, "benchmark": benchmark, "final": train}[args.command](args)


if __name__ == "__main__":
    main()
