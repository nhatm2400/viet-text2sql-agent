"""Paired real-model baseline vs bounded LangGraph agent on a local Ollama server.

Development runs are provisional. Test runs require a frozen, human-reviewed package.
Does not install/pull models, contact paid APIs, or fall back to replayed fixtures.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool

from eval.harness.metrics import percentile
from eval.harness.prepare_v2 import digest, sqlite_sql
from eval.harness.scoring import ResultSet, score_item
from t2sql.agent.build import build_agent, run_agent
from t2sql.agent.prompts import CALENDAR_WINDOW_RULES
from t2sql.guardrails.ast_policy import check_sql
from t2sql.llm.ollama_local import OllamaLocal, request_json
from t2sql.tools.glossary_tools import glossary_block
from t2sql.tools.schema_tools import schema_block

ROOT = Path(__file__).resolve().parents[2]
BASE_INSTRUCTION = "Return exactly one SQLite SELECT query, with no explanation or markdown."
AGENT_INSTRUCTION = (
    "Answer the question by calling execute_sql with SQLite SELECT SQL. "
    "You may execute at most twice; after an error, correct its cause once. "
    "Use one tool call at a time. After successful execution, give a short final answer."
)


def build_context(schema_context: str, date_windows: str) -> str:
    context = (
        "You answer Vietnamese analytics questions on this fixed synthetic database. "
        "Honor explicit definitions and dates in the question. Monetary outputs use stated rounding.\n"
        + schema_block(include_checks=schema_context == "with-checks")
        + "\nBusiness glossary:\n"
        + glossary_block()
    )
    return context + CALENDAR_WINDOW_RULES if date_windows == "half-open" else context


def load_package(package: Path, split: str) -> tuple[dict, list[dict]]:
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if digest(package / "snapshot.sqlite") != manifest["snapshot_sha256"]:
        raise ValueError("Snapshot hash mismatch")
    if split == "test":
        if not (package / "frozen.json").exists():
            raise ValueError("Test evaluation requires human review and prepare_v2 --freeze first")
        frozen = json.loads((package / "frozen.json").read_text(encoding="utf-8"))
        if frozen["questions_sha256"] != digest(package / "questions.json"):
            raise ValueError("Questions changed after freeze; create a new benchmark version")
    items = json.loads((package / "questions.json").read_text(encoding="utf-8"))
    return manifest, [i for i in items if i["split"] == split]


def execute_query(conn, sql):
    deadline = time.perf_counter() + 5
    conn.set_progress_handler(lambda: int(time.perf_counter() > deadline), 1000)
    try:
        cursor = conn.execute(sqlite_sql(sql))
        return ResultSet(columns=[c[0] for c in cursor.description], rows=cursor.fetchall())
    finally:
        conn.set_progress_handler(None, 0)


def select_items(items: list[dict], split: str, ids: list[str] | None, limit: int) -> list[dict]:
    if split == "test" and (ids or limit):
        raise ValueError("Test runs must use the full split")
    if ids:
        if limit or len(ids) != len(set(ids)):
            raise ValueError("Use unique IDs without --limit")
        unknown = set(ids) - {item["id"] for item in items}
        if unknown:
            raise ValueError(f"Unknown question IDs: {sorted(unknown)}")
        items = [item for item in items if item["id"] in ids]
    elif limit:
        items = items[:limit]
    if not items:
        raise ValueError("No questions selected")
    return items


def evaluate_item(
    item: dict, variant: str, model: OllamaLocal, database: Path, context: str
) -> dict:
    conn = sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False
    )
    conn.execute("PRAGMA query_only=ON")
    lock = threading.Lock()
    attempts = []
    budget = 1 if variant == "baseline" else 2
    model.audit.clear()

    def execute_sql(sql: str) -> dict:
        """Execute one read-only SELECT. Returns policy/execution errors for one bounded repair."""
        with lock:
            if len(attempts) >= budget:
                return {"status": "error", "message": "execution budget exhausted", "data": {}}
            record = {"sql": sql}
            attempts.append(record)
            decision = check_sql(sql)
            if not decision.allowed:
                record.update(status="blocked", message="; ".join(decision.reasons))
                return {"status": "blocked", "message": record["message"], "data": {}}
            try:
                result = execute_query(conn, decision.rewritten_sql)
                record.update(
                    status="ok",
                    sql=decision.rewritten_sql,
                    columns=result.columns,
                    rows=result.rows,
                )
                return {
                    "status": "ok",
                    "message": f"{len(result.rows)} rows",
                    "data": {
                        "executed_sql": decision.rewritten_sql,
                        "columns": result.columns,
                        "rows": [
                            dict(zip(result.columns, r, strict=True)) for r in result.rows[:20]
                        ],
                        "row_count": len(result.rows),
                        "preview_only": len(result.rows) > 20,
                    },
                }
            except Exception as err:
                record.update(status="error", message=f"{type(err).__name__}: {err}")
                return {"status": "error", "message": record["message"], "data": {}}

    record = {
        "id": item["id"],
        "variant": variant,
        "question": item["question_vi"],
        "strict": False,
        "relaxed": False,
    }
    try:
        gold = execute_query(conn, item["gold_sql"])
    except Exception:
        conn.close()
        raise  # Invalid gold invalidates the run, never counted as a model miss.
    started = time.perf_counter()
    try:
        if variant == "baseline":
            response = model.invoke(
                [
                    SystemMessage(content=context + "\n" + BASE_INSTRUCTION),
                    HumanMessage(content=item["question_vi"]),
                ]
            )
            text = response.content.strip()
            sql = re.sub(r"^```(?:sql)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
            execute_sql(sql)
            record["status"] = attempts[-1]["status"]
        else:
            tool = StructuredTool.from_function(execute_sql)
            tool.metadata = {
                "self_logs": True
            }  # result/trace is captured below, no external trace sink
            graph = build_agent(
                model=model,
                tools=[tool],
                max_iterations=3,
                prompt_text=context + "\n" + AGENT_INSTRUCTION,
            )
            run = run_agent(item["question_vi"], graph=graph, max_iterations=3)
            record.update(status=run["status"], tool_calls=run["tool_calls"], answer=run["answer"])
        if attempts and attempts[-1]["status"] == "ok" and record["status"] in {"ok", "executed"}:
            last = attempts[-1]
            detail = score_item(
                ResultSet(columns=last["columns"], rows=last["rows"]), gold, item["gold_sql"]
            )
            record.update(strict=detail.strict, relaxed=detail.relaxed, reason=detail.reason)
    except Exception as err:
        record.update(status="error", error=f"{type(err).__name__}: {err}")
    finally:
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        conn.close()
    record.update(
        attempts=attempts, model_calls=len(model.audit), model_responses=list(model.audit)
    )
    usage = [
        r["prompt_eval_count"] + r["eval_count"]
        for r in model.audit
        if "prompt_eval_count" in r and "eval_count" in r
    ]
    record["tokens"] = sum(usage) if usage and len(usage) == len(model.audit) else None
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=ROOT / "data/benchmark_v2_ready")
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--num-predict", type=int, default=2048, help="Output tokens per model call"
    )
    parser.add_argument("--ids", nargs="+", help="Explicit development question IDs for a pilot")
    parser.add_argument(
        "--schema-context",
        choices=["types-and-fks", "with-checks"],
        default="with-checks",
        help="Schema constraints in model context; types-and-fks reproduces the earlier context",
    )
    parser.add_argument(
        "--date-windows",
        choices=["unchanged", "half-open"],
        default="half-open",
        help="Calendar timestamp guidance; unchanged reproduces the earlier prompt",
    )
    args = parser.parse_args()
    if args.repeats < 1 or args.limit < 0 or args.num_predict < 1:
        parser.error("repeats >= 1; limit >= 0; num-predict >= 1")
    manifest, items = load_package(args.package, args.split)
    try:
        items = select_items(items, args.split, args.ids, args.limit)
    except ValueError as err:
        parser.error(str(err))
    tags = request_json(args.base_url, "/api/tags")
    installed = next((m for m in tags["models"] if m["name"] == args.model), None)
    if not installed or "cloud" in args.model.lower():
        raise ValueError(
            "Requested model must already be installed locally; cloud models forbidden"
        )
    model_info = request_json(args.base_url, "/api/show", {"model": args.model})
    if model_info.get("remote_model") or "tools" not in model_info.get("capabilities", []):
        raise ValueError("Model must support local tool calling")
    model = OllamaLocal(model_name=args.model, base_url=args.base_url, num_predict=args.num_predict)
    context = build_context(args.schema_context, args.date_windows)
    # Warm-up is recorded separately and excluded from per-item latency for both variants.
    model.invoke([HumanMessage(content="Reply OK.")])
    warmup = list(model.audit)
    out = ROOT / "eval/results" / f"{datetime.now(UTC):%Y%m%d-%H%M%S-%f}-live-local-{args.split}"
    out.mkdir(parents=True, exist_ok=False)
    config = {
        "model": args.model,
        "model_digest": installed["digest"],
        "split": args.split,
        "label": "human-reviewed-test" if args.split == "test" else "provisional-AI-authored-dev",
        "snapshot": manifest,
        "questions_sha256": digest(args.package / "questions.json"),
        "context": context,
        "schema_context": args.schema_context,
        "date_windows": args.date_windows,
        "baseline_instruction": BASE_INSTRUCTION,
        "agent_instruction": AGENT_INSTRUCTION,
        "model_options": {
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": model.num_predict,
            "seed": 42,
            "think": True,
        },
        "warmup": warmup,
        "repeats": args.repeats,
        "evaluated_ids": [item["id"] for item in items],
        "selection": "pilot" if args.ids or args.limit else "full-split",
        "api_version": request_json(args.base_url, "/api/version"),
        "source_sha256": {
            p: digest(ROOT / p)
            for p in [
                "eval/harness/live_local.py",
                "src/t2sql/llm/ollama_local.py",
                "src/t2sql/agent/build.py",
                "src/t2sql/agent/prompts.py",
                "eval/harness/scoring.py",
                "src/t2sql/tools/schema_tools.py",
                "db/schema.sql",
            ]
        },
    }
    (out / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    records = []
    with (out / "items.jsonl").open("w", encoding="utf-8") as stream:
        for repeat in range(args.repeats):
            for index, item in enumerate(items):
                variants = (
                    ["baseline", "agent"] if (index + repeat) % 2 == 0 else ["agent", "baseline"]
                )
                for variant in variants:
                    record = evaluate_item(
                        item, variant, model, args.package / "snapshot.sqlite", context
                    )
                    record["repeat"] = repeat
                    records.append(record)
                    stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    stream.flush()
                    print(
                        f"{repeat}/{item['id']}/{variant}: strict={record['strict']} {record['status']}",
                        flush=True,
                    )
    summary = {}
    for variant in ["baseline", "agent"]:
        selected = [r for r in records if r["variant"] == variant]
        n = len(selected)
        summary[variant] = {
            "n": n,
            "strict_correct": sum(r["strict"] for r in selected),
            "relaxed_correct": sum(r["relaxed"] for r in selected),
            "strict_ex": 100 * sum(r["strict"] for r in selected) / n,
            "relaxed_ex": 100 * sum(r["relaxed"] for r in selected) / n,
            "items_with_output_cap_hit": sum(
                any(response.get("done_reason") == "length" for response in r["model_responses"])
                for r in selected
            ),
            "no_successful_sql": sum(
                not any(attempt["status"] == "ok" for attempt in r["attempts"]) for r in selected
            ),
            "p50_ms": percentile([r["latency_ms"] for r in selected], 50),
            "p95_ms": percentile([r["latency_ms"] for r in selected], 95),
            "avg_tokens": sum(r["tokens"] for r in selected) / n
            if all(r["tokens"] is not None for r in selected)
            else None,
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(
        f"# Live local evaluation\n\nLabel: **{config['label']}**\n\n"
        "Same local model and snapshot; baseline one generation versus LangGraph tool calling with at most two SQL attempts. "
        "This compares complete strategies, not an isolated repair or RAG effect. "
        "Repeated runs are not additional independent questions. No paid API cost; electricity/hardware cost not measured.\n\n"
        + "```json\n"
        + json.dumps(summary, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    print(f"Report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
