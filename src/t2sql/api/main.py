"""FastAPI surface: `POST /ask` and `GET /health`.

Thin by design. The API validates the request shape, runs the agent, and returns the structured
result plus the full tool trace. It adds no policy of its own — there is exactly one place where
SQL is authorised (`guardrails.ast_policy`, called inside `execute_sql`), and an HTTP layer that
started making its own security decisions would be a second, divergent one.

No authentication: this is a public read-only demo over synthetic data, and the read-only role is
the access-control boundary. Auth is an explicit non-goal (proposal §3).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from t2sql.config import get_settings
from t2sql.observability import tracing

logger = logging.getLogger(__name__)

app = FastAPI(
    title="viet-text2sql-agent",
    version="0.1.0",
    description="Vietnamese question -> English schema Text-to-SQL, with database-level guardrails.",
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    max_iterations: int | None = Field(default=None, ge=1, le=20)


class ToolCallView(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


class AskResponse(BaseModel):
    question: str
    status: Literal["executed", "blocked", "needs_clarification", "error", "exhausted"]
    sql: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    answer: str = ""
    chart_spec: dict[str, Any] | None = None
    clarification: dict[str, Any] | None = None
    blocked_reasons: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    trace_id: str
    iterations: int = 0
    latency_ms: int | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus the configuration facts that change how answers are produced."""
    settings = get_settings()
    return {
        "status": "ok",
        "version": app.version,
        "offline_mode": settings.offline_mode,
        "model_provider": settings.model_provider
        if not settings.offline_mode
        else "offline-fixture",
        "database_configured": bool(settings.database_url_ro),
        "max_iterations": settings.max_iterations,
    }


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Answer one question. Always 200: a blocked query is a result, not a server error.

    Returning 4xx for a blocked query would make "the policy worked" indistinguishable from "the
    request was malformed" in every client and in the demo UI.
    """
    from t2sql.agent.build import run_agent

    trace_id = tracing.new_trace_id()
    try:
        result = run_agent(
            request.question, max_iterations=request.max_iterations, trace_id=trace_id
        )
    except Exception as err:  # noqa: BLE001 - never leak a traceback to a public demo
        logger.exception("agent run failed for trace %s", trace_id)
        return AskResponse(
            question=request.question,
            status="error",
            answer=f"The agent could not complete this request ({type(err).__name__}).",
            trace_id=trace_id,
        )

    return AskResponse(
        question=result["question"],
        status=result["status"],
        sql=result["sql"],
        rows=result["rows"],
        columns=result["columns"],
        answer=result["answer"],
        chart_spec=result["chart_spec"],
        clarification=result["clarification"],
        blocked_reasons=result["blocked_reasons"],
        tool_calls=[ToolCallView(**call) for call in result["tool_calls"]],
        trace_id=result["trace_id"],
        iterations=result["iterations"],
        latency_ms=result.get("latency_ms"),
    )


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str) -> dict[str, Any]:
    """Every tool call for one run, in order — what makes the agent inspectable, not a black box."""
    return {"trace_id": trace_id, "steps": tracing.get_trace(trace_id)}
