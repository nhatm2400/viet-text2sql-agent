"""`ask_clarification` — the agent's off-ramp from guessing.

Calling this halts the loop: the graph treats a `needs_clarification` result as a terminal state
and returns the question to the user instead of routing back to the agent node. That is a
first-class outcome, not an error — a deliberately ambiguous slice of `core_vi` exists so the
clarification rate is measurable from day one (proposal §6.2).
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from t2sql.tools import ToolResult


class NeedsClarification(BaseModel):
    """Terminal state: the agent stopped and asked rather than guessing."""

    question: str = Field(min_length=1)
    reason: str = ""
    options: list[str] = Field(default_factory=list)


def clarify(question: str, reason: str = "", options: list[str] | None = None) -> ToolResult:
    payload = NeedsClarification(question=question, reason=reason, options=options or [])
    return ToolResult(
        status="needs_clarification",
        message=payload.question,
        data=payload.model_dump(),
    )


@tool
def ask_clarification(question: str, reason: str = "", options: list[str] | None = None) -> dict:
    """Stop and ask the user a clarifying question instead of guessing.

    Use this when the question is genuinely ambiguous in a way that changes the SQL — an
    undefined metric ("khách hàng active"), an unpinned time window, or a term the glossary lists
    as unverified. Do NOT use it to avoid work: if the schema and glossary answer the question,
    answer it.

    This ends the turn. Ask one question, and offer the concrete options when you know them.

    Args:
        question: what you need to know, in the user's language.
        reason: one line on why the answer changes the query.
        options: the concrete alternatives, when there are a few.
    """
    return clarify(question, reason, options).to_dict()
