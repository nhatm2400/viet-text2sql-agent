"""sqlglot-based SQL execution policy — the layer the agent cannot opt out of.

Design contract
---------------
`check_sql()` is a pure function: SQL text in, `PolicyDecision` out. It touches no database,
no network and no LLM, which is precisely why it can be exhaustively unit-tested (see
tests/test_ast_policy.py) and why `execute_sql` can call it unconditionally on every single
execution path.

Order of checks matters. Textual checks run first (comment smuggling, multi-statement), because
a parser that "helpfully" ignores trailing junk would hide exactly the payload we care about.
Only then do we parse and walk the AST.

Everything is default-deny: an unrecognised node type, an unknown table, an unknown column or a
parse failure all block. A check that cannot reach a confident verdict returns "not allowed".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import sqlglot
import yaml
from sqlglot import exp

DIALECT = "postgres"

# Keywords that must never appear inside a comment — the classic smuggling payload.
_SMUGGLED_KEYWORDS = re.compile(
    r"\b(drop|delete|update|insert|alter|truncate|grant|revoke|create|copy|merge|call|do)\b",
    re.IGNORECASE,
)

# Top-level node types that are legitimate read queries.
_READ_NODES = (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)


@dataclass(frozen=True)
class PolicyDecision:
    """The structured verdict returned to `execute_sql`, `validate_sql` and the eval harness.

    `rewritten_sql` is set whenever the query is allowed but had to be modified (today: LIMIT
    injection or clamping). It is the ONLY SQL that may be sent to the database — callers must
    never fall back to the original text.
    """

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    rewritten_sql: str | None = None

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "rewritten_sql": self.rewritten_sql,
        }


def _blocked(*reasons: str) -> PolicyDecision:
    return PolicyDecision(allowed=False, reasons=list(reasons), rewritten_sql=None)


# ---------------------------------------------------------------------------
# Policy file
# ---------------------------------------------------------------------------

_DEFAULT_POLICY_PATH = Path(__file__).with_name("policy.yaml")


@lru_cache(maxsize=4)
def load_policy(path: str | None = None) -> dict[str, Any]:
    """Load and cache policy.yaml. Pass an explicit path in tests to use a variant policy."""
    target = Path(path) if path else _DEFAULT_POLICY_PATH
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    data.setdefault("max_rows", 1000)
    data.setdefault("max_statements", 1)
    data.setdefault("max_joins", 6)
    data.setdefault("require_limit", True)
    data.setdefault("denied_schemas", [])
    data.setdefault("allowed_tables", [])
    data.setdefault("sensitive_columns", [])
    data.setdefault("denied_functions", [])
    return data


# ---------------------------------------------------------------------------
# Stage 1 — textual checks (run before parsing, on purpose)
# ---------------------------------------------------------------------------


def _scan(sql: str) -> tuple[str, list[str]]:
    """Return (sql with comments blanked out, list of comment bodies).

    Hand-written scanner rather than a regex because a regex cannot tell a `--` inside a string
    literal from a real comment, and getting that wrong in either direction is a security bug:
    too strict blocks `WHERE note = 'a--b'`, too lax lets a payload through.
    """
    out: list[str] = []
    comments: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":  # single-quoted literal, '' escapes a quote
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif ch == '"':  # quoted identifier
            j = sql.find('"', i + 1)
            j = n - 1 if j == -1 else j
            out.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            comments.append(sql[i + 2 : j])
            out.append(" ")
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            comments.append(sql[i + 2 : max(i + 2, j - 2)])
            out.append(" ")
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out), comments


def _textual_checks(sql: str, policy: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    stripped, comments = _scan(sql)

    if not stripped.strip():
        return ["empty statement"]

    for body in comments:
        if ";" in body or _SMUGGLED_KEYWORDS.search(body):
            reasons.append(
                "comment smuggling: SQL keywords or a statement separator inside a comment"
            )
            break

    # Count statements on the comment-free text so `SELECT 1 -- ; DROP` cannot hide a semicolon.
    parts = [p for p in stripped.split(";") if p.strip()]
    if len(parts) > policy["max_statements"]:
        reasons.append(
            f"multiple statements ({len(parts)}); exactly {policy['max_statements']} allowed"
        )

    return reasons


# ---------------------------------------------------------------------------
# Stage 2 — AST checks
# ---------------------------------------------------------------------------


def _table_scope(tree: exp.Expression) -> tuple[dict[str, str], list[str]]:
    """Map every alias/name in scope to its real table name; collect reasons for bad tables."""
    scope: dict[str, str] = {}
    reasons: list[str] = []
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}

    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        db = (table.db or "").lower()
        if db:
            scope[db] = db  # schema-qualified; the schema check below handles legality
        if name in cte_names:
            scope[table.alias_or_name.lower()] = name
            continue
        scope[name] = name
        if table.alias:
            scope[table.alias.lower()] = name
    return scope, reasons


def _referenced_tables(tree: exp.Expression) -> tuple[set[str], set[str]]:
    """Return (real tables referenced, CTE names) — CTEs are not database objects."""
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables = {
        (t.name or "").lower()
        for t in tree.find_all(exp.Table)
        if (t.name or "").lower() not in cte_names
    }
    return tables, cte_names


def _check_statement_type(tree: exp.Expression) -> list[str]:
    if isinstance(tree, exp.Command) or not isinstance(tree, _READ_NODES):
        return [f"statement type not allowed: {tree.key.upper()} (SELECT-only policy)"]
    if isinstance(tree, exp.Select) and tree.args.get("into"):
        return ["SELECT INTO writes a table and is not allowed"]
    # A read query must not contain a write anywhere, including inside a CTE.
    write_nodes = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.TruncateTable,
        exp.Grant,
        exp.Merge,
        exp.Copy,
    )
    for node in tree.find_all(*write_nodes):
        return [f"write/DDL operation not allowed: {node.key.upper()}"]
    return []


def _check_schemas(tree: exp.Expression, policy: dict[str, Any]) -> list[str]:
    denied = {s.lower() for s in policy["denied_schemas"]}
    reasons: list[str] = []
    for table in tree.find_all(exp.Table):
        db = (table.db or "").lower()
        name = (table.name or "").lower()
        if db in denied or name.startswith("pg_") or name in denied:
            reasons.append(f"system catalog access is not allowed: {table.sql(dialect=DIALECT)}")
    return reasons


def _check_tables(tree: exp.Expression, policy: dict[str, Any]) -> list[str]:
    allowed = {t.lower() for t in policy["allowed_tables"]}
    tables, _ = _referenced_tables(tree)
    return [f"table not in allowlist: {t}" for t in sorted(tables - allowed)]


def _check_columns(tree: exp.Expression, policy: dict[str, Any]) -> list[str]:
    """Column allowlist + sensitive-column denylist, alias-aware.

    `SELECT *` over a table that owns a sensitive column is blocked outright: a star projection
    would return `customers.email` without ever naming it.
    """
    from t2sql.tools.schema_tools import load_schema  # local import: avoids an import cycle

    schema = load_schema()  # {table: {column: type}}
    sensitive: dict[str, set[str]] = {}
    for entry in policy["sensitive_columns"]:
        table, _, column = entry.partition(".")
        sensitive.setdefault(table.lower(), set()).add(column.lower())

    scope, reasons = _table_scope(tree)
    tables, cte_names = _referenced_tables(tree)
    real_tables = [t for t in tables if t in schema]

    # Names introduced by the query itself: `SUM(amount) AS revenue` makes `ORDER BY revenue`
    # legal even though no table has a `revenue` column.
    output_aliases = {alias.alias.lower() for alias in tree.find_all(exp.Alias) if alias.alias} | {
        column.name.lower()
        for cte in tree.find_all(exp.CTE)
        for column in (cte.args.get("alias").columns if cte.args.get("alias") else [])
    }

    # 1. star projections
    for star in tree.find_all(exp.Star):
        parent = star.parent
        if isinstance(parent, exp.Func):
            continue  # COUNT(*) counts rows; it returns no column values, sensitive or otherwise
        owner = None
        if isinstance(parent, exp.Column) and parent.table:
            owner = scope.get(parent.table.lower(), parent.table.lower())
        exposed = [t for t in ([owner] if owner else real_tables) if t in sensitive]
        if exposed:
            reasons.append(
                f"SELECT * would expose sensitive columns of: {', '.join(sorted(exposed))} "
                "— list the columns you need explicitly"
            )
            break

    # 2. named columns
    for column in tree.find_all(exp.Column):
        if isinstance(column.this, exp.Star):
            continue
        col = column.name.lower()
        qualifier = column.table.lower() if column.table else ""
        owner = scope.get(qualifier, qualifier)

        if owner and owner in cte_names:
            continue  # CTE output columns are validated where the CTE body is validated
        if owner and owner in schema:
            if col not in schema[owner]:
                reasons.append(f"unknown column: {owner}.{col}")
            elif col in sensitive.get(owner, ()):
                reasons.append(f"sensitive column is denied by policy: {owner}.{col}")
            continue
        if owner and owner not in schema:
            continue  # unknown qualifier already reported by the table check

        # Unqualified: resolve against every real table in scope.
        owners = [t for t in real_tables if col in schema.get(t, {})]
        if not owners and not cte_names and col not in output_aliases:
            reasons.append(f"unknown column: {col}")
        for candidate in owners:
            if col in sensitive.get(candidate, ()):
                reasons.append(f"sensitive column is denied by policy: {candidate}.{col}")

    return sorted(set(reasons))


def _check_functions(tree: exp.Expression, policy: dict[str, Any]) -> list[str]:
    denied = {f.lower() for f in policy["denied_functions"]}
    reasons: list[str] = []
    for node in tree.find_all(exp.Func):
        name = (node.sql_name() if hasattr(node, "sql_name") else node.key).lower()
        if isinstance(node, exp.Anonymous):
            name = str(node.this).lower()
        if name in denied:
            reasons.append(f"function not allowed: {name}()")
    return sorted(set(reasons))


def _check_joins(tree: exp.Expression, policy: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    joins = list(tree.find_all(exp.Join))
    if len(joins) > policy["max_joins"]:
        reasons.append(f"too many joins ({len(joins)} > {policy['max_joins']})")

    # An explicit CROSS JOIN is treated the same as an accidental one: at this layer the two are
    # indistinguishable, and `orders x products` is 6M rows.
    if any(not join.args.get("on") and not join.args.get("using") for join in joins):
        reasons.append("unbounded cartesian join: JOIN without ON/USING")

    # Comma-joined FROM with several tables and no WHERE is the same product in older syntax.
    for select in tree.find_all(exp.Select):
        from_ = select.args.get("from")
        select_joins = select.args.get("joins") or []
        n_tables = (1 if from_ else 0) + len(select_joins)
        unconstrained = not any(j.args.get("on") or j.args.get("using") for j in select_joins)
        if (
            from_
            and isinstance(from_.this, exp.Table)
            and n_tables > 1
            and not select.args.get("where")
            and unconstrained
        ):
            reasons.append("unbounded cartesian join: multiple tables with no join predicate")
            break
    return sorted(set(reasons))


# ---------------------------------------------------------------------------
# Stage 3 — LIMIT enforcement (rewrite, not reject)
# ---------------------------------------------------------------------------


def _enforce_limit(tree: exp.Expression, max_rows: int) -> tuple[exp.Expression, list[str]]:
    """Inject a LIMIT when absent, clamp it when too large. Returns (tree, notes)."""
    notes: list[str] = []
    limit = tree.args.get("limit")

    if limit is None:
        notes.append(f"no LIMIT in query; injected LIMIT {max_rows}")
        return tree.limit(max_rows), notes

    value = limit.expression
    if isinstance(value, exp.Literal) and value.is_int:
        current = int(value.name)
        if current > max_rows:
            notes.append(f"LIMIT {current} exceeds max_rows; clamped to {max_rows}")
            return tree.limit(max_rows), notes
        return tree, notes

    notes.append(f"non-literal LIMIT replaced with LIMIT {max_rows}")
    return tree.limit(max_rows), notes


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_sql(sql: str, *, policy_path: str | None = None) -> PolicyDecision:
    """Validate `sql` against the policy. Default-deny: anything unclear is blocked.

    Returns a `PolicyDecision`. When `allowed` is True, `rewritten_sql` holds the exact text to
    execute — it always differs from the input at least by normalisation, and callers must send
    `rewritten_sql`, never the original.
    """
    if not isinstance(sql, str) or not sql.strip():
        return _blocked("empty SQL")

    policy = load_policy(policy_path)

    if reasons := _textual_checks(sql, policy):
        return _blocked(*reasons)

    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except sqlglot.errors.ParseError as err:
        return _blocked(f"SQL parse error: {str(err).splitlines()[0]}")

    if len(statements) != 1:
        return _blocked(f"expected exactly 1 statement, parsed {len(statements)}")

    tree = statements[0]

    reasons: list[str] = []
    reasons += _check_statement_type(tree)
    if reasons:
        return _blocked(*reasons)  # nothing below is meaningful for a non-SELECT

    reasons += _check_schemas(tree, policy)
    reasons += _check_tables(tree, policy)
    if not reasons:  # column checks are only meaningful once the tables are known-good
        reasons += _check_columns(tree, policy)
    reasons += _check_functions(tree, policy)
    reasons += _check_joins(tree, policy)

    if reasons:
        return _blocked(*reasons)

    tree, notes = _enforce_limit(tree, policy["max_rows"])
    return PolicyDecision(allowed=True, reasons=notes, rewritten_sql=tree.sql(dialect=DIALECT))
