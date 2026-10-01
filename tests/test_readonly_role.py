"""The database-level half of the security model.

Layers 2 and 3 (AST policy, execution wrapper) are application code, and application code has
bugs. Layer 1 is the grant set on `t2sql_ro`: SELECT-only, `default_transaction_read_only`, a
5-second `statement_timeout`. It is the only layer that survives a mistake in the other two, so
it deserves a test that talks to a real database rather than a mock.

Which means this test cannot run offline. It **skips with an explicit message** when no database
is reachable — it never silently passes, because a green tick that proves nothing is worse than a
visible skip. Run it against a provisioned Postgres (see deploy/provision.sh) to exercise it:

    DATABASE_URL_RO=postgresql+psycopg://t2sql_ro:...@localhost:5432/t2sql pytest tests/test_readonly_role.py
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from t2sql.config import get_settings  # noqa: E402

SKIP_REASON = (
    "no DATABASE_URL_RO configured, or the database is unreachable — run against a provisioned "
    "Postgres (deploy/provision.sh, then db/roles.sql) to exercise this test. It is intentionally "
    "skipped rather than faked: mocking a permission error would prove nothing about the grants."
)


@pytest.fixture(scope="module")
def ro_engine():
    url = get_settings().database_url_ro
    if not url:
        pytest.skip(SKIP_REASON)
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as err:
        pytest.skip(f"{SKIP_REASON} (connection failed: {err})")
    return engine


def test_select_is_permitted(ro_engine) -> None:
    with ro_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM orders")).scalar() is not None


def test_insert_fails_at_the_database_level(ro_engine) -> None:
    """The claim under test: even if every application layer were bypassed, the write fails."""
    with pytest.raises(SQLAlchemyError) as err, ro_engine.connect() as conn:
        conn.execute(
            text("INSERT INTO regions (region_id, region_name, region_code) VALUES (99, 'X', 'X')")
        )
    message = str(err.value).lower()
    assert "permission denied" in message or "read-only" in message


def test_update_fails_at_the_database_level(ro_engine) -> None:
    with pytest.raises(SQLAlchemyError), ro_engine.connect() as conn:
        conn.execute(text("UPDATE orders SET status = 'paid' WHERE order_id = 1"))


def test_delete_fails_at_the_database_level(ro_engine) -> None:
    with pytest.raises(SQLAlchemyError), ro_engine.connect() as conn:
        conn.execute(text("DELETE FROM orders WHERE order_id = 1"))


def test_ddl_fails_at_the_database_level(ro_engine) -> None:
    with pytest.raises(SQLAlchemyError), ro_engine.connect() as conn:
        conn.execute(text("CREATE TABLE evil (id INT)"))


def test_statement_timeout_is_set_on_the_role(ro_engine) -> None:
    """A cartesian product the AST policy failed to spot must still die in 5 seconds."""
    with ro_engine.connect() as conn:
        timeout = conn.execute(text("SHOW statement_timeout")).scalar()
    assert timeout == "5s", "statement_timeout must be exactly 5 seconds for t2sql_ro"


def test_transactions_default_to_read_only(ro_engine) -> None:
    with ro_engine.connect() as conn:
        assert conn.execute(text("SHOW default_transaction_read_only")).scalar() == "on"


def test_timeout_actually_cancels_a_query(ro_engine) -> None:
    with pytest.raises(SQLAlchemyError) as err, ro_engine.connect() as conn:
        conn.execute(text("SELECT pg_sleep(6)"))
    assert getattr(err.value.orig, "sqlstate", None) == "57014"


def test_write_still_fails_when_readonly_default_is_disabled(ro_engine) -> None:
    with pytest.raises(SQLAlchemyError) as err, ro_engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ WRITE"))
        conn.execute(text("UPDATE orders SET status = 'paid' WHERE order_id = -1"))
    assert getattr(err.value.orig, "sqlstate", None) == "42501"


def test_trace_table_is_inaccessible_to_query_role(ro_engine) -> None:
    with pytest.raises(SQLAlchemyError) as err, ro_engine.connect() as conn:
        conn.execute(text("SELECT * FROM agent_traces LIMIT 1"))
    assert getattr(err.value.orig, "sqlstate", None) == "42501"


def test_application_session_timeout_survives_pool_initialization(ro_engine, monkeypatch) -> None:
    from t2sql.config import reload_settings
    from t2sql.tools.execute_tool import _RO_ENGINES, _readonly_engine

    url = reload_settings().database_url_ro
    old_engine = _RO_ENGINES.pop(url, None)
    if old_engine is not None:
        old_engine.dispose()
    monkeypatch.setenv("STATEMENT_TIMEOUT_MS", "100")
    reload_settings()
    try:
        engine = _readonly_engine(url)
        for _ in range(2):
            with engine.connect() as conn:
                assert conn.execute(text("SHOW statement_timeout")).scalar() == "100ms"
        with pytest.raises(SQLAlchemyError) as err, engine.connect() as conn:
            conn.execute(text("SELECT pg_sleep(0.3)"))
        assert getattr(err.value.orig, "sqlstate", None) == "57014"
    finally:
        _RO_ENGINES.pop(url).dispose()
        monkeypatch.delenv("STATEMENT_TIMEOUT_MS")
        reload_settings()
