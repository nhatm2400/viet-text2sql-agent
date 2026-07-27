"""The LangGraph ReAct loop.

    START -> agent -> (tool calls?) -> tools -> agent -> ... -> END

Two stop conditions, and the first one is the important one:

1. **The iteration cap.** `route_after_agent` ends the graph as soon as `iteration_count`
   reaches `max_iterations`, no matter what the model asked for. It is a plain integer compared
   in Python — nothing the model emits can raise it, reset it, or route around it. The run ends
   with `status="exhausted"` and a structured "could not complete safely" answer, never an
   exception and never an infinite loop.
2. **Clarification.** A tool result with `status="needs_clarification"` is terminal: the graph
   returns the question to the user instead of routing back to the agent.

Everything else the agent does — which tool, how many retries, when to give up early — is its own
decision. That is the strategy/policy split: this file bounds the loop, `execute_sql` bounds what
the loop can do to the database.
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from t2sql.agent.prompts import EXHAUSTED_MESSAGE, system_prompt
from t2sql.agent.state import AgentState, initial_state
from t2sql.config import get_settings
from t2sql.llm.provider import get_model
from t2sql.observability import tracing
from t2sql.tools.chart_tool import propose_chart
from t2sql.tools.clarify_tool import ask_clarification
from t2sql.tools.execute_tool import execute_sql
from t2sql.tools.glossary_tools import lookup_glossary
from t2sql.tools.retrieval_tools import search_examples
from t2sql.tools.schema_tools import get_table_schema, list_schema
from t2sql.tools.validate_tool import validate_sql

TOOLS: list[BaseTool] = [
    list_schema,
    get_table_schema,
    lookup_glossary,
    search_examples,
    validate_sql,
    execute_sql,
    propose_chart,
    ask_clarification,
]


# ---------------------------------------------------------------------------
# Tracing wrapper
# ---------------------------------------------------------------------------


def _traced(base: BaseTool) -> BaseTool:
    """Wrap a tool so every call is written to the trace store.

    `execute_sql` opts out via `self_logs`: it writes its own audit row next to the policy check,
    and logging it twice would double-count the tool-calls-per-question metric.
    """
    if (base.metadata or {}).get("self_logs"):
        return base

    inner = base.func

    def wrapper(**kwargs: Any) -> Any:
        started = time.perf_counter()
        result = inner(**kwargs)
        tracing.log_tool_call(
            trace_id=tracing.current_trace_id.get() or "untraced",
            tool_name=base.name,
            arguments=kwargs,
            result=result,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return result

    return StructuredTool.from_function(
        func=wrapper,
        name=base.name,
        description=base.description,
        args_schema=base.args_schema,
    )


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def build_agent(
    *,
    max_iterations: int | None = None,
    model_role: str = "fast",
    tools: list[BaseTool] | None = None,
) -> Any:
    """Compile the agent graph. `max_iterations` defaults to the configured cap."""
    settings = get_settings()
    cap = max_iterations if max_iterations is not None else settings.max_iterations
    if cap < 1:
        raise ValueError("max_iterations must be >= 1")

    active_tools = [_traced(t) for t in (tools or TOOLS)]
    model = get_model(model_role).bind_tools(active_tools)
    tool_executor = ToolNode(active_tools)
    prompt = SystemMessage(content=system_prompt(cap))

    def agent_node(state: AgentState) -> dict[str, Any]:
        response = model.invoke([prompt, *state["messages"]])
        return {"messages": [response]}

    def tools_node(state: AgentState) -> dict[str, Any]:
        result = tool_executor.invoke(state)
        return {
            "messages": result["messages"],
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END  # the model produced a final answer
        if state.get("iteration_count", 0) >= cap:
            return END  # HARD CAP — not negotiable by the model
        return "tools"

    def route_after_tools(state: AgentState) -> str:
        for message in reversed(state["messages"]):
            if not isinstance(message, ToolMessage):
                break
            if _payload(message).get("status") == "needs_clarification":
                return END
        return "agent"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    graph.add_conditional_edges("tools", route_after_tools, {"agent": "agent", END: END})
    return graph.compile()


# ---------------------------------------------------------------------------
# Result extraction
# ---------------------------------------------------------------------------


def _payload(message: ToolMessage) -> dict[str, Any]:
    """ToolNode serialises dict returns to a JSON string; parse it back, tolerating failures."""
    content = message.content
    if isinstance(content, dict):
        return content
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {"status": "error", "message": str(content)}
    except (TypeError, ValueError):
        return {"status": "error", "message": str(content)}


def summarise(state: AgentState, cap: int) -> dict[str, Any]:
    """Turn the raw message list into the API/eval-facing result."""
    messages = state["messages"]
    args_by_id: dict[str, dict[str, Any]] = {}
    names_by_id: dict[str, str] = {}
    calls: list[dict[str, Any]] = []

    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                args_by_id[call["id"]] = call.get("args", {})
                names_by_id[call["id"]] = call["name"]
        elif isinstance(message, ToolMessage):
            calls.append(
                {
                    "name": names_by_id.get(message.tool_call_id, message.name or "unknown"),
                    "arguments": args_by_id.get(message.tool_call_id, {}),
                    "result": _payload(message),
                }
            )

    result: dict[str, Any] = {
        "question": state.get("question", ""),
        "trace_id": state.get("trace_id", ""),
        "status": "error",
        "sql": None,
        "rows": [],
        "columns": [],
        "chart_spec": None,
        "answer": "",
        "clarification": None,
        "tool_calls": calls,
        "iterations": state.get("iteration_count", 0),
        "blocked_reasons": [],
    }

    for call in calls:
        payload = call["result"]
        if call["name"] == "execute_sql":
            result["sql"] = payload.get("data", {}).get("executed_sql") or call["arguments"].get(
                "sql"
            )
            if payload.get("status") == "ok":
                data = payload.get("data", {})
                result["rows"] = data.get("rows", [])
                result["columns"] = data.get("columns", [])
                result["status"] = "executed"
            elif payload.get("status") == "blocked":
                result["status"] = "blocked"
                result["blocked_reasons"] = payload.get("data", {}).get("reasons", [])
        elif call["name"] == "propose_chart" and payload.get("status") == "ok":
            result["chart_spec"] = payload.get("data", {}).get("chart_spec")
        elif call["name"] == "ask_clarification":
            result["clarification"] = payload.get("data", {})
            result["status"] = "needs_clarification"

    last = messages[-1] if messages else None
    if isinstance(last, AIMessage) and last.tool_calls and result["iterations"] >= cap:
        result["status"] = "exhausted"
        result["answer"] = EXHAUSTED_MESSAGE.format(max_iterations=cap)
    elif isinstance(last, AIMessage) and not last.tool_calls:
        result["answer"] = str(last.content)
        if result["status"] == "error" and result["answer"]:
            result["status"] = "executed" if result["rows"] else "error"
    elif result["status"] == "needs_clarification":
        result["answer"] = (result["clarification"] or {}).get("question", "")

    return result


def run_agent(
    question: str,
    *,
    max_iterations: int | None = None,
    model_role: str = "fast",
    trace_id: str | None = None,
    graph: Any | None = None,
) -> dict[str, Any]:
    """Run one question end to end and return the structured result plus its trace."""
    settings = get_settings()
    cap = max_iterations if max_iterations is not None else settings.max_iterations
    trace_id = trace_id or tracing.new_trace_id()
    compiled = graph or build_agent(max_iterations=cap, model_role=model_role)

    token = tracing.current_trace_id.set(trace_id)
    started = time.perf_counter()
    try:
        state = initial_state(question, trace_id)
        state["messages"] = [HumanMessage(content=question)]
        # recursion_limit is LangGraph's own runaway guard; our cap is stricter and hits first.
        final = compiled.invoke(state, {"recursion_limit": 2 * cap + 4})
    finally:
        tracing.current_trace_id.reset(token)

    result = summarise(final, cap)
    result["latency_ms"] = int((time.perf_counter() - started) * 1000)
    result["trace"] = tracing.get_trace(trace_id)
    return result
