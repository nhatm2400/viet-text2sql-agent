"""Real SQLite execution and Python-oracle validation, without an LLM or SQL fixtures.

Run from the repo root: python -m eval.harness.local_validation
Fresh in-memory databases only; never modifies data/dev.sqlite or an external database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from db.seed import RNG_SEED, SCHEMA_SQL, TABLES_IN_LOAD_ORDER, _split_statements, build_rows
from eval.datasets.local_dev.cases import build_cases
from eval.datasets.local_dev.oracles import expected_values
from eval.harness.scoring import ResultSet, score_item
from t2sql.guardrails.ast_policy import check_sql

ROOT = Path(__file__).resolve().parents[2]


def snapshot(rows: dict[str, list[dict]]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    for sql in _split_statements(SCHEMA_SQL.read_text(encoding="utf-8"), "sqlite"):
        conn.execute(sql)
    for table in reversed(TABLES_IN_LOAD_ORDER):
        data = rows[table]
        columns = list(data[0])
        values = [
            tuple(v.isoformat(sep=" ") if isinstance(v, datetime) else v for v in r.values())
            for r in data
        ]
        conn.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
    conn.commit()
    conn.execute("PRAGMA query_only = ON")
    return conn


def query(conn: sqlite3.Connection, sql: str) -> ResultSet:
    cursor = conn.execute(sql)
    return ResultSet(columns=[c[0] for c in cursor.description], rows=cursor.fetchall())


def data_diagnostics(conn: sqlite3.Connection) -> dict:
    """Report inherited synthetic-data limitations instead of silently claiming realism."""
    checks = {
        "shipment_address_customer_mismatch": "SELECT COUNT(*) FROM shipments s JOIN orders o ON o.order_id=s.order_id "
        "JOIN addresses a ON a.address_id=s.address_id WHERE a.customer_id<>o.customer_id",
        "delivery_before_shipping": "SELECT COUNT(*) FROM shipments WHERE delivered_at < shipped_at",
        "review_after_snapshot_end": "SELECT COUNT(*) FROM reviews WHERE created_at > '2026-06-30 23:59:00'",
    }
    return {
        "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        **{name: conn.execute(sql).fetchone()[0] for name, sql in checks.items()},
    }


def validate_snapshot(seed: int, cases: list[dict]) -> dict:
    rows = build_rows(seed)
    logical_hash = hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=str).encode()
    ).hexdigest()
    references = {r: expected_values(rows, r) for r in (1, 2, 3)}
    conn = snapshot(rows)
    records = []
    try:
        diagnostics = data_diagnostics(conn)
        for case in cases:
            expected = ResultSet(
                columns=["value"], rows=[(references[case["region_id"]][case["family"]],)]
            )
            record = {
                "id": case["id"],
                "seed": seed,
                "expected": expected.rows,
                "gold_sql": case["gold_sql"],
                "mutant_sql": case["mutant_sql"],
            }
            try:
                gold = query(conn, case["gold_sql"])
                decision = check_sql(case["gold_sql"])
                detail = score_item(gold, expected, case["gold_sql"])
                rewritten = query(conn, decision.rewritten_sql) if decision.allowed else None
                mutant_decision = check_sql(case["mutant_sql"])
                mutant = query(conn, case["mutant_sql"])
                mutant_score = score_item(mutant, expected, case["gold_sql"])
                record.update(
                    gold_result=gold.rows,
                    strict_oracle_match=detail.strict,
                    relaxed_oracle_match=detail.relaxed,
                    policy_allowed=decision.allowed,
                    policy_reasons=decision.reasons,
                    rewritten_oracle_match=bool(
                        rewritten and score_item(rewritten, expected).strict
                    ),
                    mutant_result=mutant.rows,
                    mutant_executes=True,
                    mutant_policy_allowed=mutant_decision.allowed,
                    mutant_detected=not mutant_score.strict and not mutant_score.relaxed,
                )
            except Exception as err:
                record.update(error=f"{type(err).__name__}: {err}")
            records.append(record)
    finally:
        conn.close()
    return {
        "seed": seed,
        "logical_sha256": logical_hash,
        "table_counts": {t: len(data) for t, data in rows.items()},
        "data_diagnostics": diagnostics,
        "records": records,
    }


def write_report(out: Path, snapshots: list[dict], cases: list[dict]) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    records = [record for snap in snapshots for record in snap["records"]]
    fields = [
        "strict_oracle_match",
        "relaxed_oracle_match",
        "policy_allowed",
        "rewritten_oracle_match",
        "mutant_executes",
        "mutant_policy_allowed",
        "mutant_detected",
    ]
    counts = {field: sum(bool(r.get(field)) for r in records) for field in fields}
    source_paths = [
        "db/schema.sql",
        "db/seed.py",
        "eval/datasets/local_dev/cases.py",
        "eval/datasets/local_dev/oracles.py",
        "eval/harness/local_validation.py",
        "eval/harness/scoring.py",
        "src/t2sql/guardrails/ast_policy.py",
        "src/t2sql/guardrails/policy.yaml",
    ]
    summary = {
        "measurement": "gold_sql_validation_not_model_accuracy",
        "llm_calls": 0,
        "sql_fixtures_used": False,
        "split": "development",
        "human_review": "pending",
        "n_cases": len(cases),
        "n_families": len({c["family"] for c in cases}),
        "n_snapshots": len(snapshots),
        "n_executions": len(records),
        "counts": counts,
        "snapshots": [{k: v for k, v in s.items() if k != "records"} for s in snapshots],
        "source_sha256": {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_paths
        },
        "environment": {
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "sqlglot": version("sqlglot"),
            "sqlalchemy": version("sqlalchemy"),
        },
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for filename, data in [("cases.jsonl", cases), ("items.jsonl", records)]:
        (out / filename).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data), encoding="utf-8"
        )
    lines = [
        "# Local gold-SQL validation",
        "",
        "**This is NOT model accuracy, a RAG ablation, or a PostgreSQL security evaluation.**",
        "No LLM calls; no replayed SQL result sets. Questions and references are AI-authored;",
        "independent human review is pending. This is a development suite, not held-out data.",
        "",
        f"{len(cases)} cases from {summary['n_families']} query families × 3 regions; "
        f"{len(snapshots)} seeded SQLite snapshots; {len(records)} case/snapshot pairs.",
        "",
        "| Check | Passed / total |",
        "|---|---|",
    ]
    lines += [f"| {field} | {counts[field]} / {len(records)} |" for field in fields]
    lines += [
        "",
        "Mutation detection requires both strict and relaxed scoring to reject the result.",
        "Mutations intentionally change status, date anchor, aggregation, threshold or DISTINCT.",
        "They are authored fault injections, not observed model errors.",
        "",
        "## Data diagnostics",
        "",
        "These inherited generator problems are reported, not hidden. Current cases avoid",
        "shipment-address joins and shipment/review timing assumptions. Broader business",
        "claims need a repaired generator and a new dataset version.",
        "",
    ]
    for snap in snapshots:
        lines += [
            f"- Seed {snap['seed']}: {sum(snap['table_counts'].values()):,} rows across "
            f"{len(snap['table_counts'])} tables; diagnostics: `{snap['data_diagnostics']}`"
        ]
    lines += [
        "",
        "## Reproduce",
        "",
        "```powershell",
        ".venv/Scripts/python.exe -m eval.harness.local_validation",
        "```",
        "",
        "See summary.json for exact source hashes, logical snapshot hashes and runtime versions.",
        "No existing database file is opened or overwritten. Each run creates a new output folder.",
    ]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    cases = build_cases()
    snapshots = [validate_snapshot(seed, cases) for seed in (RNG_SEED, RNG_SEED + 1)]
    out = args.output or ROOT / "eval/results" / f"{datetime.now(UTC):%Y%m%d-%H%M%S-%f}-local"
    summary = write_report(out, snapshots, cases)
    print(
        json.dumps(
            {
                "output": str(out),
                "counts": summary["counts"],
                "case_snapshot_pairs": summary["n_executions"],
                "llm_calls": 0,
            },
            indent=2,
        )
    )
    return 0 if all(n == summary["n_executions"] for n in summary["counts"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
