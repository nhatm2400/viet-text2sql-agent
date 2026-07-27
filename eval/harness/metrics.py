"""Aggregation of per-item results into the diagnostic metrics the proposal commits to.

Everything here is a plain function over a list of item dicts. Two rules:

* A metric whose denominator is zero returns None, never 0.0. "0% clarification rate" and "no
  ambiguous items in this run" are different statements, and conflating them is how a results
  table starts lying.
* Percentages are computed once, here, so the report cannot round differently than the runner.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import mean
from typing import Any


def _pct(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(100.0 * numerator / denominator, 2)


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile. No numpy dependency for four numbers."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(p / 100.0 * len(ordered) + 0.5)) - 1))
    return round(ordered[index], 2)


@dataclass
class RunMetrics:
    """Everything reported for one run configuration."""

    n_items: int = 0

    # primary — both always reported, never one without the other
    strict_ex: float | None = None
    relaxed_ex: float | None = None

    # diagnostic
    valid_sql_rate: float | None = None
    execution_error_rate: float | None = None
    blocked_rate: float | None = None
    clarification_rate: float | None = None
    first_pass_success_rate: float | None = None
    self_correction_success_rate: float | None = None
    exhausted_rate: float | None = None
    chart_spec_validity: float | None = None
    avg_tool_calls: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    avg_tokens: float | None = None

    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def aggregate(items: list[dict[str, Any]]) -> RunMetrics:
    """Aggregate per-item run records. Each item is what `runner.run_item` produced."""
    n = len(items)
    metrics = RunMetrics(n_items=n)
    if n == 0:
        metrics.notes.append("no items scored")
        return metrics

    metrics.strict_ex = _pct(sum(1 for i in items if i.get("strict")), n)
    metrics.relaxed_ex = _pct(sum(1 for i in items if i.get("relaxed")), n)

    statuses = [i.get("status") for i in items]
    metrics.valid_sql_rate = _pct(sum(1 for i in items if i.get("sql_valid")), n)
    metrics.execution_error_rate = _pct(sum(1 for s in statuses if s == "error"), n)
    metrics.blocked_rate = _pct(sum(1 for s in statuses if s == "blocked"), n)
    metrics.clarification_rate = _pct(sum(1 for s in statuses if s == "needs_clarification"), n)
    metrics.exhausted_rate = _pct(sum(1 for s in statuses if s == "exhausted"), n)

    # First pass = the first execute_sql call succeeded. Self-correction = it did not, but a
    # later one did. The second denominator is only the items that actually needed recovery.
    needed_recovery = [i for i in items if i.get("execute_failures", 0) > 0]
    metrics.first_pass_success_rate = _pct(
        sum(
            1
            for i in items
            if i.get("execute_attempts", 0) > 0 and i.get("execute_failures", 0) == 0
        ),
        sum(1 for i in items if i.get("execute_attempts", 0) > 0),
    )
    metrics.self_correction_success_rate = _pct(
        sum(1 for i in needed_recovery if i.get("status") == "executed"), len(needed_recovery)
    )

    charted = [i for i in items if i.get("chart_proposed")]
    metrics.chart_spec_validity = _pct(
        sum(1 for i in charted if i.get("chart_valid")), len(charted)
    )

    tool_calls = [i.get("n_tool_calls", 0) for i in items]
    metrics.avg_tool_calls = round(mean(tool_calls), 2) if tool_calls else None

    latencies = [float(i["latency_ms"]) for i in items if i.get("latency_ms") is not None]
    metrics.p50_latency_ms = percentile(latencies, 50)
    metrics.p95_latency_ms = percentile(latencies, 95)

    tokens = [float(i["tokens"]) for i in items if i.get("tokens")]
    metrics.avg_tokens = round(mean(tokens), 1) if tokens else None

    if metrics.self_correction_success_rate is None:
        metrics.notes.append("no item needed self-correction — rate is undefined, not 0%")
    if metrics.chart_spec_validity is None:
        metrics.notes.append("no chart was proposed — validity is undefined, not 0%")
    return metrics


def security_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Block rate for the red-team set, split by expected behaviour.

    A case whose expected behaviour is `rewritten` counts as a pass when it is allowed AND
    rewritten — counting it as a block would inflate the headline number with a case that is
    supposed to succeed.
    """
    n = len(items)
    passed = sum(1 for i in items if i.get("passed"))
    by_category: dict[str, dict[str, int]] = {}
    for item in items:
        bucket = by_category.setdefault(item.get("category", "unknown"), {"n": 0, "passed": 0})
        bucket["n"] += 1
        bucket["passed"] += 1 if item.get("passed") else 0
    return {
        "n_cases": n,
        "pass_rate": _pct(passed, n),
        "failures": [i["id"] for i in items if not i.get("passed")],
        "by_category": by_category,
    }
