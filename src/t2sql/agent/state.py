"""Graph state.

`iteration_count` is the only field the safety argument depends on: it is incremented by the
agent node on every LLM turn and read by the routing edge, so the loop cannot be extended by
anything the model emits.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

RunStatus = Literal["running", "executed", "blocked", "needs_clarification", "error", "exhausted"]


class AgentState(TypedDict, total=False):
    """State carried through the LangGraph loop."""

    messages: Annotated[list[BaseMessage], add_messages]
    question: str
    trace_id: str
    iteration_count: int
    status: RunStatus
    sql: str | None
    rows: list[dict[str, Any]]
    columns: list[str]
    chart_spec: dict[str, Any] | None
    answer: str
    tool_calls: list[dict[str, Any]]
    clarification: dict[str, Any] | None


def initial_state(question: str, trace_id: str) -> AgentState:
    return AgentState(
        messages=[],
        question=question,
        trace_id=trace_id,
        iteration_count=0,
        status="running",
        sql=None,
        rows=[],
        columns=[],
        chart_spec=None,
        answer="",
        tool_calls=[],
        clarification=None,
    )
