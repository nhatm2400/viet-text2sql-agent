import json

import pytest

from eval.harness.compare_local import compare
from t2sql.agent.prompts import CALENDAR_WINDOW_RULES


def make_run(path, budget, recovered=False):
    path.mkdir()
    config = {
        "model": "qwen3:4b",
        "model_digest": "fixed-model",
        "split": "dev",
        "repeats": 1,
        "questions_sha256": "fixed-questions",
        "context": "same",
        "baseline_instruction": "same",
        "agent_instruction": "same",
        "api_version": {"version": "fixed"},
        "snapshot": {"snapshot_sha256": "fixed-snapshot"},
        "model_options": {"num_predict": budget, "num_ctx": 8192},
        "source_sha256": {},
    }
    (path / "config.json").write_text(json.dumps(config))
    records = [
        {
            "id": str(i),
            "variant": variant,
            "strict": bool(i or recovered),
            "relaxed": bool(i or recovered),
            "latency_ms": 100,
            "tokens": 50,
            "attempts": [{"status": "ok"}],
            "model_responses": [{"done_reason": "stop"}],
            "status": "ok",
        }
        for i in range(20)
        for variant in ("baseline", "agent")
    ]
    (path / "items.jsonl").write_text("\n".join(json.dumps(r) for r in records))
    (path / "summary.json").write_text("{}")
    return config


def test_comparison_uses_paired_full_dataset(tmp_path):
    make_run(tmp_path / "old", 2048)
    make_run(tmp_path / "new", 4096, recovered=True)
    report = compare(tmp_path / "old", tmp_path / "new")
    assert report["summary"]["agent"]["strict_delta_pp"] == 5
    assert report["summary"]["agent"]["recovered_ids"] == ["0"]
    assert report["summary"]["agent"]["regressed_ids"] == []


def test_comparison_rejects_changed_context_or_incomplete_run(tmp_path):
    make_run(tmp_path / "old", 2048)
    config = make_run(tmp_path / "new", 4096)
    config["context"] = "changed"
    (tmp_path / "new/config.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="context"):
        compare(tmp_path / "old", tmp_path / "new")
    config["context"] = "same"
    (tmp_path / "new/config.json").write_text(json.dumps(config))
    records = (tmp_path / "new/items.jsonl").read_text().splitlines()[:-1]
    (tmp_path / "new/items.jsonl").write_text("\n".join(records))
    with pytest.raises(ValueError, match="40 predictions"):
        compare(tmp_path / "old", tmp_path / "new")


def test_schema_axis_allows_only_added_check_lines_with_same_budget(tmp_path):
    make_run(tmp_path / "old", 4096)
    config = make_run(tmp_path / "new", 4096)
    config["context"] = "same\n    CHECK status IN ('cancelled', 'completed')"
    (tmp_path / "new/config.json").write_text(json.dumps(config))
    result = compare(tmp_path / "old", tmp_path / "new", axis="schema-checks")
    assert result["comparison_axis"] == "schema-checks"
    assert len(result["added_check_lines"]) == 1
    config["model_options"]["num_predict"] = 2048
    (tmp_path / "new/config.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="num_predict"):
        compare(tmp_path / "old", tmp_path / "new", axis="schema-checks")
    config["model_options"]["num_predict"] = 4096
    config["context"] += "\nNew unrelated instruction"
    (tmp_path / "new/config.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="only CHECK"):
        compare(tmp_path / "old", tmp_path / "new", axis="schema-checks")


def test_date_axis_rejects_other_prompt_or_budget_changes(tmp_path):
    make_run(tmp_path / "old", 4096)
    config = make_run(tmp_path / "new", 4096)
    config["context"] += CALENDAR_WINDOW_RULES
    (tmp_path / "new/config.json").write_text(json.dumps(config))
    report = compare(tmp_path / "old", tmp_path / "new", axis="date-windows")
    assert report["added_date_rules"] == CALENDAR_WINDOW_RULES
    config["context"] += "\nExtra unrelated instruction"
    (tmp_path / "new/config.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="only the calendar"):
        compare(tmp_path / "old", tmp_path / "new", axis="date-windows")
    config["context"] = "same" + CALENDAR_WINDOW_RULES
    config["model_options"]["num_predict"] = 2048
    (tmp_path / "new/config.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="num_predict"):
        compare(tmp_path / "old", tmp_path / "new", axis="date-windows")
