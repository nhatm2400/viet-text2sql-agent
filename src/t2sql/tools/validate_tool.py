"""`validate_sql` — a thin, side-effect-free wrapper over the AST policy.

This tool exists so the agent can check a draft query *before* spending an execution on it. It
is a convenience, never a gate: `execute_sql` re-runs the identical policy internally, so
skipping this tool changes latency, not safety.
"""

from __future__ import annotations

from langchain_core.tools import tool

from t2sql.guardrails.ast_policy import check_sql
from t2sql.tools import ToolResult, blocked, ok


def validate(sql: str) -> ToolResult:
    """Plain-Python entry point, used by the API, the eval harness and tests."""
    decision = check_sql(sql)
    if decision.allowed:
        return ok(
            "SQL passes the safety policy",
            rewritten_sql=decision.rewritten_sql,
            notes=decision.reasons,
        )
    return blocked("SQL rejected by the safety policy", reasons=decision.reasons)


@tool
def validate_sql(sql: str) -> dict:
    """Check a SELECT query against the safety policy without running it.

    Returns the policy verdict and, when allowed, the rewritten SQL that would actually run
    (LIMIT is injected or clamped). Use this to fix a query cheaply before executing it.
    Running execute_sql without validating first is safe — the same policy applies there.

    Args:
        sql: a single SELECT statement.
    """
    return validate(sql).to_dict()
