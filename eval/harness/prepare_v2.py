"""Create an immutable review package; freeze only after explicit human annotation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import sqlglot

from db.seed import build_rows
from eval.datasets.review_v2 import candidates
from eval.harness.local_validation import data_diagnostics, snapshot
from t2sql.guardrails.ast_policy import check_sql

ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sqlite_sql(sql: str) -> str:
    return sqlglot.transpile(sql, read="sqlite", write="sqlite")[0]


def freeze(package: Path) -> None:
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    items = json.loads((package / "questions.json").read_text(encoding="utf-8"))
    if (package / "frozen.json").exists():
        raise ValueError("Already frozen; use a new package version for any change")
    if digest(package / "snapshot.sqlite") != manifest["snapshot_sha256"]:
        raise ValueError("Snapshot changed since preparation")
    if len(items) != 50 or len({i["id"] for i in items}) != 50:
        raise ValueError("Expected 50 unique cases")
    if (
        sum(i["split"] == "test" for i in items) != 30
        or sum(i["split"] == "dev" for i in items) != 20
    ):
        raise ValueError("Expected 20 dev and 30 test cases")
    if any(i.get("human_review") != "approved" or not i.get("reviewer", "").strip() for i in items):
        raise ValueError("Every case needs human_review=approved and a real reviewer identifier")
    # Re-execute any edited gold labels before freezing. A human still owns their semantics.
    conn = sqlite3.connect(f"{(package / 'snapshot.sqlite').resolve().as_uri()}?mode=ro", uri=True)
    try:
        for item in items:
            decision = check_sql(item["gold_sql"])
            if not decision.allowed:
                raise ValueError(f"Gold blocked: {item['id']}: {decision.reasons}")
            conn.execute(sqlite_sql(item["gold_sql"])).fetchall()
    finally:
        conn.close()
    frozen = {
        **manifest,
        "questions_sha256": digest(package / "questions.json"),
        "reviewers": sorted({i["reviewer"] for i in items}),
        "state": "human_reviewed_frozen",
    }
    (package / "frozen.json").write_text(
        json.dumps(frozen, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def prepare(package: Path) -> None:
    package.mkdir(parents=True, exist_ok=False)
    rows = build_rows(version="v2")
    conn = snapshot(rows)
    conn.execute("PRAGMA query_only=OFF")
    for table, column in [
        ("orders", "customer_id"),
        ("payments", "order_id"),
        ("order_items", "order_id"),
        ("order_items", "product_id"),
        ("reviews", "product_id"),
        ("products", "supplier_id"),
        ("addresses", "customer_id"),
    ]:
        conn.execute(f"CREATE INDEX idx_{table}_{column} ON {table} ({column})")
    conn.commit()
    conn.execute("PRAGMA query_only=ON")
    target = sqlite3.connect(package / "snapshot.sqlite")
    conn.backup(target)
    target.close()
    items = candidates()
    review = [
        "# Human review required",
        "",
        "AI-authored candidates, NOT a held-out result. Review definitions, SQL and output.",
        "20 development / 30 test candidates. Review semantic overlap and template diversity before freezing.",
        "Edit questions.json: human_review=approved and reviewer=<your identifier> only after review.",
        "Never approve labels merely because execution succeeded. Empty answers need special attention.",
        "",
    ]
    errors = []
    for item in items:
        item["reviewer"] = ""
        decision = check_sql(item["gold_sql"])
        try:
            cursor = conn.execute(sqlite_sql(item["gold_sql"]))
            values = cursor.fetchall()
            item["validation"] = {
                "policy_allowed": decision.allowed,
                "row_count": len(values),
                "columns": [c[0] for c in cursor.description],
                "preview": values[:10],
                "empty": not values,
            }
            if not decision.allowed:
                errors.append({"id": item["id"], "error": decision.reasons})
        except Exception as err:
            errors.append({"id": item["id"], "error": str(err)})
            item["validation"] = {"error": str(err)}
        review += [
            f"## {item['id']} ({item['split']})",
            "",
            item["question_vi"],
            "",
            "```sql",
            item["gold_sql"],
            "```",
            "",
            "```json",
            json.dumps(item["validation"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    diagnostics = data_diagnostics(conn)
    conn.close()
    manifest = {
        "version": "benchmark-v2-candidate-3",
        "snapshot_version": "v2",
        "rng_seed": 20260727,
        "snapshot_sha256": digest(package / "snapshot.sqlite"),
        "diagnostics": diagnostics,
        "counts": {t: len(r) for t, r in rows.items()},
        "validation_errors": errors,
        "state": "pending_human_review",
        "dialect": "SQLite native SQL; PostgreSQL model accuracy not evaluated",
        "source_sha256": {
            p: digest(ROOT / p)
            for p in [
                "db/seed.py",
                "db/schema.sql",
                "eval/datasets/review_v2.py",
                "eval/datasets/local_dev/cases.py",
            ]
        },
    }
    (package / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (package / "questions.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (package / "REVIEW.md").write_text("\n".join(review), encoding="utf-8")
    print(
        json.dumps(
            {"package": str(package), "diagnostics": diagnostics, "errors": errors}, indent=2
        )
    )
    if errors or any(diagnostics.values()):
        raise ValueError("Review package has validation failures; see manifest.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=ROOT / "data/benchmark_v2_ready")
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        freeze(args.package)
    else:
        prepare(args.package)


if __name__ == "__main__":
    main()
