"""Self-built tracing: every tool call goes to the `agent_traces` table in the same Postgres."""

from t2sql.observability.tracing import get_trace, log_tool_call, new_trace_id

__all__ = ["get_trace", "log_tool_call", "new_trace_id"]
