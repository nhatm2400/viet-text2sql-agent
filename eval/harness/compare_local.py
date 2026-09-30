"""Export a paired development comparison; reject incompatible or incomplete runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from eval.harness.metrics import percentile
from eval.harness.prepare_v2 import digest
from t2sql.agent.prompts import CALENDAR_WINDOW_RULES


def load_run(path: Path):
    config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    records = [
        json.loads(line) for line in (path / "items.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if not (path / "summary.json").exists():
        raise ValueError(f"Run not complete: {path}")
    if config["split"] != "dev" or config["repeats"] != 1:
        raise ValueError("Comparison expects one repeat on development questions")
    by_key = {(r["id"], r["variant"]): r for r in records}
    if len(by_key) != len(records) or {r["variant"] for r in records} != {"baseline", "agent"}:
        raise ValueError("Duplicate records or missing strategy")
    ids = {r["id"] for r in records}
    if len(ids) != 20 or len(records) != 40:
        raise ValueError("Full comparison requires 20 questions and 40 predictions")
    if set(by_key) != {(ident, variant) for ident in ids for variant in ("baseline", "agent")}:
        raise ValueError("Missing paired predictions")
    return config, by_key


def failure_kind(record):
    if record["strict"]:
        return "correct"
    executed = any(a["status"] == "ok" for a in record["attempts"])
    capped = any(r.get("done_reason") == "length" for r in record["model_responses"])
    if capped and not executed:
        return "output_cap_without_successful_sql"
    if executed:
        return "executed_but_incorrect_or_unfinished"
    return record["status"]


def metrics(records):
    n = len(records)
    return {
        "n": n,
        "strict_correct": sum(r["strict"] for r in records),
        "relaxed_correct": sum(r["relaxed"] for r in records),
        "strict_ex": 100 * sum(r["strict"] for r in records) / n,
        "relaxed_ex": 100 * sum(r["relaxed"] for r in records) / n,
        "items_with_output_cap_hit": sum(
            any(m.get("done_reason") == "length" for m in r["model_responses"]) for r in records
        ),
        "no_successful_sql": sum(
            not any(a["status"] == "ok" for a in r["attempts"]) for r in records
        ),
        "p50_ms": percentile([r["latency_ms"] for r in records], 50),
        "p95_ms": percentile([r["latency_ms"] for r in records], 95),
        "avg_tokens": sum(r["tokens"] for r in records) / n
        if all(r["tokens"] is not None for r in records)
        else None,
    }


def compare(before: Path, after: Path, *, axis: str = "token-budget"):
    if axis not in {"token-budget", "schema-checks", "date-windows"}:
        raise ValueError("Unsupported comparison axis")
    old_config, old = load_run(before)
    new_config, new = load_run(after)
    for key in (
        "model_digest",
        "questions_sha256",
        "baseline_instruction",
        "agent_instruction",
        "api_version",
    ):
        if old_config[key] != new_config[key]:
            raise ValueError(f"Incompatible runs: {key}")
    if axis == "token-budget":
        if old_config["context"] != new_config["context"]:
            raise ValueError("Incompatible runs: context")
    elif axis == "schema-checks":
        old_context, new_context = old_config["context"], new_config["context"]
        added_checks = [line for line in new_context.splitlines() if line.startswith("    CHECK ")]
        restored = "\n".join(
            line for line in new_context.splitlines() if not line.startswith("    CHECK ")
        )
        if (
            not added_checks
            or any(line.startswith("    CHECK ") for line in old_context.splitlines())
            or restored != old_context
        ):
            raise ValueError("Schema comparison must add only CHECK lines to the previous context")
    else:
        if (
            CALENDAR_WINDOW_RULES in old_config["context"]
            or new_config["context"] != old_config["context"] + CALENDAR_WINDOW_RULES
        ):
            raise ValueError("Date comparison must append only the calendar-window rules")
    if (
        old_config["snapshot"]["snapshot_sha256"] != new_config["snapshot"]["snapshot_sha256"]
        or old.keys() != new.keys()
    ):
        raise ValueError("Snapshot or evaluated questions changed")
    if old_config["model_options"].keys() != new_config["model_options"].keys():
        raise ValueError("Model option keys changed")
    for key, value in old_config["model_options"].items():
        if (
            not (axis == "token-budget" and key == "num_predict")
            and value != new_config["model_options"][key]
        ):
            raise ValueError(f"Model option changed beyond {axis}: {key}")
    summaries = {}
    for variant in ("baseline", "agent"):
        old_records = [r for (ident, strategy), r in old.items() if strategy == variant]
        new_records = [r for (ident, strategy), r in new.items() if strategy == variant]
        summaries[variant] = {
            "before": metrics(old_records),
            "after": metrics(new_records),
            "strict_delta_pp": 100
            * (sum(r["strict"] for r in new_records) - sum(r["strict"] for r in old_records))
            / len(old_records),
            "recovered_ids": [
                ident
                for ident, strategy in old
                if strategy == variant
                and not old[(ident, strategy)]["strict"]
                and new[(ident, strategy)]["strict"]
            ],
            "regressed_ids": [
                ident
                for ident, strategy in old
                if strategy == variant
                and old[(ident, strategy)]["strict"]
                and not new[(ident, strategy)]["strict"]
            ],
        }
    paired = [
        {
            "id": key[0],
            "variant": key[1],
            "before_strict": old[key]["strict"],
            "after_strict": new[key]["strict"],
            "before_kind": failure_kind(old[key]),
            "after_kind": failure_kind(new[key]),
            "after_attempts": new[key]["attempts"],
            "after_tokens": new[key]["tokens"],
            "after_latency_ms": new[key]["latency_ms"],
        }
        for key in old
    ]
    return {
        "label": "Paired preliminary development comparison; AI-authored synthetic questions",
        "comparison_axis": axis,
        "context_sha256": {
            "before": hashlib.sha256(old_config["context"].encode()).hexdigest(),
            "after": hashlib.sha256(new_config["context"].encode()).hexdigest(),
        },
        "added_check_lines": added_checks if axis == "schema-checks" else [],
        "added_date_rules": CALENDAR_WINDOW_RULES if axis == "date-windows" else "",
        "limitations": "One run per configuration; dev tuning; latency can vary with hardware/runtime state; not human-reviewed test accuracy.",
        "model": new_config["model"],
        "model_digest": new_config["model_digest"],
        "snapshot_sha256": new_config["snapshot"]["snapshot_sha256"],
        "questions_sha256": new_config["questions_sha256"],
        "before_num_predict": old_config["model_options"]["num_predict"],
        "after_num_predict": new_config["model_options"]["num_predict"],
        "raw_evidence": {
            label: {
                "run": str(path),
                "sha256": {
                    name: digest(path / name)
                    for name in ("config.json", "items.jsonl", "summary.json")
                },
            }
            for label, path in (("before", before), ("after", after))
        },
        "after_source_sha256": new_config["source_sha256"],
        "summary": summaries,
        "paired_items": paired,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--axis", choices=["token-budget", "schema-checks", "date-windows"], default="token-budget"
    )
    args = parser.parse_args()
    result = compare(args.before, args.after, axis=args.axis)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
