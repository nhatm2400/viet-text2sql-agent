"""Writes `eval/results/<run_id>/summary.md` and the machine-readable `items.jsonl`.

The report is deliberately unflattering by construction: it prints the run's provenance (config,
dataset version, snapshot, offline flag) above the numbers, prints strict and relaxed accuracy
side by side, and prints every failed item with its reason. A number without its denominator and
its scoring rule is not publishable — proposal §12.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.harness.metrics import RunMetrics


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value}{suffix}"


def write_report(
    results_dir: Path,
    run_id: str,
    config: dict[str, Any],
    items: list[dict[str, Any]],
    metrics: RunMetrics,
    security: dict[str, Any] | None = None,
) -> Path:
    """Write summary.md + items.jsonl + config.json. Returns the path to summary.md."""
    out = results_dir / run_id
    out.mkdir(parents=True, exist_ok=True)

    (out / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with (out / "items.jsonl").open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

    lines: list[str] = [
        f"# Run `{run_id}`",
        "",
        f"- generated: {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC",
        f"- config: `{config.get('_config_path', 'n/a')}`",
        f"- run name: {config.get('name', 'n/a')}",
        f"- dataset: `{config.get('dataset', 'n/a')}` ({metrics.n_items} items)",
        f"- model: {config.get('model_role', 'n/a')} / provider `{config.get('model_provider', 'n/a')}`",
        f"- offline fixtures: **{config.get('offline', False)}**",
        f"- db snapshot: {config.get('snapshot', 'n/a')}",
        f"- max_iterations: {config.get('max_iterations', 'n/a')}",
        "",
    ]

    if config.get("offline"):
        lines += [
            "> **Offline run.** Model turns and SQL result sets are replayed from "
            "`tests/fixtures/`. These numbers verify that the harness works end to end; they are "
            "NOT a measurement of model accuracy and must never be reported as one.",
            "",
        ]

    lines += [
        "## Primary metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Strict execution accuracy | {_fmt(metrics.strict_ex, '%')} |",
        f"| Relaxed execution accuracy | {_fmt(metrics.relaxed_ex, '%')} |",
        f"| Items scored | {metrics.n_items} |",
        "",
        "Scoring rule: README → *How we score*. Row order is compared only when the gold SQL has "
        "a top-level ORDER BY; relaxed tolerates extra predicted columns.",
        "",
        "## Diagnostic metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Valid-SQL rate | {_fmt(metrics.valid_sql_rate, '%')} |",
        f"| Blocked by policy | {_fmt(metrics.blocked_rate, '%')} |",
        f"| Execution errors | {_fmt(metrics.execution_error_rate, '%')} |",
        f"| Clarification rate | {_fmt(metrics.clarification_rate, '%')} |",
        f"| Exhausted (hit iteration cap) | {_fmt(metrics.exhausted_rate, '%')} |",
        f"| First-pass success | {_fmt(metrics.first_pass_success_rate, '%')} |",
        f"| Self-correction success | {_fmt(metrics.self_correction_success_rate, '%')} |",
        f"| Chart-spec validity | {_fmt(metrics.chart_spec_validity, '%')} |",
        f"| **Average tool calls / question** | **{_fmt(metrics.avg_tool_calls)}** |",
        f"| p50 latency | {_fmt(metrics.p50_latency_ms, ' ms')} |",
        f"| p95 latency | {_fmt(metrics.p95_latency_ms, ' ms')} |",
        f"| Average tokens / question | {_fmt(metrics.avg_tokens)} |",
        "",
    ]

    if metrics.notes:
        lines += ["> " + note for note in metrics.notes] + [""]

    if security:
        lines += [
            "## Security suite",
            "",
            f"- cases: {security['n_cases']}",
            f"- pass rate: {_fmt(security['pass_rate'], '%')}",
            f"- failures: {', '.join(security['failures']) or 'none'}",
            "",
        ]

    lines += [
        "## Per-item results",
        "",
        "| id | strict | relaxed | status | tools | reason |",
        "|---|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(
            f"| {item.get('id')} | {'✅' if item.get('strict') else '❌'} "
            f"| {'✅' if item.get('relaxed') else '❌'} | {item.get('status')} "
            f"| {item.get('n_tool_calls', 0)} | {str(item.get('reason', ''))[:80]} |"
        )

    failures = [i for i in items if not i.get("strict")]
    if failures:
        lines += ["", "## Failure detail", ""]
        for item in failures:
            lines += [
                f"### {item.get('id')} — {item.get('question', '')}",
                "",
                f"- status: `{item.get('status')}`  ·  relaxed: {'pass' if item.get('relaxed') else 'fail'}",
                f"- reason: {item.get('reason', '')}",
                f"- predicted SQL: `{(item.get('predicted_sql') or '').strip()[:400]}`",
                f"- gold SQL: `{(item.get('gold_sql') or '').strip()[:400]}`",
                "",
            ]

    lines += [
        "",
        "---",
        "",
        "Reproduce: `make eval CONFIG="
        + str(config.get("_config_path", "eval/configs/baseline.yaml"))
        + "`",
        "",
    ]

    summary = out / "summary.md"
    summary.write_text("\n".join(lines), encoding="utf-8")
    return summary
