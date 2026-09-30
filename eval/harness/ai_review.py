"""Reproducible AI review: Python reference results and small semantic counterexamples.

Does not approve human labels, freeze packages, change snapshots, or invoke an LLM.
"""

import argparse
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from eval.datasets.local_dev.oracles import expected_values
from eval.datasets.review_oracles import references
from eval.harness.prepare_v2 import digest, sqlite_sql
from t2sql.guardrails.ast_policy import check_sql

ROOT = Path(__file__).resolve().parents[2]


def edge_checks(items):
    sqls = {item["id"]: item["gold_sql"] for item in items}
    cases = [
        (
            "test_08",
            "Unsold product present alongside a repeatedly sold product",
            "CREATE TABLE products(product_id); INSERT INTO products VALUES(1),(2),(3);"
            "CREATE TABLE order_items(product_id); INSERT INTO order_items VALUES(1),(1);",
            [(2,)],
            "NOT EXISTS",
            "EXISTS",
        ),
        (
            "test_13",
            "Active unreviewed included; inactive unreviewed excluded",
            "CREATE TABLE products(product_id,is_active); INSERT INTO products VALUES(1,1),(2,1),(3,0),(4,1);"
            "CREATE TABLE reviews(product_id); INSERT INTO reviews VALUES(1),(1);",
            [(2,)],
            "p.is_active=TRUE",
            "p.is_active=FALSE",
        ),
        (
            "test_23",
            "Equal order amounts use ascending ID; cancelled excluded",
            "CREATE TABLE orders(order_id,status,total_amount); INSERT INTO orders VALUES"
            "(3,'completed',100),(1,'completed',100),(2,'completed',200),(4,'cancelled',999);",
            [(2, 200), (1, 100), (3, 100)],
            "order_id LIMIT",
            "order_id DESC LIMIT",
        ),
        (
            "test_04",
            "AOV counts an order once despite two succeeded payments",
            "CREATE TABLE orders(order_id,channel,total_amount,created_at);"
            "INSERT INTO orders VALUES(1,'web',100,'2026-04-01'),(2,'web',300,'2026-06-30');"
            "CREATE TABLE payments(order_id,status);"
            "INSERT INTO payments VALUES(1,'succeeded'),(1,'succeeded'),(2,'succeeded');",
            [("web", 200.0)],
            "AVG(o.total_amount)",
            "SUM(o.total_amount)",
        ),
        (
            "test_11",
            "Keep active suppliers with zero active products",
            "CREATE TABLE suppliers(supplier_id,is_active); INSERT INTO suppliers VALUES(1,1),(2,1),(3,0);"
            "CREATE TABLE products(product_id,supplier_id,is_active); INSERT INTO products VALUES(10,1,1),(11,2,0),(12,3,1);",
            [(1, 1), (2, 0)],
            "COUNT(p.product_id)",
            "COUNT(*)",
        ),
        (
            "test_18",
            "Exactly five days excluded; one second above included; NULL excluded",
            "CREATE TABLE shipments(status,shipped_at,delivered_at);"
            "INSERT INTO shipments VALUES('delivered','2026-01-01 12:00:00','2026-01-06 12:00:00'),"
            "('delivered','2026-01-01 12:00:00','2026-01-06 12:00:01'),"
            "('delivered','2026-01-01 12:00:00','2026-01-06 11:59:59'),"
            "('returned','2026-01-01','2026-01-09'),('delivered',NULL,'2026-01-09');",
            [(1,)],
            "> 5",
            ">= 5",
        ),
        (
            "test_27",
            "Both channels required; repeated web and cancelled app do not qualify",
            "CREATE TABLE orders(customer_id,status,channel); INSERT INTO orders VALUES"
            "(1,'completed','web'),(1,'completed','web'),(2,'completed','web'),(2,'completed','app'),"
            "(3,'completed','web'),(3,'cancelled','app');",
            [(1,)],
            "COUNT(DISTINCT channel)",
            "COUNT(channel)",
        ),
        (
            "test_22",
            "Ratio of sums, not mean of per-order percentages",
            "CREATE TABLE orders(status,total_amount,discount);"
            "INSERT INTO orders VALUES('completed',90,10),('completed',500,500),('cancelled',0,900);",
            [(46.36,)],
            "SUM(total_amount+discount)",
            "SUM(total_amount)",
        ),
        (
            "test_20",
            "Two city addresses for same customer count once",
            "CREATE TABLE addresses(customer_id,city); INSERT INTO addresses VALUES"
            "(1,'TP.HCM'),(1,'TP.HCM'),(2,'Hà Nội'),(3,'TP.HCM');",
            [(2,)],
            "COUNT(DISTINCT customer_id)",
            "COUNT(customer_id)",
        ),
        (
            "test_28",
            "Zero quantity still counts as a warehouse; duplicate warehouse does not",
            "CREATE TABLE inventory(product_id,warehouse,quantity); INSERT INTO inventory VALUES"
            "(1,'a',0),(1,'b',0),(1,'c',0),(2,'a',1),(2,'a',1),(2,'b',1);",
            [(1,)],
            "COUNT(DISTINCT warehouse)",
            "COUNT(warehouse)",
        ),
        (
            "test_10",
            "Only products with inventory rows; sum across every warehouse",
            "CREATE TABLE inventory(product_id,quantity); INSERT INTO inventory VALUES(1,0),(1,0),(2,0),(2,5);"
            "CREATE TABLE products(product_id); INSERT INTO products VALUES(1),(2),(3);",
            [(1,)],
            "SUM(quantity)=0",
            "MIN(quantity)=0",
        ),
        (
            "test_30",
            "Payment quarter and order date are different filters",
            "CREATE TABLE orders(order_id,created_at); INSERT INTO orders VALUES(1,'2026-03-31 23:59:59'),(2,'2026-04-01');"
            "CREATE TABLE payments(order_id,status,paid_at); INSERT INTO payments VALUES"
            "(1,'succeeded','2026-04-01'),(1,'succeeded','2026-07-01'),"
            "(2,'succeeded','2026-04-01'),(1,'failed','2026-04-01');",
            [(1,)],
            "o.created_at <",
            "o.created_at <=",
        ),
    ]
    records = []
    for ident, name, setup, expected, old, new in cases:
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(setup)
            conn.execute("PRAGMA query_only=ON")
            actual = conn.execute(sqlite_sql(sqls[ident])).fetchall()
            assert old in sqls[ident], (ident, old)
            mutant = conn.execute(sqlite_sql(sqls[ident].replace(old, new))).fetchall()
            records.append(
                {
                    "id": ident,
                    "check": name,
                    "expected": expected,
                    "actual": actual,
                    "pass": actual == expected,
                    "mutant_rejected": mutant != expected,
                    "mutation": [old, new],
                    "mutant_result": mutant,
                }
            )
        finally:
            conn.close()
    return records


def review(package):
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if digest(package / "snapshot.sqlite") != manifest["snapshot_sha256"]:
        raise ValueError("Snapshot hash mismatch")
    items = json.loads((package / "questions.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(f"{(package / 'snapshot.sqlite').resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        names = [
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        data = {
            name: [
                dict(row) for row in conn.execute('SELECT * FROM "' + name.replace('"', '""') + '"')
            ]
            for name in names
        }
        expected = references(data)
        converted = {
            name: [
                {
                    key: datetime.fromisoformat(value)
                    if key in {"created_at", "paid_at"} and value is not None
                    else value
                    for key, value in row.items()
                }
                for row in rows
            ]
            for name, rows in data.items()
        }
        dev = {region: expected_values(converted, region) for region in (1, 2)}
        records = []
        for item in items:
            reference = (
                expected[item["id"]]
                if item["split"] == "test"
                else [(dev[item["region_id"]][item["family"]],)]
            )
            actual = [tuple(row) for row in conn.execute(sqlite_sql(item["gold_sql"]))]
            decision = check_sql(item["gold_sql"])
            rewritten = (
                [tuple(row) for row in conn.execute(sqlite_sql(decision.rewritten_sql))]
                if decision.allowed
                else None
            )
            records.append(
                {
                    "id": item["id"],
                    "family": item["family"],
                    "split": item["split"],
                    "python_match": actual == reference,
                    "gold": actual,
                    "reference": reference,
                    "policy_allowed": decision.allowed,
                    "policy_preserves_result": rewritten == actual,
                    "empty_result": not actual,
                    "scalar_zero_or_null": actual in [[(0,)], [(None,)]],
                    "question": item["question_vi"],
                    "gold_sql": item["gold_sql"],
                }
            )
    finally:
        conn.close()
    edges = edge_checks(items)
    return {
        "label": "AI-reviewed; human review remains pending; not model accuracy",
        "package": str(package),
        "snapshot_sha256": manifest["snapshot_sha256"],
        "questions_sha256": digest(package / "questions.json"),
        "source_sha256": {
            name: digest(ROOT / name)
            for name in [
                "eval/harness/ai_review.py",
                "eval/datasets/review_oracles.py",
                "eval/datasets/local_dev/oracles.py",
            ]
        },
        "summary": {
            "cases": len(records),
            "python_matches": sum(r["python_match"] for r in records),
            "policy_preserves_result": sum(r["policy_preserves_result"] for r in records),
            "edge_checks": len(edges),
            "edge_passes": sum(r["pass"] for r in edges),
            "mutants_rejected": sum(r["mutant_rejected"] for r in edges),
        },
        "items": records,
        "edge_checks": edges,
    }


def write_revision(package, destination, report):
    """Version only the ambiguous wording; never fabricate a human annotation."""
    if not all(r["python_match"] and r["policy_preserves_result"] for r in report["items"]):
        raise ValueError("Resolve review failures before creating a revision")
    if not all(r["pass"] and r["mutant_rejected"] for r in report["edge_checks"]):
        raise ValueError("Resolve edge-check failures before creating a revision")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(package / "snapshot.sqlite", destination / "snapshot.sqlite")
    items = json.loads((package / "questions.json").read_text(encoding="utf-8"))
    for item in items:
        if item["id"] == "test_10":
            item["question_vi"] = (
                "Trong các sản phẩm có ít nhất một bản ghi inventory, liệt kê mã sản phẩm "
                "có tổng quantity ở mọi kho bằng 0, sắp theo mã. "
                "Không tính sản phẩm chưa có bản ghi inventory."
            )
        item["ai_review"] = {
            "reviewer": "Codex (AI)",
            "status": "checked_with_python_reference",
            "human_review": False,
            "note": "Shared AI authorship; no independent human verification.",
        }
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(
        version="benchmark-v2-ai-reviewed-1",
        state="ai_reviewed_pending_human_review",
        parent_questions_sha256=digest(package / "questions.json"),
        revision_source_sha256=digest(Path(__file__)),
        changes=["test_10: explicitly exclude products without inventory records; SQL unchanged"],
    )
    (destination / "questions.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sections = [
        "# AI-reviewed package; human review remains pending",
        "",
        "Same snapshot and gold SQL. test_10 wording clarified. No model test run or human approval.",
        "",
    ]
    for item in items:
        sections += [
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
    (destination / "REVIEW.md").write_text("\n".join(sections), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=ROOT / "data/benchmark_v2_ready")
    parser.add_argument("--revision", type=Path, help="Optional new package; refuses overwrite")
    args = parser.parse_args()
    report = review(args.package)
    target = ROOT / "eval/results" / f"{datetime.now(UTC):%Y%m%d-%H%M%S-%f}-ai-review"
    target.mkdir(parents=True, exist_ok=False)
    (target / "review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"report": str(target), **report["summary"]}, indent=2))
    if any(
        not r["python_match"] or not r["policy_preserves_result"] for r in report["items"]
    ) or any(not r["pass"] or not r["mutant_rejected"] for r in report["edge_checks"]):
        raise SystemExit(1)
    if args.revision:
        write_revision(args.package, args.revision, report)
        print(f"AI-reviewed revision: {args.revision}")


if __name__ == "__main__":
    main()
