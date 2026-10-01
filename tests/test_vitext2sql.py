import json
import shutil
import sqlite3
import sys
import urllib.error

import pytest

from eval.datasets.external.download_vitext2sql import sha256
from eval.harness import live_vitext2sql as runner
from eval.harness.live_vitext2sql import (
    acquire_run_lock,
    evaluate_item,
    load_package,
    read_records,
    select_pilot,
)
from eval.harness.prepare_vitext2sql import align_items
from eval.harness.report_vitext2sql import report
from eval.harness.sqlite_readonly import connect_readonly, execute_select
from t2sql.llm import ollama_local
from t2sql.llm.ollama_local import OllamaLocal


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


@pytest.mark.parametrize("variant", ["baseline", "agent"])
@pytest.mark.parametrize("error_type", [urllib.error.URLError, TimeoutError, ConnectionError])
def test_runtime_disconnect_aborts_instead_of_becoming_model_miss(
    database, monkeypatch, variant, error_type
):
    def disconnected(*args, **kwargs):
        raise error_type("local server stopped")

    monkeypatch.setattr(ollama_local, "request_json", disconnected)
    item = {
        "id": "synthetic",
        "db_id": "sample",
        "question_vi": "Count",
        "gold_sql": "SELECT COUNT(*) FROM sample",
    }
    with pytest.raises(error_type):
        evaluate_item(item, variant, OllamaLocal(), database, "schema")


@pytest.mark.parametrize("error_type", [urllib.error.URLError, TimeoutError, ConnectionError])
def test_agent_disconnect_after_successful_sql_still_aborts(database, monkeypatch, error_type):
    calls = []

    def disconnected_after_tool(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise error_type("disconnected while generating final answer")
        return {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "execute_sql",
                            "arguments": {"sql": "SELECT COUNT(*) FROM sample"},
                        }
                    }
                ],
            },
            "prompt_eval_count": 10,
            "eval_count": 10,
        }

    monkeypatch.setattr(ollama_local, "request_json", disconnected_after_tool)
    item = {
        "id": "synthetic",
        "db_id": "sample",
        "question_vi": "Count",
        "gold_sql": "SELECT COUNT(*) FROM sample",
    }
    with pytest.raises(error_type):
        evaluate_item(item, "agent", OllamaLocal(), database, "schema")
    assert len(calls) == 2


@pytest.fixture
def interrupted_run(database, tmp_path, monkeypatch):
    """Exercise CLI orchestration with a real package/checkpoint and a simulated outage."""
    root = tmp_path / "repo"
    package = root / "data/package"
    package.mkdir(parents=True)
    shutil.copyfile(database, package / "sample.sqlite")
    (root / "implementation.py").write_text("# fixed source\n", encoding="utf-8")
    questions = [
        {
            "id": ident,
            "db_id": "sample",
            "question_vi": "Count",
            "gold_sql": "SELECT COUNT(*) FROM sample",
            "source_sql_ast_sha256": "fixed-ast",
        }
        for ident in ("a", "b")
    ]
    (package / "questions.json").write_text(json.dumps(questions), encoding="utf-8")
    (package / "exclusions.json").write_text("[]", encoding="utf-8")
    manifest = {
        "split": "dev",
        "setting": "Synthetic fixture; no external dataset",
        "source_count": 2,
        "ast_aligned_count": 2,
        "eligible_count": 2,
        "database_count": 1,
        "empty_gold_count": 0,
        "questions_sha256": sha256(package / "questions.json"),
        "exclusions_sha256": sha256(package / "exclusions.json"),
        "databases": {
            "sample": {
                "path": "sample.sqlite",
                "sha256": sha256(package / "sample.sqlite"),
                "context": "schema",
            }
        },
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(runner, "REPO_ROOT", root)
    monkeypatch.setattr(runner, "SOURCES", ["implementation.py"])
    metadata = {"digest": "fixed-model", "version": "fixed-runtime"}

    def response(base_url, path, payload=None):
        return {
            "/api/tags": {"models": [{"name": "qwen3:4b", "digest": metadata["digest"]}]},
            "/api/show": {"capabilities": ["tools"]},
            "/api/version": {"version": metadata["version"]},
            "/api/chat": {"message": {"content": "OK"}},
        }[path]

    monkeypatch.setattr(runner, "request_json", response)
    monkeypatch.setattr(ollama_local, "request_json", response)
    calls = []

    def evaluation(item, variant, *args):
        calls.append((item["id"], variant))
        if len(calls) == 3:
            raise TimeoutError("simulated runtime outage")
        correct = (item["id"], variant) != ("a", "baseline")
        return {
            "id": item["id"],
            "db_id": item["db_id"],
            "question": item["question_vi"],
            "variant": variant,
            "strict": correct,
            "relaxed": correct,
            "gold_empty": False,
            "status": "executed",
            "tokens": None,
            "model_calls": 0,
            "latency_ms": 1,
            "model_responses": [],
            "attempts": [{"status": "ok", "sql": item["gold_sql"] if correct else "SELECT 0"}],
        }

    monkeypatch.setattr(runner, "evaluate_item", evaluation)
    argv = ["live_vitext2sql", "--package", str(package)]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(TimeoutError):
        runner.main()
    out = next((root / "eval/results").iterdir())
    assert not (out / "summary.json").exists()
    assert json.loads((out / "progress.json").read_text())["completed_predictions"] == 2
    assert (out / "source/implementation.py").read_bytes() == (
        root / "implementation.py"
    ).read_bytes()
    # Lock must also be released on an exception in the same process.
    acquire_run_lock(out / "run.lock").close()
    return root, package, out, calls, metadata, argv


def test_aggregate_report_replays_predictions_without_exporting_question_or_sql(
    interrupted_run, monkeypatch
):
    root, package, out, calls, metadata, argv = interrupted_run
    monkeypatch.setattr(sys, "argv", argv + ["--resume", str(out)])
    runner.main()
    exported = report(out)
    assert exported["summary"]["metrics"]["baseline"]["strict_ex"] == 50
    assert exported["summary"]["metrics"]["agent"]["strict_ex"] == 100
    assert exported["population"]["evaluated_questions"] == 2
    assert exported["population"]["distinct_database_ast_pairs"] == 1
    text = json.dumps(exported)
    assert "SELECT COUNT(*) FROM sample" not in text
    assert '"question"' not in text and '"attempts"' not in text and '"model_responses"' not in text


def test_prefix_report_labels_full_run_incomplete_and_replays_only_completed_prefix(
    interrupted_run,
):
    root, package, out, calls, metadata, argv = interrupted_run
    exported = report(out, prefix_size=1)
    assert exported["population"]["evaluated_questions"] == 1
    assert exported["population"]["eligible_questions"] == 2
    assert exported["scope"]["requested_subset_complete"]
    assert not exported["scope"]["full_run_complete"]
    assert exported["summary"]["expected_predictions"] == 2
    assert exported["summary"]["metrics"]["baseline"]["strict_ex"] == 0
    assert exported["summary"]["metrics"]["agent"]["strict_ex"] == 100
    assert not (out / "summary.json").exists()


@pytest.mark.parametrize("prefix_size", [0, 2, 3])
def test_prefix_report_rejects_invalid_or_unfinished_prefix(interrupted_run, prefix_size):
    root, package, out, calls, metadata, argv = interrupted_run
    with pytest.raises(ValueError, match="prefix"):
        report(out, prefix_size=prefix_size)


@pytest.mark.parametrize("change", ["partial", "summary", "score", "source"])
def test_aggregate_report_rejects_incomplete_or_inconsistent_evidence(
    interrupted_run, monkeypatch, change
):
    root, package, out, calls, metadata, argv = interrupted_run
    if change != "partial":
        monkeypatch.setattr(sys, "argv", argv + ["--resume", str(out)])
        runner.main()
    if change == "summary":
        summary_path = out / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["metrics"]["baseline"]["strict_ex"] = 100
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
    elif change == "score":
        path = out / "items.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        records[0]["strict"] = True
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    elif change == "source":
        (out / "source/implementation.py").write_text("modified", encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        report(out)


def test_resume_keeps_recorded_misses_and_evaluates_only_unfinished_predictions(
    interrupted_run, monkeypatch
):
    root, package, out, calls, metadata, argv = interrupted_run
    before = (out / "items.jsonl").read_bytes()
    monkeypatch.setattr(sys, "argv", argv + ["--resume", str(out)])
    runner.main()
    assert calls == [
        ("a", "baseline"),
        ("a", "agent"),
        ("b", "agent"),
        ("b", "agent"),
        ("b", "baseline"),
    ]
    assert (out / "items.jsonl").read_bytes().startswith(before)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["complete"] and summary["completed_predictions"] == 4
    assert summary["metrics"]["baseline"]["strict_correct"] == 1
    assert summary["metrics"]["agent"]["strict_correct"] == 2
    runner.main()  # Completed resume must not redo predictions.
    assert len(calls) == 5


def test_pause_finishes_current_prediction_and_resume_keeps_it(interrupted_run, monkeypatch):
    root, package, out, calls, metadata, argv = interrupted_run
    evaluate = runner.evaluate_item

    def request_pause_after_prediction(*args):
        record = evaluate(*args)
        (out / "pause.request").write_text("pause", encoding="utf-8")
        return record

    monkeypatch.setattr(runner, "evaluate_item", request_pause_after_prediction)
    monkeypatch.setattr(sys, "argv", argv + ["--resume", str(out)])
    runner.main()
    progress = json.loads((out / "progress.json").read_text())
    assert progress["completed_predictions"] == 3 and not progress["complete"]
    assert not (out / "summary.json").exists()
    before = (out / "items.jsonl").read_bytes()
    acquire_run_lock(out / "run.lock").close()
    monkeypatch.setattr(runner, "evaluate_item", evaluate)
    runner.main()
    assert not (out / "pause.request").exists()
    assert (out / "items.jsonl").read_bytes().startswith(before)
    assert json.loads((out / "summary.json").read_text())["complete"]
    assert calls[-2:] == [("b", "agent"), ("b", "baseline")]


@pytest.mark.parametrize("change", ["options", "source", "model", "runtime", "database"])
def test_resume_rejects_changed_inputs_before_model_inference(interrupted_run, monkeypatch, change):
    root, package, out, calls, metadata, argv = interrupted_run
    original = (out / "items.jsonl").read_bytes()
    extra = []
    if change == "options":
        extra = ["--num-predict", "2048"]
    elif change == "source":
        (root / "implementation.py").write_text("# changed source\n", encoding="utf-8")
    elif change == "model":
        metadata["digest"] = "changed-model"
    elif change == "runtime":
        metadata["version"] = "changed-runtime"
    else:
        with sqlite3.connect(package / "sample.sqlite") as conn:
            conn.execute("INSERT INTO sample VALUES (4, 'changed')")
    monkeypatch.setattr(sys, "argv", argv + ["--resume", str(out)] + extra)
    with pytest.raises(ValueError, match="changed|incompatible"):
        runner.main()
    assert len(calls) == 3
    assert (out / "items.jsonl").read_bytes() == original
    assert not (out / "summary.json").exists()


def test_session_time_budget_pauses_without_changing_evaluation_protocol(
    interrupted_run, monkeypatch
):
    root, package, out, calls, metadata, argv = interrupted_run
    ticks = iter([0, 0.5, 2])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(sys, "argv", argv + ["--resume", str(out), "--max-wall-seconds", "1"])
    runner.main()
    assert len(calls) == 4
    progress = json.loads((out / "progress.json").read_text())
    assert progress["completed_predictions"] == 3 and not progress["complete"]
    assert not (out / "summary.json").exists()
