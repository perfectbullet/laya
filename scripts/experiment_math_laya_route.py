#!/usr/bin/env python3
"""Assess the difficulty of the 250 math questions through a remote Laya server.

Laya receives only ``questions.question`` and predicts ``simple`` or ``difficult``.  The script
routes to the local solver only when the returned ``P(simple)`` clears a configurable threshold;
all other questions go online.  It records that policy with each result so it can later be compared
with the local model's measured correctness.  It does not call a math solver itself.

The default server is the Laya service on host 233.  Credentials are loaded with python-dotenv so
special characters in .env values are not interpreted by a shell.

Examples:
    python scripts/experiment_math_laya_route.py --dry-run
    python scripts/experiment_math_laya_route.py --experiment-id math-difficulty-ml-v3-p70
    python scripts/experiment_math_laya_route.py --experiment-id math-difficulty-td-v3-p70 \\
        --model typed-decisions
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import dotenv_values
from pymongo import ASCENDING, MongoClient


DEFAULT_LAYA_URL = "http://192.168.100.233:8000"
DEFAULT_COLLECTION = "laya_math_route_experiments"
DEFAULT_SIMPLE_THRESHOLD = 0.70
PROMPT_VERSION = "math-difficulty-prompt-v3"
ROUTER_VERSION = "math-difficulty-experiment-v3-p70"

# Keep this object byte-for-byte stable for one experiment.  Changing the wording changes the
# decision task and therefore needs a new experiment id and prompt version.
ROUTING_QUESTION: Dict[str, Dict[str, Any]] = {
    "math_difficulty": {
        "type": "choice",
        "instructions": (
            "判断下面这道中文高中数学题的解题难度。题目可能包含 LaTex、单选、多选、"
            "多小问、计算或证明。只根据题面中可见的条件、步骤和知识点判断；不要假设存在外部难度标注。"
            "只有能从题面确认它是简单、直接、基础的题才选 simple；其余情况一律选 difficult。不要解题，不要输出答案，不要解释。"
        ),
        "criteria": {
            "simple": (
                "仅限明显简单、直接的基础题：核心知识点明确，条件很少，通常可用标准公式、"
                "基本变形或极短推理完成。"
            ),
            "difficult": (
                "只要不能从题面明确确认是简单题，就选此项；包括需要多步推理、综合多个知识点、"
                "复杂分类讨论、严谨证明、较长计算，或条件繁多的多问、多选、几何、组合计数、概率和函数推导题。"
            ),
        },
    }
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def prompt_hash() -> str:
    encoded = json.dumps(ROUTING_QUESTION, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_config(env_file: str) -> Dict[str, str]:
    """Read .env without shell expansion; real environment variables take precedence."""
    config = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
    for key, value in os.environ.items():
        if value and (key.startswith("MONGODB_") or key.startswith("LAYA_")):
            config[key] = value
    return config


def mongo_database(config: Mapping[str, str]):
    database = config.get("MONGODB_DATABASE", "qwen_math_lab")
    uri = config.get("MONGODB_URI")
    if uri:
        client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
    else:
        missing = [key for key in ("MONGODB_HOST", "MONGODB_USERNAME", "MONGODB_PASSWORD") if not config.get(key)]
        if missing:
            raise ValueError("missing MongoDB configuration: %s" % ", ".join(missing))
        client = MongoClient(
            host=config["MONGODB_HOST"],
            port=int(config.get("MONGODB_PORT", "27017")),
            username=config["MONGODB_USERNAME"],
            password=config["MONGODB_PASSWORD"],
            authSource=config.get("MONGODB_AUTH_SOURCE", database),
            serverSelectionTimeoutMS=10_000,
        )
    client.admin.command("ping")
    return client[database]


def endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/v1/systemone"


def post_json(url: str, payload: Mapping[str, Any], api_key: Optional[str], timeout: float) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1_000]
        raise RuntimeError("HTTP %s: %s" % (error.code, detail)) from error
    except URLError as error:
        raise RuntimeError("network error: %s" % (error.reason,)) from error

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("server returned invalid JSON: %s" % (raw[:1_000],)) from error
    if not isinstance(decoded, dict):
        raise RuntimeError("server returned %s instead of a JSON object" % type(decoded).__name__)
    return decoded


def route_one(
    question: str,
    laya_url: str,
    model: Optional[str],
    api_key: Optional[str],
    timeout: float,
    simple_threshold: float,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"state": question, "questions": ROUTING_QUESTION}
    if model:
        payload["model"] = model

    started = time.monotonic()
    response = post_json(endpoint(laya_url), payload, api_key, timeout)
    duration_ms = round((time.monotonic() - started) * 1_000, 2)
    answer = response.get("answers", {}).get("math_difficulty")
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise RuntimeError("response has no choice answer for math_difficulty")

    probabilities = answer.get("probabilities")
    simple_probability = probabilities.get("simple") if isinstance(probabilities, dict) else None
    if not isinstance(simple_probability, (int, float)):
        # A missing probability must fail closed: the online solver is the safe fallback.
        simple_probability = None

    return {
        "status": "ok",
        "decision": answer.get("choice"),
        "derivedRoute": "local" if simple_probability is not None and simple_probability >= simple_threshold else "online",
        "answerConfidence": answer.get("answer_confidence"),
        "probabilities": probabilities if isinstance(probabilities, dict) else None,
        "simpleProbability": simple_probability,
        "simpleThreshold": simple_threshold,
        "lowConfidence": answer.get("low_confidence"),
        "abstention": answer.get("abstention"),
        "durationMs": duration_ms,
        "layaRouting": response.get("routing"),
        "layaUsage": response.get("usage"),
    }


def questions_to_route(db, limit: Optional[int], question_ids: Iterable[str]):
    query: Dict[str, Any] = {}
    requested_ids = list(question_ids)
    if requested_ids:
        query["id"] = {"$in": requested_ids}
    cursor = db.questions.find(
        query,
        {"_id": 0, "id": 1, "question": 1, "sortOrder": 1, "math_type": 1, "difficulty": 1, "tag": 1},
    ).sort([("sortOrder", ASCENDING), ("id", ASCENDING)])
    if limit is not None:
        cursor = cursor.limit(limit)
    return list(cursor)


def existing_question_ids(collection, experiment_id: str) -> set[str]:
    return {
        row["questionId"]
        for row in collection.find({"experimentId": experiment_id}, {"_id": 0, "questionId": 1})
        if isinstance(row.get("questionId"), str)
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="dotenv file with MongoDB and optional Laya API credentials")
    parser.add_argument("--laya-url", default=None, help="Laya base URL (default: LAYA_ROUTE_EXPERIMENT_URL or 233:8000)")
    parser.add_argument("--api-key", default=None, help="Laya bearer key (default: LAYA_API_KEY from env file)")
    parser.add_argument("--model", default="multilingual", help="checkpoint sent to Laya; use 'auto' to omit model and use server routing")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="MongoDB collection for per-question experiment rows")
    parser.add_argument("--experiment-id", default=None, help="stable identifier; reuse it with --skip-existing to resume")
    parser.add_argument("--question-id", action="append", default=[], help="route only this MongoDB questions.id; repeatable")
    parser.add_argument("--limit", type=int, default=None, help="maximum number of questions after filtering")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout seconds per question")
    parser.add_argument("--retries", type=int, default=1, help="retries after the initial request")
    parser.add_argument(
        "--simple-threshold",
        type=float,
        default=DEFAULT_SIMPLE_THRESHOLD,
        help="route locally only when probabilities.simple is at least this value (default: %(default)s)",
    )
    parser.add_argument("--skip-existing", action="store_true", help="with a stable experiment id, skip rows already saved")
    parser.add_argument("--dry-run", action="store_true", help="validate inputs and print the selected count without HTTP or MongoDB writes")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.retries < 0:
        parser.error("--retries must be zero or greater")
    if not 0.0 <= args.simple_threshold <= 1.0:
        parser.error("--simple-threshold must be between 0 and 1")
    return args


def main() -> int:
    args = parse_args()
    config = load_config(args.env_file)
    laya_url = args.laya_url or config.get("LAYA_ROUTE_EXPERIMENT_URL") or DEFAULT_LAYA_URL
    api_key = args.api_key if args.api_key is not None else config.get("LAYA_API_KEY")
    model = None if args.model.lower() == "auto" else args.model
    experiment_id = args.experiment_id or ("math-route-" + utc_now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])

    db = mongo_database(config)
    rows = questions_to_route(db, args.limit, args.question_id)
    if args.question_id:
        found = {row["id"] for row in rows}
        missing = sorted(set(args.question_id) - found)
        if missing:
            raise ValueError("unknown question ids: %s" % ", ".join(missing))
    if not rows:
        raise ValueError("no questions selected")

    collection = db[args.collection]
    already_done: set[str] = set()
    if args.skip_existing:
        already_done = existing_question_ids(collection, experiment_id)
        rows = [row for row in rows if row["id"] not in already_done]

    print(
        "experiment_id=%s selected=%d skipped_existing=%d model=%s simple_threshold=%.2f endpoint=%s"
        % (experiment_id, len(rows), len(already_done), model or "server-auto", args.simple_threshold, endpoint(laya_url))
    )
    if args.dry_run:
        return 0

    collection.create_index([("experimentId", ASCENDING), ("questionId", ASCENDING)], unique=True)
    collection.create_index([("createdAt", ASCENDING)])
    counts: Counter[str] = Counter()
    for number, row in enumerate(rows, start=1):
        question_id = row["id"]
        question = row.get("question")
        if not isinstance(question, str) or not question.strip():
            outcome: Dict[str, Any] = {"status": "input_error", "error": "question is missing or blank"}
        else:
            outcome = {}
            for attempt in range(args.retries + 1):
                try:
                    outcome = route_one(question, laya_url, model, api_key, args.timeout, args.simple_threshold)
                    break
                except Exception as error:  # An experiment should preserve an individual failure and continue.
                    outcome = {"status": "request_error", "error": str(error), "attempts": attempt + 1}
                    if attempt < args.retries:
                        time.sleep(1.0)

        document = {
            "experimentId": experiment_id,
            "routerVersion": ROUTER_VERSION,
            "promptVersion": PROMPT_VERSION,
            "promptSha256": prompt_hash(),
            "createdAt": utc_now(),
            "questionId": question_id,
            "questionSha256": hashlib.sha256(str(question).encode("utf-8")).hexdigest(),
            "questionMetadata": {
                "mathType": row.get("math_type"),
                "difficulty": row.get("difficulty"),
                "tag": row.get("tag"),
            },
            "request": {
                "layaUrl": laya_url,
                "endpoint": "/v1/systemone",
                "model": model,
                "simpleProbabilityThreshold": args.simple_threshold,
            },
            "outcome": outcome,
        }
        collection.update_one(
            {"experimentId": experiment_id, "questionId": question_id},
            {"$set": document},
            upsert=True,
        )
        counts[outcome["status"]] += 1
        print("[%d/%d] %s %s%s" % (
            number,
            len(rows),
            question_id,
            outcome["status"],
            " decision=" + str(outcome.get("decision")) if outcome.get("status") == "ok" else "",
        ))

    print("saved collection=%s summary=%s" % (args.collection, dict(sorted(counts.items()))))
    return 0 if not counts.get("request_error") and not counts.get("input_error") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("experiment failed: %s" % (error,), file=sys.stderr)
        raise SystemExit(2)
