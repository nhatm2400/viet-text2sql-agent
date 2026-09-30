import json
import sqlite3
import urllib.error

import pytest

from eval.harness.live_vitext2sql import (
    acquire_run_lock,
    evaluate_item,
    load_package,
    read_records,
    select_pilot,
)
from eval.harness.prepare_vitext2sql import align_items
from eval.harness.sqlite_readonly import connect_readonly, execute_select


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER, value TEXT)")
        conn.executemany("INSERT INTO sample VALUES (?,?)", [(1, "A"), (2, "B"), (2, "B")])
    return path


def test_native_execution_counts_and_keeps_duplicates_without_limit_rewriting(database):
    conn = connect_readonly(database)
    try:
        assert execute_select(conn, "SELECT COUNT(*) FROM sample").rows == [(3,)]
        assert execute_select(conn, "SELECT value FROM sample ORDER BY id DESC").rows == [
            ("B",),
            ("B",),
            ("A",),
        ]
        assert execute_select(
            conn, "WITH x AS (SELECT * FROM sample) SELECT COUNT(*) FROM x"
        ).rows == [(3,)]
    finally:
        conn.close()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM sample",
        "DROP TABLE sample",
        "PRAGMA user_version=3",
        "ATTACH ':memory:' AS other",
        "SELECT 1; DELETE FROM sample",
        "SELECT name FROM sqlite_master",
        "SELECT load_extension('missing')",
        "WITH x AS (SELECT 1) DELETE FROM sample",
    ],
)
def test_external_readonly_boundary_does_not_allow_writes_or_catalog_access(database, sql):
    conn = connect_readonly(database)
    try:
        with pytest.raises((ValueError, sqlite3.Error)):
            execute_select(conn, sql)
        assert execute_select(conn, "SELECT COUNT(*) FROM sample").rows == [(3,)]
    finally:
        conn.close()


def test_alignment_never_ignores_different_values_or_database_ids():
    english = [{"db_id": "a", "sql": {"where": ["female"]}, "query": "SELECT 'female'"}]
    vi = [
        {"db_id": "a", "sql": {"where": ["female"]}, "question": "matching"},
        {"db_id": "a", "sql": {"where": ["male"]}, "question": "different value"},
        {"db_id": "b", "sql": {"where": ["female"]}, "question": "different db"},
    ]
    matched, excluded = align_items(vi, english, "dev")
    assert [item["id"] for item in matched] == ["vi-dev-0000"]
    assert len(excluded) == 2
    assert matched[0]["gold_sql"] == english[0]["query"]


def test_pilot_is_deterministic_across_databases_and_full_selection_preserves_all():
    items = [{"id": f"{db}-{i}", "db_id": db} for db in "abcdef" for i in range(3)]
    first = select_pilot(items, 4)
    assert first == select_pilot(items, 4)
    assert len({item["db_id"] for item in first}) == 4
    assert select_pilot(items, 0) == items


def test_resume_rejects_duplicate_records_and_unknown_question_ids(tmp_path):
    path = tmp_path / "items.jsonl"
    record = {"id": "a", "variant": "agent"}
    path.write_text(json.dumps(record) + "\n")
    assert read_records(path, {("a", "agent")}) == [record]
    with pytest.raises(ValueError, match="unexpected"):
        read_records(path, {("b", "agent")})
    path.write_text((json.dumps(record) + "\n") * 2)
    with pytest.raises(ValueError, match="Duplicate"):
        read_records(path, {("a", "agent")})


def test_package_loading_rejects_modified_annotations(tmp_path):
    (tmp_path / "questions.json").write_text("[]")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"questions_sha256": "incorrect", "exclusions_sha256": "incorrect"})
    )
    with pytest.raises(ValueError, match="changed"):
        load_package(tmp_path)


def test_run_lock_rejects_second_worker_and_releases_on_close(tmp_path):
    path = tmp_path / "run.lock"
    first = acquire_run_lock(path)
    try:
        with pytest.raises(ValueError, match="Another worker"):
            acquire_run_lock(path)
    finally:
        first.close()
    next_worker = acquire_run_lock(path)
    next_worker.close()


def test_runtime_disconnect_aborts_instead_of_becoming_model_miss(database):
    class DisconnectedModel:
        audit = []

        def invoke(self, messages):
            raise urllib.error.URLError("local server stopped")

    item = {
        "id": "synthetic",
        "db_id": "sample",
        "question_vi": "Count",
        "gold_sql": "SELECT COUNT(*) FROM sample",
    }
    with pytest.raises(urllib.error.URLError):
        evaluate_item(item, "baseline", DisconnectedModel(), database, "schema")
