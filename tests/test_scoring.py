"""Tests for strict vs relaxed execution accuracy.

Every case here is a *disagreement* case: a result set where the two metrics deliberately give
different verdicts. That is the point of reporting both — the gap between them is where
projection differences, column ordering and normalisation live, and a single number would hide
all three.

Fabricated result sets only. No database, no LLM.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from eval.harness.scoring import (
    canonical_name,
    has_top_level_order_by,
    normalize_value,
    relaxed_ex,
    score_item,
    strict_ex,
)

GOLD_ORDERED = "SELECT name, revenue FROM t ORDER BY revenue DESC"
GOLD_UNORDERED = "SELECT name, revenue FROM t"


# ---------------------------------------------------------------------------
# Row order
# ---------------------------------------------------------------------------


def test_row_order_ignored_when_gold_has_no_order_by() -> None:
    gold = [{"name": "a", "revenue": 1}, {"name": "b", "revenue": 2}]
    predicted = [{"name": "b", "revenue": 2}, {"name": "a", "revenue": 1}]
    assert strict_ex(predicted, gold, GOLD_UNORDERED)
    assert relaxed_ex(predicted, gold, GOLD_UNORDERED)


def test_row_order_enforced_when_gold_has_order_by() -> None:
    gold = [{"name": "b", "revenue": 2}, {"name": "a", "revenue": 1}]
    predicted = [{"name": "a", "revenue": 1}, {"name": "b", "revenue": 2}]
    assert not strict_ex(predicted, gold, GOLD_ORDERED)
    assert not relaxed_ex(predicted, gold, GOLD_ORDERED)


def test_order_by_inside_a_subquery_does_not_make_the_comparison_ordered() -> None:
    """An inner ORDER BY is an implementation detail, not part of the answer."""
    sql = "SELECT name, revenue FROM (SELECT name, revenue FROM t ORDER BY name) AS x"
    assert not has_top_level_order_by(sql)
    gold = [{"name": "a", "revenue": 1}, {"name": "b", "revenue": 2}]
    predicted = list(reversed(gold))
    assert strict_ex(predicted, gold, sql)


# ---------------------------------------------------------------------------
# Extra columns — the headline strict/relaxed disagreement
# ---------------------------------------------------------------------------


def test_extra_predicted_column_fails_strict_passes_relaxed() -> None:
    gold = [{"name": "a", "revenue": 1}, {"name": "b", "revenue": 2}]
    predicted = [
        {"id": 10, "name": "a", "revenue": 1},
        {"id": 11, "name": "b", "revenue": 2},
    ]
    assert not strict_ex(predicted, gold, GOLD_UNORDERED)
    assert relaxed_ex(predicted, gold, GOLD_UNORDERED)


def test_missing_column_fails_both() -> None:
    gold = [{"name": "a", "revenue": 1}]
    predicted = [{"name": "a"}]
    assert not strict_ex(predicted, gold, GOLD_UNORDERED)
    assert not relaxed_ex(predicted, gold, GOLD_UNORDERED)


def test_swapped_column_order_fails_strict_passes_relaxed() -> None:
    gold = [{"name": "a", "revenue": 1}, {"name": "b", "revenue": 2}]
    predicted = [{"revenue": 1, "name": "a"}, {"revenue": 2, "name": "b"}]
    assert not strict_ex(predicted, gold, GOLD_UNORDERED)
    assert relaxed_ex(predicted, gold, GOLD_UNORDERED)


def test_relaxed_matches_by_value_when_names_differ() -> None:
    gold = [{"name": "a", "revenue": 1}, {"name": "b", "revenue": 2}]
    predicted = [{"c0": "a", "c1": 1}, {"c0": "b", "c1": 2}]
    assert relaxed_ex(predicted, gold, GOLD_UNORDERED)


def test_relaxed_rejects_wrong_values_even_with_matching_names() -> None:
    gold = [{"name": "a", "revenue": 1}]
    predicted = [{"name": "a", "revenue": 999}]
    assert not relaxed_ex(predicted, gold, GOLD_UNORDERED)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_null_and_the_string_null_are_the_same_value() -> None:
    assert normalize_value(None) is None
    assert normalize_value("NULL") is None
    assert normalize_value("null") is None
    gold = [{"name": "a", "revenue": None}]
    predicted = [{"name": "a", "revenue": "NULL"}]
    assert strict_ex(predicted, gold, GOLD_UNORDERED)


def test_empty_string_is_not_null() -> None:
    """'' and NULL are different answers; conflating them would hide a real class of error."""
    assert normalize_value("") == ""
    assert normalize_value("") is not None


def test_decimal_equals_float() -> None:
    assert normalize_value(Decimal("1.50")) == normalize_value(1.5)
    gold = [{"name": "a", "revenue": Decimal("1234.56")}]
    predicted = [{"name": "a", "revenue": 1234.56}]
    assert strict_ex(predicted, gold, GOLD_UNORDERED)


def test_float_rounding_absorbs_driver_noise_but_not_real_differences() -> None:
    gold = [{"name": "a", "revenue": 1.000000001}]
    assert strict_ex([{"name": "a", "revenue": 1.0}], gold, GOLD_UNORDERED)
    assert not strict_ex([{"name": "a", "revenue": 1.01}], gold, GOLD_UNORDERED)


def test_int_and_float_and_numeric_string_agree() -> None:
    gold = [{"name": "a", "revenue": 1000}]
    assert strict_ex([{"name": "a", "revenue": 1000.0}], gold, GOLD_UNORDERED)
    assert strict_ex([{"name": "a", "revenue": "1000"}], gold, GOLD_UNORDERED)


def test_date_formats_are_canonicalised() -> None:
    assert normalize_value(date(2026, 6, 1)) == "2026-06-01"
    assert normalize_value("2026-06-01") == "2026-06-01"
    assert normalize_value(datetime(2026, 6, 1, 12, 30)) == "2026-06-01 12:30:00"
    assert normalize_value("2026-06-01 12:30:00.000000") == "2026-06-01 12:30:00"


def test_bool_and_int_agree() -> None:
    assert normalize_value(True) == normalize_value(1)


def test_canonical_name_folds_case_and_separators() -> None:
    assert canonical_name("Total Revenue") == "total_revenue"
    assert canonical_name('"totalRevenue"') == "totalrevenue"


# ---------------------------------------------------------------------------
# Row counts and empties
# ---------------------------------------------------------------------------


def test_row_count_mismatch_fails_both() -> None:
    gold = [{"name": "a", "revenue": 1}]
    predicted = [{"name": "a", "revenue": 1}, {"name": "a", "revenue": 1}]
    assert not strict_ex(predicted, gold, GOLD_UNORDERED)
    assert not relaxed_ex(predicted, gold, GOLD_UNORDERED)


def test_duplicate_rows_are_a_multiset_not_a_set() -> None:
    gold = [{"name": "a"}, {"name": "a"}]
    assert strict_ex([{"name": "a"}, {"name": "a"}], gold, "SELECT name FROM t")
    assert not strict_ex([{"name": "a"}], gold, "SELECT name FROM t")


def test_both_empty_matches() -> None:
    assert strict_ex([], [], GOLD_UNORDERED, predicted_columns=["name"], gold_columns=["name"])


# ---------------------------------------------------------------------------
# score_item reports both metrics plus the reason
# ---------------------------------------------------------------------------


def test_score_item_reports_both_metrics_and_the_mapping() -> None:
    gold = [{"name": "a", "revenue": 1}]
    predicted = [{"id": 9, "name": "a", "revenue": 1}]
    detail = score_item(predicted, gold, GOLD_UNORDERED)
    assert detail.strict is False
    assert detail.relaxed is True
    assert detail.column_mapping == {"name": "name", "revenue": "revenue"}
    assert detail.order_sensitive is False
    assert detail.reason
