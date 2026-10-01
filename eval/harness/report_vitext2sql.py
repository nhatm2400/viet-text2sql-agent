"""Export aggregate evidence only; never redistribute external questions, SQL or outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.datasets.external.download_vitext2sql import sha256
from eval.harness.live_vitext2sql import load_package, read_records, summarize_records
from eval.harness.scoring import score_item
from eval.harness.sqlite_readonly import connect_readonly, execute_select


def report(run: Path, *, prefix_size: int | None = None) -> dict:
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    summary_name = "summary.json" if prefix_size is None else "progress.json"
    summary = json.loads((run / summary_name).read_text(encoding="utf-8"))
    if prefix_size is None and not summary.get("complete"):
        raise ValueError("Only completed runs can be exported as evaluation results")
    package = Path(config["package"])
    manifest, items = load_package(package)
    if sha256(package / "manifest.json") != config["manifest_sha256"]:
        raise ValueError("Manifest changed since inference")
    by_id = {item["id"]: item for item in items}
    selected = config["evaluated_ids"]
    if len(set(selected)) != len(selected) or not set(selected).issubset(by_id):
        raise ValueError("Invalid evaluated IDs")
    if config["selection"] == "all-eligible-questions" and set(selected) != set(by_id):
        raise ValueError("Full run is missing eligible questions")
    if any(config[key] != manifest[key] for key in ("source_count", "eligible_count")):
        raise ValueError("Source or eligible count changed")
    expected = {(ident, variant) for ident in selected for variant in config["variants"]}
    records = read_records(run / "items.jsonl", expected)
    recorded_keys = {(r["id"], r["variant"]) for r in records}
    if prefix_size is None and recorded_keys != expected:
        raise ValueError("Missing predictions in a supposedly complete run")
    run_summary = summarize_records(config, records, complete=recorded_keys == expected)
    if run_summary != summary:
        raise ValueError("Summary disagrees with recorded predictions")
    if prefix_size is not None:
        if prefix_size < 1 or prefix_size > len(selected):
            raise ValueError("Invalid prefix size")
        if config["selection"] != "all-eligible-questions" or selected != [i["id"] for i in items]:
            raise ValueError("Prefix report requires all eligible questions in source order")
        selected = selected[:prefix_size]
        subset_expected = {(ident, variant) for ident in selected for variant in config["variants"]}
        if not subset_expected.issubset(recorded_keys):
            raise ValueError("Missing predictions in the requested prefix")
        records = [r for r in records if (r["id"], r["variant"]) in subset_expected]
    for name, expected_hash in config["source_sha256"].items():
        if sha256(run / "source" / name) != expected_hash:
            raise ValueError(f"Source snapshot changed: {name}")
    # Re-execute final predictions on the pinned databases, independently of saved booleans.
    for record in records:
        item = by_id[record["id"]]
        if record["db_id"] != item["db_id"] or record["question"] != item["question_vi"]:
            raise ValueError("Prediction does not match its package question")
        conn = connect_readonly(package / manifest["databases"][item["db_id"]]["path"])
        try:
            gold = execute_select(conn, item["gold_sql"])
            strict = relaxed = False
            attempts = record["attempts"]
            if (
                attempts
                and attempts[-1]["status"] == "ok"
                and record["status"] in {"ok", "executed"}
            ):
                prediction = execute_select(conn, attempts[-1]["sql"])
                score = score_item(prediction, gold, item["gold_sql"])
                strict, relaxed = score.strict, score.relaxed
            if (record["strict"], record["relaxed"], record["gold_empty"]) != (
                strict,
                relaxed,
                not gold.rows,
            ):
                raise ValueError("Recorded score disagrees with execution replay")
        finally:
            conn.close()
        responses = record["model_responses"]
        usage = [
            r["prompt_eval_count"] + r["eval_count"]
            for r in responses
            if "prompt_eval_count" in r and "eval_count" in r
        ]
        tokens = sum(usage) if usage and len(usage) == len(responses) else None
        if record["model_calls"] != len(responses) or record["tokens"] != tokens:
            raise ValueError("Recorded model usage disagrees with raw responses")
    report_config = dict(config, evaluated_ids=selected)
    if prefix_size is not None:
        report_config["selection"] = "completed-source-order-prefix"
    recomputed = summarize_records(report_config, records, complete=True)
    evaluated = [by_id[ident] for ident in selected]
    return {
        "label": config["label"],
        "scope": {
            "selection": report_config["selection"],
            "requested_subset_complete": True,
            "full_run_complete": summary["complete"],
            "full_run_completed_predictions": run_summary["completed_predictions"],
            "full_run_expected_predictions": run_summary["expected_predictions"],
            "prefix_questions": prefix_size,
        },
        "setting": manifest["setting"],
        "split": manifest["split"],
        "not_official_vitext2sql_or_spider_score": True,
        "review": "Programmatic alignment and execution replay; independent human audit pending",
        "population": {
            "source_questions": manifest["source_count"],
            "ast_aligned_questions": manifest["ast_aligned_count"],
            "eligible_questions": manifest["eligible_count"],
            "excluded_questions": manifest["source_count"] - manifest["eligible_count"],
            "eligible_databases": manifest["database_count"],
            "eligible_empty_gold": manifest["empty_gold_count"],
            "evaluated_questions": len(evaluated),
            "evaluated_databases": len({item["db_id"] for item in evaluated}),
            "distinct_database_ast_pairs": len(
                {(item["db_id"], item["source_sql_ast_sha256"]) for item in evaluated}
            ),
        },
        "model": config["model"],
        "model_digest": config["model_digest"],
        "api_version": config["api_version"],
        "model_options": config["model_options"],
        "runtime": config.get("runtime", "Not captured by the historical pilot runner"),
        "scoring": config["scoring"],
        "execution": config["execution"],
        "summary": recomputed,
        "evidence_sha256": {
            name: sha256(run / name) for name in ("config.json", "items.jsonl", summary_name)
        },
        "manifest_sha256": config["manifest_sha256"],
        "questions_sha256": manifest["questions_sha256"],
        "exclusions_sha256": manifest["exclusions_sha256"],
        "source_sha256": config["source_sha256"],
        "limitations": "Adapted eligible subset, English Spider schemas; one database snapshot per question; repeated SQL structures; no independent human audit; not an official leaderboard score. Pilot or source-order prefix results do not estimate full-test accuracy.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--prefix-size",
        type=int,
        help="Replay a completed source-order prefix; explicitly report the full run as incomplete",
    )
    args = parser.parse_args()
    result = report(args.run, prefix_size=args.prefix_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
