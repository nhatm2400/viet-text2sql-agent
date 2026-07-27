"""THE bypass proof.

The security claim this repository makes is: *the agent decides strategy, it never decides
policy*. The specific, falsifiable form of that claim is:

    There is no code path from an agent decision to the database that skips the AST policy.

Documentation cannot establish that. These tests can: they call `execute_sql` directly, with no
`validate_sql` call anywhere before them, and assert that disallowed statements are still
blocked and that nothing reaches a database connection.

If someone later "optimises" `execute` by trusting a prior validation, or adds a `skip_policy`
argument, this file fails. That is its job.
"""

from __future__ import annotations

import pytest

from t2sql.tools.execute_tool import execute, execute_sql

DISALLOWED = [
    "DROP TABLE customers",
    "DELETE FROM orders",
    "UPDATE orders SET status = 'paid'",
    "INSERT INTO orders (order_id) VALUES (1)",
    "SELECT order_id FROM orders; DROP TABLE orders",
    "SELECT tablename FROM pg_catalog.pg_tables",
    "SELECT email FROM customers",
    "SELECT * FROM customers",
    "SELECT order_id FROM orders -- ; DROP TABLE orders",
    "SELECT o.order_id, p.product_id FROM orders o, products p",
]


@pytest.mark.parametrize("sql", DISALLOWED)
def test_execute_blocks_without_any_prior_validate_call(sql: str) -> None:
    """No validate_sql. No agent. Straight to execute_sql — and still blocked."""
    result = execute(sql)
    assert result.status == "blocked", f"policy was bypassed for: {sql}"
    assert result.error_kind == "policy"
    assert result.data.get("reasons"), "a block must explain itself"
    assert "rows" not in result.data, "a blocked query must not return data"


@pytest.mark.parametrize("sql", DISALLOWED[:4])
def test_tool_surface_blocks_too(sql: str) -> None:
    """The same guarantee through the LangChain tool interface the agent actually calls."""
    payload = execute_sql.invoke({"sql": sql})
    assert payload["status"] == "blocked"


def test_blocked_query_never_opens_a_database_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enforcement happens before any driver work — not after a connection is already open."""
    import t2sql.tools.execute_tool as module

    def explode(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("execute_sql reached the database with a disallowed statement")

    monkeypatch.setattr(module, "_readonly_engine", explode)
    monkeypatch.setattr(module, "_execute_offline", explode)

    result = execute("DROP TABLE customers")
    assert result.status == "blocked"


def test_prior_validation_does_not_grant_an_exemption() -> None:
    """Validate a legitimate query first, then execute a malicious one in the same process.

    This is the agent-shaped attack: get one query approved, then send another. Because `execute`
    re-checks its own argument every time and holds no 'already validated' state, the second call
    is judged entirely on its own text.
    """
    from t2sql.tools.validate_tool import validate

    assert validate("SELECT order_id FROM orders LIMIT 5").status == "ok"
    assert execute("DROP TABLE customers").status == "blocked"


def test_allowed_query_is_executed_with_the_rewritten_sql() -> None:
    """The positive half: policy-clean SQL runs, and what runs is the LIMIT-enforced rewrite."""
    result = execute(
        "SELECT COUNT(*) AS customer_count FROM customers AS c "
        "JOIN regions AS r ON r.region_id = c.region_id "
        "WHERE r.region_code = 'SOUTH' AND c.status = 'active'"
    )
    assert result.status == "ok"
    assert "LIMIT 1000" in result.data["executed_sql"]


def test_every_execution_attempt_is_audited() -> None:
    """Blocked attempts are logged exactly like successful ones — audit lives with enforcement."""
    from t2sql.observability import tracing

    trace_id = tracing.new_trace_id()
    execute("DROP TABLE customers", trace_id=trace_id)
    steps = tracing.get_trace(trace_id)
    assert len(steps) == 1
    assert steps[0]["tool_name"] == "execute_sql"
    assert steps[0]["result"]["status"] == "blocked"
    assert steps[0]["arguments"]["sql"] == "DROP TABLE customers"
