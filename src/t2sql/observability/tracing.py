"""Self-built trace store: every tool call lands in the `agent_traces` Postgres table.

Why not Langfuse self-host: its topology assumes Docker Compose (Postgres + ClickHouse + Redis +
MinIO), and this project has a hard no-Docker constraint. Reproducing that stack by hand under
systemd is disproportionate effort for the value. Langfuse **Cloud** (SaaS, zero install) is
supported as an optional richer view when keys are present — the Postgres row is always the
source of truth, and a Langfuse outage can never affect a request.

Tracing must never break the request it is tracing. Every failure path here is swallowed and
recorded in the in-memory buffer instead, which is what the offline demo and the tests read.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from t2sql.config import get_settings

logger = logging.getLogger(__name__)

current_trace_id: ContextVar[str] = ContextVar("current_trace_id", default="")
"""Set once per agent run so tool wrappers can correlate calls without threading an id through
every signature. A ContextVar (not a global) keeps concurrent API requests from cross-writing."""

_INSERT = """
INSERT INTO agent_traces (trace_id, step, tool_name, arguments, result, latency_ms, token_count)
VALUES (:trace_id, :step, :tool_name, :arguments, :result, :latency_ms, :token_count)
"""

# In-memory mirror of what was written. Always populated, database or not — this is what
# `make demo-offline`, the API response and the tests read, so the trace is inspectable with
# zero infrastructure.
_BUFFER: dict[str, list[dict[str, Any]]] = defaultdict(list)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def _jsonable(value: Any) -> Any:
    """Best-effort JSON coercion — a non-serialisable result must not lose the whole trace row."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return {"repr": repr(value)[:4000]}


def log_tool_call(
    trace_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    result: Any = None,
    latency_ms: int | None = None,
    token_count: int | None = None,
) -> dict[str, Any]:
    """Record one tool call. Returns the buffered row. Never raises."""
    step = len(_BUFFER[trace_id])
    row = {
        "trace_id": trace_id,
        "step": step,
        "tool_name": tool_name,
        "arguments": _jsonable(arguments or {}),
        "result": _jsonable(result if result is not None else {}),
        "latency_ms": latency_ms,
        "token_count": token_count,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _BUFFER[trace_id].append(row)

    _write_postgres(row)
    _forward_langfuse(row)
    return row


def _write_postgres(row: dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.database_url:
        return  # offline / no database configured — the buffer is the whole story
    try:
        from sqlalchemy import text

        engine = _engine(settings.database_url)
        payload = dict(row)
        payload.pop("created_at", None)
        payload["arguments"] = json.dumps(payload["arguments"], ensure_ascii=False)
        payload["result"] = json.dumps(payload["result"], ensure_ascii=False)
        with engine.begin() as conn:
            conn.execute(text(_INSERT), payload)
    except Exception as err:  # noqa: BLE001 - tracing must never break the request
        logger.warning("trace write failed (%s): %s", type(err).__name__, err)


_ENGINES: dict[str, Any] = {}


def _engine(url: str) -> Any:
    """Cache one engine per URL — a new pool per tool call would exhaust connections."""
    if url not in _ENGINES:
        from sqlalchemy import create_engine

        _ENGINES[url] = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)
    return _ENGINES[url]


def _forward_langfuse(row: dict[str, Any]) -> None:
    """Optional enrichment. Wrapped so a Langfuse outage is invisible to the app."""
    settings = get_settings()
    if not settings.langfuse_enabled:
        return
    try:  # pragma: no cover - requires the optional `langfuse` package and network
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        client.trace(id=row["trace_id"]).span(
            name=row["tool_name"],
            input=row["arguments"],
            output=row["result"],
            metadata={"step": row["step"], "latency_ms": row["latency_ms"]},
        )
    except Exception as err:  # noqa: BLE001
        logger.debug("langfuse forward skipped: %s", err)


def get_trace(trace_id: str) -> list[dict[str, Any]]:
    """Buffered rows for one trace, in call order."""
    return list(_BUFFER.get(trace_id, []))


def clear_trace(trace_id: str | None = None) -> None:
    """Drop one trace (or all). Used by tests and by long-running processes to bound memory."""
    if trace_id is None:
        _BUFFER.clear()
    else:
        _BUFFER.pop(trace_id, None)


def read_recent_traces(limit: int = 20) -> list[dict[str, Any]]:
    """Read past traces from Postgres for the Streamlit 'Traces' tab.

    Falls back to the in-memory buffer when no database is configured, so the tab is never empty
    in an offline demo.
    """
    settings = get_settings()
    if not settings.database_url:
        rows = [row for trace in _BUFFER.values() for row in trace]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)[:limit]
    try:
        from sqlalchemy import text

        with _engine(settings.database_url).connect() as conn:
            result = conn.execute(
                text(
                    "SELECT trace_id, step, tool_name, arguments, result, latency_ms, created_at "
                    "FROM agent_traces ORDER BY created_at DESC, step ASC LIMIT :limit"
                ),
                {"limit": limit},
            )
            return [dict(r._mapping) for r in result]
    except Exception as err:  # noqa: BLE001
        logger.warning("trace read failed: %s", err)
        return []
