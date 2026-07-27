"""Schema introspection tools: `list_schema` and `get_table_schema`.

The schema is parsed once from `db/schema.sql` and cached. It is deliberately NOT hardcoded and
deliberately NOT read from a live database: the AST policy's column allowlist depends on it, so
it must be available with zero database connectivity (offline tests, CI) and it must be
impossible for the two to drift apart — one file, one parse, one source of truth.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import sqlglot
from langchain_core.tools import tool
from sqlglot import exp

from t2sql.config import get_settings
from t2sql.tools import ToolResult, error, ok


@lru_cache(maxsize=2)
def load_schema(path: str | None = None) -> dict[str, dict[str, str]]:
    """Parse `db/schema.sql` into `{table_name: {column_name: sql_type}}` (all lowercase keys)."""
    target = Path(path) if path else get_settings().schema_sql_path
    sql = target.read_text(encoding="utf-8")
    schema: dict[str, dict[str, str]] = {}

    for statement in sqlglot.parse(sql, read="postgres"):
        if not isinstance(statement, exp.Create) or statement.kind != "TABLE":
            continue
        table = statement.this
        if not isinstance(table, exp.Schema):
            continue
        name = table.this.name.lower()
        columns: dict[str, str] = {}
        for column in table.expressions:
            if isinstance(column, exp.ColumnDef):
                columns[column.name.lower()] = column.args["kind"].sql(dialect="postgres")
        schema[name] = columns
    return schema


@lru_cache(maxsize=2)
def load_foreign_keys(path: str | None = None) -> dict[str, list[str]]:
    """`{table: ["orders.customer_id -> customers.customer_id", ...]}` for the prompt block."""
    target = Path(path) if path else get_settings().schema_sql_path
    sql = target.read_text(encoding="utf-8")
    fks: dict[str, list[str]] = {}

    for statement in sqlglot.parse(sql, read="postgres"):
        if not isinstance(statement, exp.Create) or statement.kind != "TABLE":
            continue
        table = statement.this
        if not isinstance(table, exp.Schema):
            continue
        name = table.this.name.lower()
        for column in table.expressions:
            if not isinstance(column, exp.ColumnDef):
                continue
            for constraint in column.args.get("constraints") or []:
                ref = constraint.args.get("kind")
                if isinstance(ref, exp.Reference):
                    target_schema = ref.this
                    ref_table = target_schema.this.name.lower()
                    ref_cols = [e.name.lower() for e in getattr(target_schema, "expressions", [])]
                    ref_col = ref_cols[0] if ref_cols else ""
                    fks.setdefault(name, []).append(
                        f"{name}.{column.name.lower()} -> {ref_table}.{ref_col}"
                    )
    return fks


def schema_block() -> str:
    """Compact, token-cheap rendering of the whole schema for the system prompt."""
    schema = load_schema()
    fks = load_foreign_keys()
    lines: list[str] = []
    for table, columns in schema.items():
        cols = ", ".join(f"{c} {t}" for c, t in columns.items())
        lines.append(f"{table}({cols})")
        for fk in fks.get(table, []):
            lines.append(f"    FK {fk}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool surface
# ---------------------------------------------------------------------------


@tool
def list_schema() -> dict:
    """List every table in the database with its column names.

    Use this first when you do not know which tables exist. Returns table names and their
    columns, but not types or foreign keys — call get_table_schema for those.
    """
    schema = load_schema()
    return ok(
        f"{len(schema)} tables",
        tables={table: list(columns) for table, columns in schema.items()},
    ).to_dict()


@tool
def get_table_schema(table_name: str) -> dict:
    """Get the columns, types and foreign keys of one table.

    Args:
        table_name: exact table name, e.g. "orders". Case-insensitive.
    """
    schema = load_schema()
    key = (table_name or "").strip().lower()
    if key not in schema:
        return error(
            f"unknown table: {table_name!r}. Known tables: {', '.join(sorted(schema))}",
            error_kind="syntax",
        ).to_dict()
    return ok(
        f"schema of {key}",
        table=key,
        columns=schema[key],
        foreign_keys=load_foreign_keys().get(key, []),
    ).to_dict()


def get_table_schema_raw(table_name: str) -> ToolResult:
    """Non-tool accessor used by the API and tests."""
    return ToolResult(**get_table_schema.invoke({"table_name": table_name}))
