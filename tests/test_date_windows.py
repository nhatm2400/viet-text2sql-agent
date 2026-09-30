import sqlite3

from eval.harness.live_local import build_context, execute_query
from t2sql.agent.prompts import CALENDAR_WINDOW_RULES, system_prompt


def test_half_open_timestamp_window_keeps_last_day_and_excludes_next_period():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE sample (paid_at TEXT, amount INTEGER)")
        conn.executemany(
            "INSERT INTO sample VALUES (?,?)",
            [
                ("2026-03-31 23:59:59", 100),
                ("2026-04-01 00:00:00", 1),
                ("2026-06-30 00:00:00", 2),
                ("2026-06-30 23:59:59", 4),
                ("2026-07-01 00:00:00", 100),
            ],
        )
        correct = execute_query(
            conn,
            "SELECT SUM(amount) FROM sample WHERE paid_at >= '2026-04-01' AND paid_at < '2026-07-01'",
        )
        old = execute_query(
            conn,
            "SELECT SUM(amount) FROM sample WHERE paid_at >= '2026-04-01' AND paid_at <= '2026-06-30'",
        )
        assert correct.rows == [(7,)]
        assert old.rows == [(1,)]
    finally:
        conn.close()


def test_date_rule_is_shared_without_changing_existing_context():
    old = build_context("with-checks", "unchanged")
    new = build_context("with-checks", "half-open")
    assert new == old + CALENDAR_WINDOW_RULES
    assert system_prompt() == system_prompt(date_windows=False) + CALENDAR_WINDOW_RULES
