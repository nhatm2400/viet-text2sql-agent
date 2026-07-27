"""The iteration cap must be a hard stop.

`tests/fixtures/offline_llm.json` contains a script (`always_fails`) whose last turn repeats
forever: it keeps asking to run `DROP TABLE customers`, which is always blocked, so the model
never reaches a final answer. A correct graph terminates at exactly `max_iterations` with a
structured result. An incorrect one loops until LangGraph's recursion limit throws, or forever.

The distinction that matters: the run must end in a *result*, not an exception. An agent that
crashes on an unbounded loop is not bounded, it is merely noisy.
"""

from __future__ import annotations

import pytest

from t2sql.agent.build import run_agent

ALWAYS_FAILS = "Fixture: câu hỏi luôn thất bại để kiểm tra giới hạn vòng lặp"


@pytest.mark.parametrize("cap", [1, 2, 3, 6])
def test_terminates_at_exactly_max_iterations(cap: int) -> None:
    result = run_agent(ALWAYS_FAILS, max_iterations=cap)
    assert result["iterations"] == cap, "the loop must stop at the cap, not before or after"
    assert len(result["tool_calls"]) == cap


def test_returns_a_structured_could_not_complete_result_not_an_exception() -> None:
    result = run_agent(ALWAYS_FAILS, max_iterations=3)
    assert result["status"] == "exhausted"
    assert "could not complete safely" in result["answer"]
    assert result["sql"] is not None  # the attempted SQL is still reported, for the trace


def test_every_attempt_was_blocked_so_nothing_reached_the_database() -> None:
    result = run_agent(ALWAYS_FAILS, max_iterations=4)
    assert all(call["result"]["status"] == "blocked" for call in result["tool_calls"])


def test_cap_is_not_negotiable_by_the_model() -> None:
    """The model asks for another tool call on every single turn; it gets exactly `cap` of them."""
    small = run_agent(ALWAYS_FAILS, max_iterations=1)
    large = run_agent(ALWAYS_FAILS, max_iterations=5)
    assert len(small["tool_calls"]) == 1
    assert len(large["tool_calls"]) == 5


def test_invalid_cap_is_rejected_at_build_time() -> None:
    from t2sql.agent.build import build_agent

    with pytest.raises(ValueError):
        build_agent(max_iterations=0)


def test_a_normal_question_finishes_well_inside_the_cap() -> None:
    """Guard against 'fixed' by capping everything at 1: normal runs must still complete."""
    result = run_agent("Số đơn hàng bị huỷ theo từng kênh bán trong 6 tháng đầu năm 2026?")
    assert result["status"] == "executed"
    assert result["iterations"] < 6
