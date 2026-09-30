"""Native SQLite SELECT execution for external benchmarks, without business SQL rewrites."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import sqlglot
from sqlglot import exp

from eval.harness.scoring import ResultSet

MAX_RESULT_ROWS = 100_000
DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile", "randomblob", "zeroblob"}


def connect_readonly(database: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False
    )
    conn.execute("PRAGMA query_only=ON")
    tables = {
        r[0].lower()
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }

    def authorize(action, first, second, schema, trigger):
        if action == sqlite3.SQLITE_READ:
            # SQLite's COUNT(*) fast path reports no schema/column name.
            # ATTACH is denied below, so this connection has only the main database.
            allowed = schema in {None, "main"} and (first or "").lower() in tables
        elif action == sqlite3.SQLITE_FUNCTION:
            allowed = (second or "").lower() not in DENIED_FUNCTIONS
        else:
            allowed = action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}
        return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY

    conn.set_authorizer(authorize)
    return conn


def execute_select(conn: sqlite3.Connection, sql: str, *, timeout: float = 5.0) -> ResultSet:
    try:
        statements = [node for node in sqlglot.parse(sql, read="sqlite") if node is not None]
    except sqlglot.errors.ParseError as error:
        raise ValueError(f"Invalid SQLite SELECT syntax: {error}") from error
    if len(statements) != 1 or not isinstance(
        statements[0], (exp.Select, exp.Union, exp.Except, exp.Intersect)
    ):
        raise ValueError("Exactly one SELECT query is required")
    deadline = time.monotonic() + timeout
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        # Execute original SQL. No LIMIT injection, dialect translation, or literal substitution.
        cursor = conn.execute(sql)
        rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
        if len(rows) > MAX_RESULT_ROWS:
            raise ValueError("Result exceeds resource cap; not truncated for scoring")
        return ResultSet(columns=[c[0] for c in cursor.description], rows=rows)
    finally:
        conn.set_progress_handler(None, 0)


def database_context(database: Path) -> str:
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        ddl = [
            row[0]
            for row in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
    return (
        "Answer the Vietnamese question using this SQLite database with English identifiers. "
        "Use exactly the table and column names below. Quote identifiers when necessary. "
        "Return all requested rows; add LIMIT only when requested by the question.\n"
        + "\n".join(ddl)
    )
