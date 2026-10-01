"""Resumable local-model evaluation on an explicitly adapted ViText2SQL package.

Per-question data and model outputs stay git-ignored. Report local strict/relaxed
execution agreement; this is not the official ViText2SQL or Spider leaderboard metric.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import re
import sqlite3
import threading
import time
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool

from eval.datasets.external.download_vitext2sql import REPO_ROOT, sha256
from eval.harness.compare_local import metrics
from eval.harness.live_local import AGENT_INSTRUCTION, BASE_INSTRUCTION
from eval.harness.scoring import ResultSet, score_item
from eval.harness.sqlite_readonly import connect_readonly, execute_select
from t2sql.agent.build import build_agent, run_agent
from t2sql.agent.prompts import CALENDAR_WINDOW_RULES
from t2sql.llm.ollama_local import OllamaLocal, request_json

SOURCES = [
    "eval/harness/live_vitext2sql.py",
    "eval/harness/sqlite_readonly.py",
    "eval/harness/scoring.py",
    "eval/harness/compare_local.py",
    "eval/harness/metrics.py",
    "eval/harness/live_local.py",
    "eval/datasets/external/download_vitext2sql.py",
    "src/t2sql/agent/prompts.py",
    "src/t2sql/agent/build.py",
    "src/t2sql/agent/state.py",
    "src/t2sql/config.py",
    "src/t2sql/observability/tracing.py",
    "src/t2sql/llm/ollama_local.py",
]


def snapshot_sources(out: Path, expected: dict[str, str]):
    """Preserve the exact implementation before inference, without copying local secrets."""
    for name, digest in expected.items():
        source = (REPO_ROOT / name).read_bytes()
        if hashlib.sha256(source).hexdigest() != digest:
            raise ValueError(f"Source changed before snapshot: {name}")
        target = out / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source)


def acquire_run_lock(path: Path):
    stream = path.open("a+b")
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        stream.close()
        raise ValueError("Another worker owns this run; do not run concurrent resumes") from error
    return stream  # OS releases the lock on close or process termination.


def load_package(package: Path):
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in [
        ("questions.json", manifest["questions_sha256"]),
        ("exclusions.json", manifest["exclusions_sha256"]),
    ]:
        if sha256(package / name) != expected:
            raise ValueError(f"Package changed: {name}")
    for db_id, info in manifest["databases"].items():
        database = (package / info["path"]).resolve()
        if not database.is_relative_to(package.resolve()) or sha256(database) != info["sha256"]:
            raise ValueError(f"Database changed or path escapes package: {db_id}")
    items = json.loads((package / "questions.json").read_text(encoding="utf-8"))
    if len(items) != manifest["eligible_count"] or len({i["id"] for i in items}) != len(items):
        raise ValueError("Invalid question count or duplicate ID")
    return manifest, items


def select_pilot(items: list[dict], size: int) -> list[dict]:
    if size == 0:
        return items
    if size < 0 or size > len(items):
        raise ValueError("Invalid pilot size")
    rng = random.Random(42)
    databases = sorted({item["db_id"] for item in items})
    rng.shuffle(databases)
    selected = []
    for db_id in databases:
        candidates = [item for item in items if item["db_id"] == db_id]
        selected.append(rng.choice(candidates))
        if len(selected) == size:
            break
    if len(selected) < size:
        remaining = [item for item in items if item not in selected]
        selected.extend(rng.sample(remaining, size - len(selected)))
    ids = {item["id"] for item in selected}
    return [item for item in items if item["id"] in ids]


def evaluate_item(item: dict, variant: str, model: OllamaLocal, database: Path, context: str):
    conn = connect_readonly(database)
    attempts, budget = [], 1 if variant == "baseline" else 2
    lock = threading.Lock()
    model.audit.clear()

    def execute_sql(sql: str) -> dict:
        """Run a single native read-only SQLite SELECT and report execution errors."""
        with lock:
            if len(attempts) >= budget:
                return {"status": "error", "message": "execution budget exhausted", "data": {}}
            attempt = {"sql": sql}
            attempts.append(attempt)
            try:
                result = execute_select(conn, sql)
                attempt.update(status="ok", columns=result.columns, rows=result.rows)
                return {
                    "status": "ok",
                    "message": f"{len(result.rows)} rows",
                    "data": {
                        "columns": result.columns,
                        "rows": result.rows[:20],
                        "row_count": len(result.rows),
                        "preview_only": len(result.rows) > 20,
                    },
                }
            except Exception as error:
                attempt.update(status="error", message=f"{type(error).__name__}: {error}")
                return {"status": "error", "message": attempt["message"], "data": {}}

    try:
        gold = execute_select(conn, item["gold_sql"])
    except Exception:
        conn.close()
        raise  # Abort: invalid gold is not a model error and must not silently disappear.
    record = {
        "id": item["id"],
        "db_id": item["db_id"],
        "variant": variant,
        "question": item["question_vi"],
        "strict": False,
        "relaxed": False,
        "gold_empty": not gold.rows,
    }
    started = time.perf_counter()
    try:
        if variant == "baseline":
            response = model.invoke(
                [
                    SystemMessage(content=context + "\n" + BASE_INSTRUCTION),
                    HumanMessage(content=item["question_vi"]),
                ]
            )
            sql = re.sub(
                r"^```(?:sql)?\s*|\s*```$", "", response.content.strip(), flags=re.IGNORECASE
            )
            execute_sql(sql)
            record["status"] = attempts[-1]["status"]
        else:
            tool = StructuredTool.from_function(execute_sql)
            tool.metadata = {"self_logs": True}
            graph = build_agent(
                model=model,
                tools=[tool],
                max_iterations=3,
                prompt_text=context + "\n" + AGENT_INSTRUCTION,
            )
            run = run_agent(item["question_vi"], graph=graph, max_iterations=3)
            record.update(status=run["status"], tool_calls=run["tool_calls"], answer=run["answer"])
        if attempts and attempts[-1]["status"] == "ok" and record["status"] in {"ok", "executed"}:
            attempt = attempts[-1]
            detail = score_item(
                ResultSet(columns=attempt["columns"], rows=attempt["rows"]), gold, item["gold_sql"]
            )
            record.update(strict=detail.strict, relaxed=detail.relaxed, reason=detail.reason)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        # A stopped server/network timeout invalidates this prediction, not model accuracy.
        # Do not commit it: fail fast and resume from the last completed prediction.
        raise
    except Exception as error:
        record.update(status="error", error=f"{type(error).__name__}: {error}")
    finally:
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        conn.close()
    responses = list(model.audit)
    record.update(attempts=attempts, model_calls=len(responses), model_responses=responses)
    usage = [
        r["prompt_eval_count"] + r["eval_count"]
        for r in responses
        if "prompt_eval_count" in r and "eval_count" in r
    ]
    record["tokens"] = sum(usage) if usage and len(usage) == len(responses) else None
    return record


def read_records(path: Path, expected: set[tuple[str, str]]) -> list[dict]:
    records = (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if path.exists()
        else []
    )
    keys = [(item["id"], item["variant"]) for item in records]
    if len(set(keys)) != len(keys) or not set(keys).issubset(expected):
        raise ValueError("Duplicate or unexpected recorded predictions; cannot resume")
    return records


def summarize_records(config: dict, records: list[dict], *, complete: bool):
    summaries = {}
    for variant in config["variants"]:
        selected = [item for item in records if item["variant"] == variant]
        summaries[variant] = metrics(selected) if selected else {"n": 0}
        nonempty = [item for item in selected if not item["gold_empty"]]
        summaries[variant]["nonempty_gold"] = metrics(nonempty) if nonempty else {"n": 0}
        summaries[variant]["empty_gold_questions"] = len(selected) - len(nonempty)
    return {
        "complete": complete,
        "selection": config["selection"],
        "source_count": config["source_count"],
        "eligible_count": config["eligible_count"],
        "selected_questions": len(config["evaluated_ids"]),
        "completed_predictions": len(records),
        "expected_predictions": len(config["evaluated_ids"]) * len(config["variants"]),
        "metrics": summaries,
    }


def write_progress(out: Path, config: dict, records: list[dict], *, complete: bool):
    summary = summarize_records(config, records, complete=complete)
    temporary = out / "progress.tmp"
    temporary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    temporary.replace(out / "progress.json")
    if complete:
        (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--num-predict", type=int, default=4096)
    parser.add_argument("--pilot-size", type=int, default=0)
    parser.add_argument("--variant", choices=["both", "baseline", "agent"], default="both")
    parser.add_argument("--resume", type=Path)
    parser.add_argument(
        "--max-wall-seconds",
        type=int,
        default=0,
        help="Pause between predictions after this session budget; 0 means no time limit",
    )
    args = parser.parse_args()
    if args.num_predict < 1:
        parser.error("num-predict must be positive")
    if args.max_wall_seconds < 0:
        parser.error("max-wall-seconds must not be negative")
    session_started = time.monotonic()
    manifest, items = load_package(args.package)
    if manifest["split"] == "test" and args.pilot_size:
        parser.error("Use train or dev for a pilot; keep the adapted test split intact")
    selected = select_pilot(items, args.pilot_size)
    installed = next(
        (
            item
            for item in request_json(args.base_url, "/api/tags")["models"]
            if item["name"] == args.model
        ),
        None,
    )
    info = request_json(args.base_url, "/api/show", {"model": args.model})
    if (
        not installed
        or "cloud" in args.model.lower()
        or info.get("remote_model")
        or "tools" not in info.get("capabilities", [])
    ):
        raise ValueError("An installed local tool-capable model is required")
    variants = ["baseline", "agent"] if args.variant == "both" else [args.variant]
    settings = {
        "package": str(args.package.resolve()),
        "manifest_sha256": sha256(args.package / "manifest.json"),
        "label": "technical-pilot-unreviewed-adapted-benchmark"
        if args.pilot_size
        else "preliminary-unreviewed-adapted-benchmark",
        "selection": "fixed-seed-cross-database-pilot"
        if args.pilot_size
        else "all-eligible-questions",
        "source_count": manifest["source_count"],
        "eligible_count": manifest["eligible_count"],
        "model": args.model,
        "model_digest": installed["digest"],
        "api_version": request_json(args.base_url, "/api/version"),
        "model_options": {
            "num_predict": args.num_predict,
            "temperature": 0,
            "seed": 42,
            "num_ctx": 8192,
            "think": True,
        },
        "variants": variants,
        "evaluated_ids": [item["id"] for item in selected],
        "context_suffix": CALENDAR_WINDOW_RULES,
        "baseline_instruction": BASE_INSTRUCTION,
        "agent_instruction": AGENT_INSTRUCTION,
        "scoring": "repository strict/relaxed execution agreement, not official leaderboard scoring",
        "execution": "native SQLite SELECT; read-only authorizer; no business allowlist or LIMIT rewriting; 5s SQL deadline, 100000-row failure cap",
        "source_sha256": {name: sha256(REPO_ROOT / name) for name in SOURCES},
        "runtime": {
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "packages": {
                name: importlib.metadata.version(name)
                for name in (
                    "langgraph",
                    "langchain-core",
                    "sqlglot",
                    "pydantic",
                    "pydantic-settings",
                )
            },
        },
    }
    out = (
        args.resume
        or REPO_ROOT
        / "eval/results"
        / f"{datetime.now(UTC):%Y%m%d-%H%M%S-%f}-vitext2sql-{manifest['split']}"
    )
    if not out.resolve().is_relative_to((REPO_ROOT / "eval/results").resolve()):
        raise ValueError("Per-question external outputs must stay git-ignored under eval/results/")
    if not args.resume:
        out.mkdir(parents=True, exist_ok=False)
    with acquire_run_lock(out / "run.lock"):
        if args.resume:
            config = json.loads((out / "config.json").read_text(encoding="utf-8"))
            for key, value in settings.items():
                if config.get(key) != value:
                    raise ValueError(f"Resume incompatible with original run: {key}")
        else:
            config = settings
            snapshot_sources(out, config["source_sha256"])
        expected = {(item["id"], variant) for item in selected for variant in variants}
        records = read_records(out / "items.jsonl", expected)
        completed = {(item["id"], item["variant"]) for item in records}
        model = OllamaLocal(
            model_name=args.model, base_url=args.base_url, num_predict=args.num_predict
        )
        if not args.resume:
            model.invoke([HumanMessage(content="Reply OK.")])
            config["warmup"] = list(model.audit)
            (out / "config.json").write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        else:
            # An explicit compatible resume acknowledges the previous pause request.
            (out / "pause.request").unlink(missing_ok=True)
        print(f"Run: {out}", flush=True)
        write_progress(out, config, records, complete=completed == expected)
        with (out / "items.jsonl").open("a", encoding="utf-8") as stream:
            for index, item in enumerate(selected):
                order = variants if index % 2 == 0 else list(reversed(variants))
                for variant in order:
                    if (item["id"], variant) in completed:
                        continue
                    time_limit_reached = (
                        args.max_wall_seconds > 0
                        and time.monotonic() - session_started >= args.max_wall_seconds
                    )
                    if (out / "pause.request").exists() or time_limit_reached:
                        write_progress(out, config, records, complete=False)
                        print(
                            f"Paused: {len(records)}/{len(expected)} predictions saved", flush=True
                        )
                        return
                    database = args.package / manifest["databases"][item["db_id"]]["path"]
                    context = (
                        manifest["databases"][item["db_id"]]["context"] + CALENDAR_WINDOW_RULES
                    )
                    record = evaluate_item(item, variant, model, database, context)
                    stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                    records.append(record)
                    completed.add((item["id"], variant))
                    write_progress(out, config, records, complete=completed == expected)
                    print(
                        f"{len(records)}/{len(expected)} {item['id']}/{variant}: strict={record['strict']} {record['status']}",
                        flush=True,
                    )
        print(json.dumps(write_progress(out, config, records, complete=True), indent=2))


if __name__ == "__main__":
    main()
