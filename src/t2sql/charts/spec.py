"""Declarative chart specification.

The model never emits code — it emits a `ChartSpec` that Pydantic validates against a fixed
allowlist, and this module turns that spec into a Plotly figure. There is no `eval`, no `exec`,
no `plotly.io.from_json` of model output, and no template string that reaches a renderer. This
is the same argument as the SQL policy, applied to visualisation.

Validation failure returns a `ChartRefusal`, never an exception: a bad chart must degrade to
"here is your table without a chart", not take down the request.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

ChartType = Literal["bar", "line", "pie"]
Aggregation = Literal["none", "sum", "avg", "count", "min", "max"]
SortOrder = Literal["none", "asc", "desc"]

MAX_POINTS = 50


class ChartSpec(BaseModel):
    """What to draw. Field names map to result-set column names, never to expressions."""

    model_config = {"extra": "forbid"}

    chart_type: ChartType
    x: str = Field(min_length=1, description="column name for the category / time axis")
    y: str = Field(min_length=1, description="column name for the value axis")
    aggregation: Aggregation = "none"
    sort: SortOrder = "none"
    limit: int = Field(default=MAX_POINTS, ge=1, le=MAX_POINTS)
    title: str = ""

    @field_validator("x", "y")
    @classmethod
    def _plain_identifier(cls, value: str) -> str:
        """Reject anything that is not a bare column name.

        A column reference is all this field is allowed to be. Blocking punctuation here is what
        stops a spec field from being used as an injection vector into a downstream renderer.
        """
        cleaned = value.strip()
        if not cleaned.replace("_", "").isalnum():
            raise ValueError(f"column reference must be a plain identifier, got {value!r}")
        return cleaned


class ChartRefusal(BaseModel):
    """Structured 'no chart this time' — the agent can read it and move on."""

    status: Literal["refused"] = "refused"
    reasons: list[str] = Field(default_factory=list)


def build_spec(payload: dict[str, Any]) -> ChartSpec | ChartRefusal:
    """Validate an untrusted dict into a ChartSpec. Never raises."""
    try:
        return ChartSpec(**payload)
    except ValidationError as err:
        return ChartRefusal(
            reasons=[f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors()]
        )
    except TypeError as err:
        return ChartRefusal(reasons=[str(err)])


def _aggregate(spec: ChartSpec, rows: list[dict[str, Any]]) -> list[tuple[Any, float]]:
    buckets: dict[Any, list[float]] = {}
    for row in rows:
        key = row.get(spec.x)
        raw = row.get(spec.y)
        try:
            value = float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            value = 0.0
        buckets.setdefault(key, []).append(value)

    def reduce(values: list[float]) -> float:
        match spec.aggregation:
            case "sum":
                return sum(values)
            case "avg":
                return sum(values) / len(values)
            case "count":
                return float(len(values))
            case "min":
                return min(values)
            case "max":
                return max(values)
            case _:
                return values[0]

    points = [(key, reduce(values)) for key, values in buckets.items()]
    if spec.sort != "none":
        points.sort(key=lambda p: p[1], reverse=spec.sort == "desc")
    return points[: spec.limit]


def render(spec: ChartSpec, rows: list[dict[str, Any]]) -> Any:
    """Return a Plotly figure for `spec` over `rows`.

    Raises ValueError only for a spec/data mismatch the validator cannot see (a column the result
    set does not contain) — callers treat that as "show the table, skip the chart".
    """
    import plotly.graph_objects as go

    if not rows:
        raise ValueError("no rows to plot")
    missing = [c for c in (spec.x, spec.y) if c not in rows[0]]
    if missing:
        raise ValueError(f"columns not in result set: {', '.join(missing)}")

    points = _aggregate(spec, rows)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    title = spec.title or f"{spec.y} by {spec.x}"

    match spec.chart_type:
        case "bar":
            figure = go.Figure(go.Bar(x=xs, y=ys))
        case "line":
            figure = go.Figure(go.Scatter(x=xs, y=ys, mode="lines+markers"))
        case "pie":
            figure = go.Figure(go.Pie(labels=xs, values=ys))

    figure.update_layout(title=title, xaxis_title=spec.x, yaxis_title=spec.y, margin=dict(t=48))
    return figure
