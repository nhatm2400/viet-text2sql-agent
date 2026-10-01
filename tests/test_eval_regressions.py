"""Regressions that otherwise produce misleading evaluation results."""

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from eval.harness.metrics import aggregate, percentile
from t2sql.agent.build import summarise


@pytest.mark.parametrize(
    ("values", "p", "expected"),
    [
        ([1, 2], 50, 1),
        (list(range(1, 101)), 95, 95),
        ([4], 95, 4),
        ([], 95, None),
    ],
)
def test_nearest_rank(values, p, expected):
    assert percentile(values, p) == expected


@pytest.mark.parametrize("later_status", ["error", "blocked"])
def test_failed_query_cannot_reuse_previous_rows(later_status):
    messages = []
    for i, status in enumerate(["ok", later_status]):
        messages += [
            AIMessage(
                content="",
                tool_calls=[{"name": "execute_sql", "id": str(i), "args": {"sql": f"SELECT {i}"}}],
            ),
            ToolMessage(
                tool_call_id=str(i),
                content=json.dumps(
                    {
                        "status": status,
                        "data": {"rows": [{"n": 123}], "columns": ["n"]} if status == "ok" else {},
                    }
                ),
            ),
        ]
    messages.append(AIMessage(content="Final answer"))
    result = summarise({"messages": messages, "iteration_count": 2}, 6)
    assert result["status"] == later_status
    assert result["rows"] == []
    assert result["columns"] == []
    assert result["sql"] == "SELECT 1"


def test_first_pass_uses_first_attempt_not_all_attempts():
    metrics = aggregate(
        [
            {"execute_statuses": ["ok", "error"], "status": "error"},
            {"execute_statuses": ["error", "ok"], "status": "executed"},
            {"execute_statuses": ["error", "error"], "status": "error"},
        ]
    )
    assert metrics.first_pass_success_rate == 33.33
    assert metrics.self_correction_success_rate == 50


def test_text_only_reply_is_neither_execution_nor_policy_block():
    state = {"messages": [AIMessage(content="I cannot run DROP TABLE.")], "iteration_count": 0}
    result = summarise(state, 6)
    assert result["status"] == "answered"
    assert result["sql"] is None
    assert result["rows"] == []
    assert result["blocked_reasons"] == []


def test_missing_attempt_order_is_not_invented():
    metrics = aggregate([{"execute_attempts": 2, "execute_failures": 1, "status": "executed"}])
    assert metrics.first_pass_success_rate is None
    assert metrics.self_correction_success_rate is None
