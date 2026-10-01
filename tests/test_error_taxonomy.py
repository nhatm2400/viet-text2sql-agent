"""Taxonomy precedence must follow scoring, rather than erase execution failures."""

from eval.harness.analyze_vitext2sql import classify
from eval.harness.scoring import ResultSet


def record(*, columns=None, rows=None, status="executed", strict=False, relaxed=False, cap=False):
    return {
        "strict": strict,
        "relaxed": relaxed,
        "status": status,
        "attempts": [{"status": "ok", "columns": columns or ["x"], "rows": rows or [[1]]}],
        "model_responses": [{"done_reason": "length" if cap else "stop"}],
    }


def test_failed_final_execution_is_not_classified_as_a_value_error():
    r = record()
    r["attempts"].append({"status": "error"})
    assert (
        classify(r, ResultSet(["x"], [(1,)]), "SELECT x")
        == "non_successful_final_state_after_earlier_success"
    )


def test_capped_final_answer_does_not_erase_a_successful_prediction():
    r = record(strict=True, relaxed=True, cap=True)
    assert classify(r, ResultSet(["x"], [(1,)]), "SELECT x") == "strict_correct"


def test_projection_and_order_are_distinct():
    gold = ResultSet(["x"], [(1,), (2,)])
    extra = record(columns=["x", "extra"], rows=[[1, 9], [2, 8]], relaxed=True)
    assert classify(extra, gold, "SELECT x ORDER BY x") == "projection_difference_relaxed_match"
    reverse = record(rows=[[2], [1]])
    assert classify(reverse, gold, "SELECT x ORDER BY x") == "row_order_only_difference"


def test_absent_sql_does_not_get_confused_with_empty_results():
    r = record(cap=True)
    r["attempts"] = []
    assert classify(r, ResultSet(["x"], []), "SELECT x") == "no_successful_sql_with_output_cap"
