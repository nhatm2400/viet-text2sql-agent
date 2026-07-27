"""Evaluation runner.

    python -m eval.harness.runner --config eval/configs/baseline.yaml --offline   # make smoke
    python -m eval.harness.runner --demo --offline                                # make demo-offline
    python -m eval.harness.runner --config eval/configs/baseline.yaml             # make eval

The harness is not the last thing built here, it is nearly the first (proposal §9, standing
rule). It runs from week 2 onward, which means it has to work before the agent is any good — so
the offline path replays fixtures and the online path is a straight substitution of the executor,
not a different code path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:  # allow `python eval/harness/runner.py` too
    sys.path.insert(0, str(REPO_ROOT / "src"))

from eval.harness import report as report_mod  # noqa: E402
from eval.harness.metrics import aggregate, security_metrics  # noqa: E402
from eval.harness.scoring import ResultSet, score_item  # noqa: E402

GoldExecutor = Callable[[str], ResultSet]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a .jsonl dataset, skipping the `_comment` schema line used in empty scaffolds."""
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if "_comment" in record:
            continue
        items.append(record)
    return items


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config["_config_path"] = str(path.as_posix())
    return config


# ---------------------------------------------------------------------------
# Gold executors
# ---------------------------------------------------------------------------


def offline_gold_executor() -> GoldExecutor:
    """Replay recorded gold result sets. Raises a clear error for an unrecorded query."""
    from t2sql.tools.execute_tool import _fingerprint, _load_sql_fixtures

    fixtures = _load_sql_fixtures()

    def execute(sql: str) -> ResultSet:
        fixture = fixtures.get(_fingerprint(sql))
        if fixture is None:
            raise KeyError(
                "no recorded result for this gold SQL — regenerate tests/fixtures/offline_sql.json"
            )
        rows = fixture.get("rows", [])
        columns = fixture.get("columns") or (list(rows[0]) if rows else [])
        return ResultSet(columns=columns, rows=[tuple(r.get(c) for c in columns) for r in rows])

    return execute


def live_gold_executor(url: str) -> GoldExecutor:
    """Execute gold SQL on the snapshot. Read-only connection; gold is data, not trusted input."""
    from sqlalchemy import create_engine, text

    engine = create_engine(url)

    def execute(sql: str) -> ResultSet:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            return ResultSet(columns=columns, rows=[tuple(r) for r in result.fetchall()])

    return execute


# ---------------------------------------------------------------------------
# One item
# ---------------------------------------------------------------------------


def run_item(item: dict[str, Any], gold_executor: GoldExecutor, cap: int) -> dict[str, Any]:
    """Run the agent on one dataset item and score it against the gold result set."""
    from t2sql.agent.build import run_agent

    question = item.get("question_vi") or item.get("question_en") or ""
    record: dict[str, Any] = {
        "id": item.get("id"),
        "question": question,
        "gold_sql": item.get("gold_sql", ""),
        "tags": item.get("tags", []),
        "difficulty": item.get("difficulty", ""),
    }

    try:
        run = run_agent(question, max_iterations=cap)
    except Exception as err:  # noqa: BLE001 - one broken item must not abort the run
        record.update(
            status="error",
            strict=False,
            relaxed=False,
            reason=f"agent crashed: {err}",
            n_tool_calls=0,
            sql_valid=False,
            latency_ms=None,
        )
        return record

    executes = [c for c in run["tool_calls"] if c["name"] == "execute_sql"]
    charts = [c for c in run["tool_calls"] if c["name"] == "propose_chart"]
    record.update(
        status=run["status"],
        predicted_sql=run["sql"],
        n_tool_calls=len(run["tool_calls"]),
        tool_names=[c["name"] for c in run["tool_calls"]],
        latency_ms=run.get("latency_ms"),
        trace_id=run.get("trace_id"),
        execute_attempts=len(executes),
        execute_failures=sum(1 for c in executes if c["result"].get("status") != "ok"),
        chart_proposed=bool(charts),
        chart_valid=any(c["result"].get("status") == "ok" for c in charts),
        sql_valid=run["status"] == "executed",
        blocked_reasons=run.get("blocked_reasons", []),
    )

    if run["status"] != "executed":
        record.update(
            strict=False, relaxed=False, reason=f"no successful execution ({run['status']})"
        )
        return record

    try:
        gold = gold_executor(item["gold_sql"])
    except Exception as err:  # noqa: BLE001
        record.update(strict=False, relaxed=False, reason=f"gold SQL could not be executed: {err}")
        return record

    detail = score_item(
        run["rows"], gold, item["gold_sql"], predicted_columns=run["columns"] or None
    )
    record.update(
        strict=detail.strict,
        relaxed=detail.relaxed,
        order_sensitive=detail.order_sensitive,
        reason=detail.reason,
        column_mapping=detail.column_mapping,
    )
    return record


def run_security_suite(path: Path) -> list[dict[str, Any]]:
    """Run the red-team set through the policy. SQL payloads only — natural-language payloads are
    exercised by the agent tests, since there is no SQL to check until the agent writes one."""
    from t2sql.guardrails.ast_policy import check_sql

    results: list[dict[str, Any]] = []
    for case in load_jsonl(path):
        if case.get("input_kind") != "sql":
            results.append({**case, "passed": None, "skipped": "natural-language payload"})
            continue
        decision = check_sql(case["payload"])
        joined = "; ".join(decision.reasons)
        expected = case.get("expected_behavior")
        if expected == "blocked":
            passed = not decision.allowed
        else:  # "rewritten": must be allowed AND actually modified
            passed = decision.allowed and decision.rewritten_sql is not None
        if passed and (needle := case.get("expected_reason_contains")):
            passed = needle.lower() in joined.lower()
        results.append({**case, "passed": passed, "reasons": decision.reasons})
    return [r for r in results if r.get("passed") is not None]


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def run_demo(dataset: Path, cap: int) -> int:
    """Print the ordered tool-call trace and final answer for every seed question."""
    from t2sql.agent.build import run_agent

    items = load_jsonl(dataset)
    retries_seen = 0

    for item in items:
        question = item.get("question_vi") or item.get("question_en", "")
        print("=" * 78)
        print(f"[{item['id']}] {question}")
        print("=" * 78)
        run = run_agent(question, max_iterations=cap)

        for n, call in enumerate(run["tool_calls"], start=1):
            result = call["result"]
            status = result.get("status", "?")
            marker = {"ok": "✅", "blocked": "⛔", "error": "❌", "needs_clarification": "❓"}.get(
                status, "·"
            )
            args = json.dumps(call["arguments"], ensure_ascii=False)
            print(f"  {n}. {marker} {call['name']}({args[:150]})")
            detail = result.get("message", "")
            if status != "ok":
                retries_seen += 1
                print(f"       -> {status}: {detail[:180]}")
                print(
                    "       -> the agent reads error_kind and rewrites the query on the next turn"
                )
            else:
                print(f"       -> {detail[:180]}")

        print(f"\n  status      : {run['status']}  (tool calls: {len(run['tool_calls'])}/{cap})")
        print(f"  SQL         : {(run['sql'] or '(none)')[:200]}")
        print(f"  rows        : {len(run['rows'])}")
        print(
            f"  chart_spec  : {json.dumps(run['chart_spec'], ensure_ascii=False) if run['chart_spec'] else '(none)'}"
        )
        print(f"  answer      : {run['answer'][:400]}\n")

    print("=" * 78)
    if retries_seen:
        print(
            f"✅ {retries_seen} failed tool call(s) recovered inside the loop — the retry path is live."
        )
    else:
        print("⚠️  no failed tool call in this demo; the retry path was NOT exercised.")
    print(
        "Zero API keys, zero database, zero network: every model turn and result set was a fixture."
    )
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="viet-text2sql evaluation harness")
    parser.add_argument("--config", type=Path, help="run config, e.g. eval/configs/baseline.yaml")
    parser.add_argument("--offline", action="store_true", help="force OFFLINE_MODE=1 (fixtures)")
    parser.add_argument(
        "--demo", action="store_true", help="print the agent loop for the seed questions"
    )
    parser.add_argument("--limit", type=int, default=0, help="score only the first N items")
    parser.add_argument("--run-id", default="", help="override the generated run id")
    args = parser.parse_args(argv)

    if args.offline:
        # Set before anything imports settings, so the whole process agrees on the mode.
        os.environ["OFFLINE_MODE"] = "1"

    from t2sql.config import reload_settings

    settings = reload_settings()

    if args.demo:
        return run_demo(
            REPO_ROOT / "eval/datasets/core_vi/questions.jsonl", settings.max_iterations
        )

    if not args.config:
        parser.error("--config is required unless --demo is used")

    config = load_config(args.config)
    cap = int(config.get("max_iterations", settings.max_iterations))

    # An offline run must be asked for explicitly. Without this guard, `make eval` on a machine
    # with the default OFFLINE_MODE=1 would quietly report fixture replay as a measurement — the
    # exact way a results table starts lying. `make smoke` passes --offline and is honest about it.
    if settings.offline_mode and not args.offline:
        print(
            "Refusing to run an evaluation on fixtures without being asked to.\n"
            "  OFFLINE_MODE is on, so every model turn and result set would be replayed from\n"
            "  tests/fixtures/ — those numbers measure the harness, not the model.\n"
            "\n"
            "  To check the harness end to end:  make smoke\n"
            "  To measure for real:              set OFFLINE_MODE=0, MODEL_PROVIDER + an API key,\n"
            "                                    DATABASE_URL and DATABASE_URL_RO, then re-run.",
            file=sys.stderr,
        )
        return 1

    if settings.offline_mode:
        gold_executor = offline_gold_executor()
    elif config.get("gold_database_url") or settings.database_url:
        gold_executor = live_gold_executor(config.get("gold_database_url") or settings.database_url)
    else:
        print(
            "Cannot run an online evaluation: no database is configured.\n"
            "  - set DATABASE_URL (the snapshot the gold SQL is executed against), or\n"
            "  - run the offline harness check instead: make smoke\n"
            "Online runs also need MODEL_PROVIDER + an API key and OFFLINE_MODE=0.",
            file=sys.stderr,
        )
        return 1

    dataset_path = REPO_ROOT / config.get("dataset", "eval/datasets/core_vi/questions.jsonl")
    items = load_jsonl(dataset_path)
    if args.limit:
        items = items[: args.limit]

    print(
        f"Running {len(items)} items from {dataset_path.name} (offline={settings.offline_mode}) ..."
    )
    records = [run_item(item, gold_executor, cap) for item in items]
    for record in records:
        print(
            f"  {record['id']}: strict={record.get('strict')} relaxed={record.get('relaxed')} "
            f"status={record.get('status')} tools={record.get('n_tool_calls')}"
        )

    metrics = aggregate(records)
    security = None
    if config.get("run_security_suite", True):
        security = security_metrics(
            run_security_suite(REPO_ROOT / "eval/datasets/security/attacks.jsonl")
        )

    run_id = args.run_id or f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{config.get('name', 'run')}"
    config.update(
        offline=settings.offline_mode,
        model_provider=settings.model_provider,
        max_iterations=cap,
        dataset=str(dataset_path.relative_to(REPO_ROOT).as_posix()),
    )
    summary = report_mod.write_report(
        settings.results_path, run_id, config, records, metrics, security
    )

    print("")
    print(f"strict EX          : {metrics.strict_ex}%")
    print(f"relaxed EX         : {metrics.relaxed_ex}%")
    print(f"avg tool calls/q   : {metrics.avg_tool_calls}")
    if security:
        print(f"security pass rate : {security['pass_rate']}% over {security['n_cases']} SQL cases")
    print(f"\nwrote {summary.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
