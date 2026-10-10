#!/usr/bin/env python3
"""Export audited MongoDB labels and five reproducible train/calibration/test folds.

Read-only against MongoDB. Output must be a new directory. No inference or training is run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from experiment_math_laya_route import load_config, mongo_database, utc_now


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def normalized_text(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def label_for(capability):
    """Fail closed on contradictory/incomplete labels; do not train on unknowns."""
    if capability.get("labelUsable") is not True:
        return None, "label_unusable"
    details = capability.get("attemptDetails", [])
    if capability.get("attempts") != 3 or len(details) != 3:
        return None, "expected_three_attempts"
    run_ids = [detail.get("runId") for detail in details]
    if not all(run_ids) or len(set(run_ids)) != 3:
        return None, "invalid_attempt_ids"
    rate = capability.get("localSuccessRate")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate):
        return None, "invalid_success_rate"
    runtime = capability.get("runtime", {})
    counted = Counter(detail.get("runtimeStatus") for detail in details)
    for status in ("completed", "truncated", "failed", "cancelled", "interrupted"):
        if runtime.get(status, 0) != counted[status]:
            return None, "runtime_summary_mismatch"
    if any(counted[status] for status in ("truncated", "failed", "cancelled", "interrupted")):
        return "online", "runtime_failure"
    if counted["completed"] != 3:
        return None, "unknown_runtime_status"
    verdicts = [detail.get("mathVerdict") for detail in details]
    if any(verdict not in ("correct", "incorrect") for verdict in verdicts):
        return None, "unresolved_verdict"
    successes = verdicts.count("correct")
    if (capability.get("gradableAttempts") != 3
            or capability.get("localSuccessCount") != successes
            or not math.isclose(rate, successes / 3, abs_tol=1e-6)):
        return None, "success_summary_mismatch"
    return ("local", "three_completed_correct") if successes == 3 else ("online", "math_failure")


def assign_folds(rows, seed, count=5):
    """Stratify by label, balance types, keeping every explicit/exact-duplicate group intact."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["groupId"]].append(row)
    rng = random.Random(seed)
    ordered = list(groups.values())
    rng.shuffle(ordered)
    ordered.sort(key=lambda group: (-len(group), -sum(r["label"] == "online" for r in group)))
    totals = [Counter() for _ in range(count)]
    types = [Counter() for _ in range(count)]
    sizes = [0] * count
    assignment = {}
    for group in ordered:
        labels = Counter(row["label"] for row in group)
        strata = Counter((row["label"], row["mathType"]) for row in group)
        candidates = list(range(count))
        rng.shuffle(candidates)
        chosen = min(candidates, key=lambda fold: (
            sum(totals[fold][label] * n for label, n in labels.items()),
            sizes[fold],
            sum(types[fold][key] * n for key, n in strata.items()),
        ))
        for row in group:
            assignment[row["questionId"]] = chosen
        totals[chosen].update(labels)
        types[chosen].update(strata)
        sizes[chosen] += len(group)
    return assignment


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
                            for row in rows), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--capability-version", default="capability-v1")
    parser.add_argument("--seed", default=20261010, type=int)
    parser.add_argument("--groups-file", type=Path,
                        help="optional JSON mapping questions.id to manually reviewed family/group ID")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("--out must be a new directory; existing exports are never overwritten")
    questions_schema = json.loads(Path(__file__).with_name("math_route_questions.json").read_text(encoding="utf-8"))
    manual_groups = json.loads(args.groups_file.read_text(encoding="utf-8")) if args.groups_file else {}
    if not isinstance(manual_groups, dict) or any(not isinstance(v, str) or not v for v in manual_groups.values()):
        parser.error("--groups-file must map question IDs to nonempty string group IDs")
    db = mongo_database(load_config(args.env_file))
    try:
        questions = list(db.questions.find({}, {"_id": 0, "id": 1, "question": 1, "math_type": 1}))
        capabilities = list(db.question_capabilities.find(
            {"capabilityVersion": args.capability_version}, {"_id": 0}))
    finally:
        db.client.close()
    ids = [row.get("id") for row in questions]
    cap_ids = [row.get("questionId") for row in capabilities]
    if len(set(ids)) != len(ids) or len(set(cap_ids)) != len(cap_ids):
        raise ValueError("duplicate question/capability IDs; export aborted")
    if set(manual_groups) - set(ids):
        raise ValueError("manual groups contain unknown question IDs")
    by_id = {row["questionId"]: row for row in capabilities}
    rows, excluded = [], []
    for question in sorted(questions, key=lambda row: row["id"]):
        qid = question["id"]
        cap = by_id.get(qid)
        text = question.get("question")
        if not isinstance(text, str) or not text.strip():
            excluded.append({"questionId": qid, "reason": "missing_question_text"})
            continue
        if cap is None:
            excluded.append({"questionId": qid, "reason": "missing_capability"})
            continue
        if cap.get("question") and normalized_text(cap["question"]) != normalized_text(text):
            excluded.append({"questionId": qid, "reason": "capability_question_mismatch"})
            continue
        label, reason = label_for(cap)
        if label is None:
            excluded.append({"questionId": qid, "reason": reason})
            continue
        rows.append({
            "questionId": qid, "text": text, "label": label, "reason": reason,
            "mathType": question.get("math_type") or cap.get("mathType") or "unknown",
            "groupId": "manual:" + manual_groups[qid] if qid in manual_groups else "text:" + digest(normalized_text(text)),
            "capability": {key: cap.get(key) for key in (
                "capabilityVersion", "evaluatorPipelineVersion", "updatedAt", "labelUsable", "attempts",
                "gradableAttempts", "localSuccessCount", "localSuccessRate", "runtime", "attemptDetails")},
        })
    if not rows:
        raise ValueError("no auditable labels found")
    # Exact duplicates must remain together even if a manual mapping was inconsistent or partial.
    duplicate_groups = defaultdict(list)
    for row in rows:
        duplicate_groups[normalized_text(row["text"])].append(row)
    for group in duplicate_groups.values():
        if len({row["groupId"] for row in group}) > 1:
            raise ValueError("exact duplicate text has conflicting manual groups; fix --groups-file")
        if len({row["label"] for row in group}) > 1:
            raise ValueError("exact duplicate text has conflicting labels; audit before training")
    assignment = assign_folds(rows, args.seed)
    samples = {row["questionId"]: {
        "state": row["text"], "questions": questions_schema, "expected": {"math_route": row["label"]},
    } for row in rows}
    args.out.mkdir(parents=True)
    write_json(args.out / "questions.json", questions_schema)
    write_jsonl(args.out / "all_labeled.jsonl", list(samples.values()))
    write_jsonl(args.out / "excluded.jsonl", excluded)
    audit = [{key: value for key, value in row.items() if key != "text"} | {
        "questionSha256": hashlib.sha256(row["text"].encode()).hexdigest(),
        "bucket": assignment[row["questionId"]],
    } for row in rows]
    write_jsonl(args.out / "label_audit.jsonl", audit)
    folds = []
    for fold in range(5):
        folder = args.out / ("fold-%d" % fold)
        folder.mkdir()
        splits = {"test": fold, "calibration": (fold + 1) % 5}
        report = {}
        for split in ("train", "calibration", "test"):
            selected = [row for row in rows if (
                assignment[row["questionId"]] not in splits.values() if split == "train"
                else assignment[row["questionId"]] == splits[split])]
            write_jsonl(folder / (split + ".jsonl"), [samples[row["questionId"]] for row in selected])
            report[split] = {"questionIds": [row["questionId"] for row in selected],
                             "labels": dict(Counter(row["label"] for row in selected)),
                             "count": len(selected)}
        folds.append({"fold": fold, "splits": report})
    manifest = {
        "createdAt": utc_now().isoformat(), "seed": args.seed,
        "database": db.name, "capabilityVersion": args.capability_version,
        "promptVersion": "math-route-prompt-v1", "promptSha256": digest(questions_schema),
        "baseModel": "multilingual", "sourceQuestions": len(questions),
        "sourceCapabilities": len(capabilities), "included": len(rows),
        "labels": dict(Counter(row["label"] for row in rows)),
        "excluded": dict(Counter(row["reason"] for row in excluded)),
        "grouping": "NFKC + whitespace-normalized exact text; optional manual family groups; no similarity model",
        "manualGroups": manual_groups, "folds": folds,
        "files": {str(path.relative_to(args.out)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in sorted(args.out.rglob("*")) if path.is_file()},
        "notes": ["Development cross-validation only: these questions were used for earlier prompt selection.",
                  "Review related variants manually before relying on fold metrics.",
                  "Train/calibration/test are separate; do not pass calibration.jsonl as training data.",
                  "Stock laya-train splits calibration randomly inside --data; an explicit-split training wrapper is needed.",
                  "Do not carry the zero-shot P(simple)>=0.70 threshold over to the fine-tuned model."],
    }
    write_json(args.out / "manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("included", "labels", "excluded", "promptSha256")},
                     ensure_ascii=False, indent=2))
    print("saved", args.out.resolve())


if __name__ == "__main__":
    main()
