"""Classify observed failures on a replay-verified prefix, without inferring semantic causes."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import sqlglot
from sqlglot import exp

from eval.harness.live_vitext2sql import load_package
from eval.harness.report_vitext2sql import report
from eval.harness.scoring import ResultSet, relaxed_ex, strict_ex
from eval.harness.sqlite_readonly import connect_readonly, execute_select


def classify(record: dict, gold: ResultSet, gold_sql: str) -> str:
    """Exclusive observable categories; precedence follows the recorded scoring path."""
    if record["strict"]:
        return "strict_correct"
    attempts = record["attempts"]
    capped = any(r.get("done_reason") == "length" for r in record["model_responses"])
    successful = [a for a in attempts if a["status"] == "ok"]
    if not successful:
        if capped:
            return "no_successful_sql_with_output_cap"
        return "no_successful_sql_without_output_cap"
    if not attempts or attempts[-1]["status"] != "ok" or record["status"] not in {"ok", "executed"}:
        return "non_successful_final_state_after_earlier_success"
    if record["relaxed"]:
        return "projection_difference_relaxed_match"
    last = attempts[-1]
    predicted = ResultSet(columns=last["columns"], rows=[tuple(row) for row in last["rows"]])
    if predicted.arity < gold.arity:
        return "too_few_columns"
    if len(predicted.rows) != len(gold.rows):
        return "row_count_difference"
    if relaxed_ex(predicted, gold):
        return "row_order_only_difference"
    return "value_or_projection_difference"


def feature_signals(predicted_sql: str, gold_sql: str) -> list[str]:
    """Syntactic differences are diagnostic hints, never proof that a clause is wrong."""
    try:
        trees = [sqlglot.parse_one(s, read="sqlite") for s in (predicted_sql, gold_sql)]
    except (sqlglot.errors.ParseError, ValueError):
        return ["parse_difference"]
    features = {
        "tables": exp.Table,
        "joins": exp.Join,
        "aggregates": exp.AggFunc,
        "filters": exp.Where,
        "grouping": exp.Group,
        "having": exp.Having,
        "ordering": exp.Order,
        "limits": exp.Limit,
        "set_operations": exp.SetOperation,
        "literals": exp.Literal,
    }
    return [
        name
        for name, kind in features.items()
        if sorted(n.sql(dialect="sqlite") for n in trees[0].find_all(kind))
        != sorted(n.sql(dialect="sqlite") for n in trees[1].find_all(kind))
    ]


def analyze(run: Path, prefix_size: int) -> tuple[dict, list[dict]]:
    verified = report(run, prefix_size=prefix_size)
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    package = Path(config["package"])
    manifest, items = load_package(package)
    by_id = {i["id"]: i for i in items}
    selected = set(config["evaluated_ids"][:prefix_size])
    records = [
        json.loads(line) for line in (run / "items.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    counts, signals = Counter(), Counter()
    private = []
    capped_misses = 0
    for record in records:
        if record["id"] not in selected:
            continue
        item = by_id[record["id"]]
        conn = connect_readonly(package / manifest["databases"][item["db_id"]]["path"])
        try:
            gold = execute_select(conn, item["gold_sql"])
            if record["attempts"] and record["attempts"][-1]["status"] == "ok":
                replay = execute_select(conn, record["attempts"][-1]["sql"])
                last = record["attempts"][-1]
                # Compare using the same normalization, including duplicates and ordering.
                if not strict_ex(
                    replay,
                    ResultSet(last["columns"], [tuple(r) for r in last["rows"]]),
                    item["gold_sql"],
                ):
                    raise ValueError("Saved prediction rows disagree with replay")
            category = classify(record, gold, item["gold_sql"])
        finally:
            conn.close()
        counts[category] += 1
        if not record["strict"]:
            hints = (
                feature_signals(record["attempts"][-1]["sql"], item["gold_sql"])
                if record["attempts"]
                else []
            )
            signals.update(hints)
            capped = any(r.get("done_reason") == "length" for r in record["model_responses"])
            capped_misses += capped
            private.append(
                {
                    "id": record["id"],
                    "db_id": record["db_id"],
                    "question": item["question_vi"],
                    "gold_sql": item["gold_sql"],
                    "attempts": record["attempts"],
                    "status": record["status"],
                    "category": category,
                    "syntactic_hints_not_semantic_causes": hints,
                    "output_cap": capped,
                }
            )
    n = verified["population"]["evaluated_questions"] * len(config["variants"])
    if sum(counts.values()) != n or len(private) != n - counts["strict_correct"]:
        raise ValueError("Taxonomy coverage mismatch")
    public = {
        "evaluated_predictions": n,
        "strict_failures": len(private),
        "exclusive_observed_categories": dict(sorted(counts.items())),
        "overlapping_syntax_difference_hints_among_strict_failures": dict(sorted(signals.items())),
        "strict_failures_with_any_output_cap": capped_misses,
        "evidence_sha256": verified["evidence_sha256"],
        "review": "Automated result replay and syntactic diagnostics; not independent human semantic review",
        "limitations": "Categories describe observed results, not proven root causes. Syntax differences can be equivalent SQL. Prefix selection is not random; no model calls or score changes.",
    }
    return public, private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--prefix-size", type=int, default=500)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    public, private = analyze(args.run, args.prefix_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(public, stream, ensure_ascii=False, indent=2)
    detail = args.run / "analysis" / f"prefix-{args.prefix_size}-failures.json"
    detail.parent.mkdir(exist_ok=True)
    detail.write_text(json.dumps(private, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(public, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
