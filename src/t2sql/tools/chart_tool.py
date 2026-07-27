"""`propose_chart` — a thin wrapper over the Pydantic ChartSpec.

The tool returns a validated *specification*, never a rendered artefact and never code. The
renderer runs later, in the UI, over a spec that has already passed validation.
"""

from __future__ import annotations

from langchain_core.tools import tool

from t2sql.charts.spec import ChartRefusal, build_spec
from t2sql.tools import ToolResult, blocked, ok


def propose(payload: dict) -> ToolResult:
    spec = build_spec(payload)
    if isinstance(spec, ChartRefusal):
        return blocked(
            "chart spec rejected: " + "; ".join(spec.reasons),
            error_kind="policy",
            reasons=spec.reasons,
        )
    return ok(f"{spec.chart_type} chart spec accepted", chart_spec=spec.model_dump())


@tool
def propose_chart(
    chart_type: str,
    x: str,
    y: str,
    aggregation: str = "none",
    sort: str = "none",
    limit: int = 50,
    title: str = "",
) -> dict:
    """Propose a chart for the rows returned by execute_sql.

    Only bar, line and pie are available. x and y must be plain column names from the result set
    — not expressions, not SQL. Use this once you have rows worth visualising; skip it for a
    single number or a one-row answer.

    Args:
        chart_type: "bar" | "line" | "pie".
        x: result-set column for the category / time axis.
        y: result-set column for the value axis.
        aggregation: "none" | "sum" | "avg" | "count" | "min" | "max".
        sort: "none" | "asc" | "desc" — sorts by the y value.
        limit: max points to plot, 1-50.
        title: chart title; a sensible default is generated when empty.
    """
    return propose(
        {
            "chart_type": chart_type,
            "x": x,
            "y": y,
            "aggregation": aggregation,
            "sort": sort,
            "limit": limit,
            "title": title,
        }
    ).to_dict()
