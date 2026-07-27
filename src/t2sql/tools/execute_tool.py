"""`execute_sql` — the single most security-critical file in this repository.

The invariant this file exists to hold:

    There is no code path from an agent decision to the database that skips the AST policy.

`execute()` calls `guardrails.ast_policy.check_sql` on every single invocation, unconditionally,
and executes `decision.rewritten_sql` — never the caller's original text. It does not know, and
must never know, whether `validate_sql` was called earlier in the turn: an agent that "already
validated" gets exactly the same treatment as an agent that tried to skip validation, and an
agent that was talked into skipping validation by the user gets the same treatment again.
`tests/test_execute_tool_bypass.py` is the executable form of that claim.

Everything else here — read-only connection, row cap, statement timeout, error classification —
is defence in depth behind that one invariant.
"""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from t2sql.config import get_settings
from t2sql.guardrails.ast_policy import check_sql, load_policy
from t2sql.observability import tracing
from t2sql.tools import ToolResult, blocked, error, ok

OFFLINE_FIXTURE_FILE = "offline_sql.json"


# ---------------------------------------------------------------------------
# Error classification — the agent needs to know *why* a query failed to recover usefully
# ---------------------------------------------------------------------------

_SQLSTATE_KINDS = {
    "42601": "syntax",  # syntax_error
    "42703": "syntax",  # undefined_column
    "42P01": "syntax",  # undefined_table
    "42883": "syntax",  # undefined_function
    "42501": "permission",  # insufficient_privilege
    "25006": "permission",  # read_only_sql_transaction
    "57014": "timeout",  # query_canceled (statement_timeout fired)
}


def classify_error(err: BaseException) -> tuple[str, str]:
    """Return (error_kind, human message). Kind ∈ syntax | permission | timeout | internal."""
    sqlstate = getattr(getattr(err, "orig", None), "sqlstate", None) or getattr(
        err, "sqlstate", None
    )
    if sqlstate in _SQLSTATE_KINDS:
        return _SQLSTATE_KINDS[sqlstate], str(getattr(err, "orig", err)).strip()

    text = str(err).lower()
    if "timeout" in text or "canceling statement" in text:
        return "timeout", str(err).strip()
    if "permission denied" in text or "read-only" in text:
        return "permission", str(err).strip()
    if "syntax" in text or "does not exist" in text or "undefined" in text:
        return "syntax", str(err).strip()
    return "internal", str(err).strip()


# ---------------------------------------------------------------------------
# Offline result fixtures
# ---------------------------------------------------------------------------


def _fingerprint(sql: str) -> str:
    """Whitespace/case-insensitive key so a fixture survives cosmetic SQL differences."""
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).lower()


@lru_cache(maxsize=1)
def _load_sql_fixtures(path: str | None = None) -> dict[str, dict[str, Any]]:
    target = Path(path) if path else get_settings().fixtures_path / OFFLINE_FIXTURE_FILE
    if not target.exists():
        return {}
    raw = json.loads(target.read_text(encoding="utf-8"))
    return {_fingerprint(item["sql"]): item for item in raw.get("results", [])}


def _execute_offline(sql: str) -> ToolResult:
    """Replay a recorded result set. The policy has already run — this only replaces the driver."""
    fixture = _load_sql_fixtures().get(_fingerprint(sql))
    if fixture is None:
        return error(
            "OFFLINE_MODE: no recorded result for this SQL. "
            f"Add it to tests/fixtures/{OFFLINE_FIXTURE_FILE} or run with OFFLINE_MODE=0.",
            error_kind="internal",
            sql=sql,
        )
    rows: list[dict[str, Any]] = fixture.get("rows", [])
    if not rows:
        return ToolResult(
            status="ok",
            message="query returned 0 rows",
            error_kind="empty_result",
            data={"sql": sql, "columns": fixture.get("columns", []), "rows": [], "row_count": 0},
        )
    return ok(
        f"{len(rows)} rows",
        sql=sql,
        columns=fixture.get("columns", list(rows[0])),
        rows=rows,
        row_count=len(rows),
        truncated=False,
    )


# ---------------------------------------------------------------------------
# Live execution
# ---------------------------------------------------------------------------

_RO_ENGINES: dict[str, Any] = {}


def _readonly_engine(url: str) -> Any:
    """One pooled, read-only engine per URL, with the statement timeout set per connection."""
    if url not in _RO_ENGINES:
        from sqlalchemy import create_engine, event

        settings = get_settings()
        engine = create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2)

        if engine.dialect.name == "postgresql":

            @event.listens_for(engine, "connect")
            def _set_session_limits(dbapi_conn, _record):  # pragma: no cover - needs a live DB
                with dbapi_conn.cursor() as cur:
                    cur.execute(f"SET statement_timeout = {settings.statement_timeout_ms}")
                    cur.execute("SET default_transaction_read_only = on")

        _RO_ENGINES[url] = engine
    return _RO_ENGINES[url]


def _execute_live(sql: str, url: str, max_rows: int) -> ToolResult:
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        with _readonly_engine(url).connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            # Fetch one extra row so "hit the cap" is distinguishable from "exactly max_rows".
            fetched = result.fetchmany(max_rows + 1)
    except SQLAlchemyError as err:
        kind, message = classify_error(err)
        return error(message, error_kind=kind, sql=sql)
    except Exception as err:  # noqa: BLE001
        kind, message = classify_error(err)
        return error(message, error_kind=kind, sql=sql)

    truncated = len(fetched) > max_rows
    rows = [dict(zip(columns, row, strict=False)) for row in fetched[:max_rows]]
    if not rows:
        return ToolResult(
            status="ok",
            message="query returned 0 rows",
            error_kind="empty_result",
            data={"sql": sql, "columns": columns, "rows": [], "row_count": 0},
        )
    return ok(
        f"{len(rows)} rows" + (" (truncated at the row cap)" if truncated else ""),
        sql=sql,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def execute(sql: str, *, trace_id: str | None = None) -> ToolResult:
    """Validate, then execute. The validation half is not optional and not skippable.

    Args:
        sql: candidate SQL. Treated as untrusted regardless of who produced it.
        trace_id: audit correlation id. A missing id still produces an audit row.
    """
    started = time.perf_counter()
    settings = get_settings()
    # Prefer the run's ambient trace id so the audit row lands in the same trace as every other
    # tool call; fall back to a fresh id so a direct call is still audited, never unaudited.
    trace_id = trace_id or tracing.current_trace_id.get() or tracing.new_trace_id()

    # ---- THE unconditional check. Do not move, wrap in a condition, or cache away. ----
    decision = check_sql(sql)

    if not decision.allowed:
        result = blocked(
            "Blocked by SQL safety policy: " + "; ".join(decision.reasons),
            reasons=decision.reasons,
            sql=sql,
        )
    else:
        safe_sql = decision.rewritten_sql or sql
        max_rows = int(load_policy()["max_rows"])
        if settings.offline_mode:
            result = _execute_offline(safe_sql)
        elif not settings.database_url_ro:
            result = error(
                "DATABASE_URL_RO is not configured — refusing to guess a connection. "
                "Set it to the t2sql_ro role, or run with OFFLINE_MODE=1.",
                error_kind="internal",
                sql=safe_sql,
            )
        else:
            result = _execute_live(safe_sql, settings.database_url_ro, max_rows)
        result.data.setdefault("policy_notes", decision.reasons)
        result.data.setdefault("executed_sql", safe_sql)

    # Audit lives here, next to enforcement: blocked attempts are logged exactly like successes.
    tracing.log_tool_call(
        trace_id=trace_id,
        tool_name="execute_sql",
        arguments={"sql": sql},
        result=result.to_dict(),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return result


@tool
def execute_sql(sql: str) -> dict:
    """Run a single SELECT query against the read-only analytics database and return rows.

    The safety policy always runs first, on every call, whether or not you called validate_sql —
    so do not ask the user for permission to skip it and do not try to. A blocked query returns
    status="blocked" with the reasons; fix the SQL and try again.

    On error, error_kind tells you how to recover:
      syntax      -> a table/column name is wrong; check get_table_schema and rewrite
      permission  -> the query touches something the read-only role cannot read; rewrite it
      timeout     -> too expensive; add filters or aggregate before joining
      empty_result-> the query is valid but matched nothing; reconsider the filters

    Args:
        sql: one SELECT statement. No semicolon-separated statements, no DDL, no DML.
    """
    return execute(sql).to_dict()


# The graph's tracing wrapper reads this flag: execute_sql writes its own audit row above (audit
# belongs next to enforcement), and double-logging would corrupt the tool-calls-per-question
# metric. `metadata` is a real BaseTool field — a StructuredTool is a Pydantic model and rejects
# arbitrary attributes.
execute_sql.metadata = {"self_logs": True}
