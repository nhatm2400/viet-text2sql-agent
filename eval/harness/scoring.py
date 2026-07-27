"""Strict and relaxed execution accuracy.

Pure functions over result sets: no database, no LLM, no network. That is deliberate — the
scoring rule is the part of this project that every reported number depends on, so it has to be
the part that is easiest to test and hardest to accidentally change. See tests/test_scoring.py.

The published rule (README, "How we score"):

1. Execute predicted and gold SQL on the same immutable snapshot.
2. Normalise scalars: floats rounded, Decimal == float, dates canonicalised, NULL vs "NULL".
3. Ignore row order UNLESS the gold SQL has a top-level ORDER BY.
4. strict_ex : exact multiset match, column order enforced, no extra columns.
   relaxed_ex: extra predicted columns tolerated; gold columns matched by canonical name, and
               failing that by value.
5. Both are recorded for every item. They disagree often, and the disagreements are the
   interesting part — a strict miss with a relaxed hit is usually a projection difference, not a
   wrong query.

Known limitation, stated in the README as well: execution accuracy has false positives (a wrong
query that happens to agree on this snapshot) and false negatives. Reporting both numbers bounds
that; it does not remove it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from itertools import permutations
from typing import Any

import sqlglot
from sqlglot import exp

FLOAT_PLACES = 4
MAX_PERMUTATION_COLUMNS = 8
"""Above this arity the relaxed matcher stops trying every column assignment (8! = 40320 is the
last comfortable size) and falls back to name-based matching only. Recorded in the result so a
fallback is never mistaken for a real match."""

_NULL_STRINGS = {"null", "none", "nan", "<null>"}
_DATETIME_PATTERNS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y",
)
_DATEISH = re.compile(r"^\d{4}-\d{2}-\d{2}|^\d{2}/\d{2}/\d{4}")


# ---------------------------------------------------------------------------
# Result sets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultSet:
    """A query result: ordered column names plus rows as tuples in that column order."""

    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)

    @property
    def arity(self) -> int:
        return len(self.columns)


def as_result_set(rows: Any, columns: list[str] | None = None) -> ResultSet:
    """Coerce the shapes the harness actually sees into a ResultSet.

    Accepts: a ResultSet, a list of dicts (what execute_sql returns), or a list of
    tuples/lists plus an explicit `columns`.
    """
    if isinstance(rows, ResultSet):
        return rows
    rows = list(rows or [])
    if not rows:
        return ResultSet(columns=list(columns or []), rows=[])
    if isinstance(rows[0], dict):
        cols = list(columns) if columns else list(rows[0].keys())
        return ResultSet(columns=cols, rows=[tuple(r.get(c) for c in cols) for r in rows])
    cols = list(columns) if columns else [f"col{i}" for i in range(len(rows[0]))]
    return ResultSet(columns=cols, rows=[tuple(r) for r in rows])


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def canonical_name(name: str) -> str:
    """Column-name canonicalisation for relaxed matching: case, quotes and separators folded."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(name).strip().strip('"').lower())
    return cleaned.strip("_")


def normalize_value(value: Any, float_places: int = FLOAT_PLACES) -> Any:
    """Make two equivalent scalars from two different drivers compare equal.

    Handles the differences this project actually hits: Decimal vs float (psycopg vs sqlite3),
    NULL vs the string "NULL", bool vs 0/1, and four different date renderings.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, (int,)):
        return float(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return round(value, float_places)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)

    text = str(value).strip()
    if text.lower() in _NULL_STRINGS or text == "":
        return None if text.lower() in _NULL_STRINGS else ""
    if _DATEISH.match(text):
        for pattern in _DATETIME_PATTERNS:
            try:
                parsed = datetime.strptime(text, pattern)
            except ValueError:
                continue
            has_time = parsed.time() != datetime.min.time() or "%H" in pattern
            return parsed.strftime("%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d")
    try:  # numeric strings: "1000" and 1000 are the same answer
        return round(float(text), float_places)
    except ValueError:
        return text


def normalize_rows(result: ResultSet, float_places: int = FLOAT_PLACES) -> list[tuple[Any, ...]]:
    return [tuple(normalize_value(v, float_places) for v in row) for row in result.rows]


def _multiset(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Order-insensitive canonical form. Sorted by repr because rows mix types and None."""
    return sorted(rows, key=repr)


# ---------------------------------------------------------------------------
# ORDER BY detection
# ---------------------------------------------------------------------------


def has_top_level_order_by(sql: str) -> bool:
    """True when the gold query's OUTERMOST statement has an ORDER BY.

    An ORDER BY inside a CTE or subquery does not make row order part of the answer, so it must
    not make the comparison order-sensitive — that would fail correct predictions.
    """
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return False
    if tree is None:
        return False
    if isinstance(tree, exp.Subquery):
        tree = tree.this
    return tree.args.get("order") is not None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreDetail:
    """Why an item scored the way it did — this is what makes an error taxonomy possible."""

    strict: bool
    relaxed: bool
    order_sensitive: bool
    reason: str = ""
    column_mapping: dict[str, str] = field(default_factory=dict)


def strict_ex(
    predicted: Any,
    gold: Any,
    gold_sql: str = "",
    *,
    predicted_columns: list[str] | None = None,
    gold_columns: list[str] | None = None,
    float_places: int = FLOAT_PLACES,
) -> bool:
    """Exact match: same arity, same column order, same rows. Row order enforced only when the
    gold SQL has a top-level ORDER BY."""
    pred = as_result_set(predicted, predicted_columns)
    ref = as_result_set(gold, gold_columns)

    if pred.arity != ref.arity:
        return False
    pred_rows = normalize_rows(pred, float_places)
    gold_rows = normalize_rows(ref, float_places)
    if len(pred_rows) != len(gold_rows):
        return False
    if has_top_level_order_by(gold_sql):
        return pred_rows == gold_rows
    return _multiset(pred_rows) == _multiset(gold_rows)


def relaxed_ex(
    predicted: Any,
    gold: Any,
    gold_sql: str = "",
    *,
    predicted_columns: list[str] | None = None,
    gold_columns: list[str] | None = None,
    float_places: int = FLOAT_PLACES,
) -> bool:
    """Tolerant match: extra predicted columns are ignored, and gold columns are matched to
    predicted columns by canonical name first, by value second."""
    return relaxed_detail(
        predicted,
        gold,
        gold_sql,
        predicted_columns=predicted_columns,
        gold_columns=gold_columns,
        float_places=float_places,
    )[0]


def relaxed_detail(
    predicted: Any,
    gold: Any,
    gold_sql: str = "",
    *,
    predicted_columns: list[str] | None = None,
    gold_columns: list[str] | None = None,
    float_places: int = FLOAT_PLACES,
) -> tuple[bool, dict[str, str], str]:
    """`relaxed_ex` plus the column mapping it found and a one-line reason."""
    pred = as_result_set(predicted, predicted_columns)
    ref = as_result_set(gold, gold_columns)

    if ref.arity == 0:
        return (pred.arity == 0 and not pred.rows, {}, "gold result set is empty")
    if pred.arity < ref.arity:
        return (False, {}, f"predicted has {pred.arity} columns, gold needs {ref.arity}")

    pred_rows = normalize_rows(pred, float_places)
    gold_rows = normalize_rows(ref, float_places)
    if len(pred_rows) != len(gold_rows):
        return (False, {}, f"row count {len(pred_rows)} != {len(gold_rows)}")

    ordered = has_top_level_order_by(gold_sql)

    def matches(indices: tuple[int, ...]) -> bool:
        projected = [tuple(row[i] for i in indices) for row in pred_rows]
        return projected == gold_rows if ordered else _multiset(projected) == _multiset(gold_rows)

    def report(indices: tuple[int, ...], how: str) -> tuple[bool, dict[str, str], str]:
        return (True, {ref.columns[g]: pred.columns[p] for g, p in enumerate(indices)}, how)

    # 1. Name-based mapping — the common, cheap case.
    pred_names = [canonical_name(c) for c in pred.columns]
    gold_names = [canonical_name(c) for c in ref.columns]
    by_name: list[int] = []
    used: set[int] = set()
    for name in gold_names:
        candidates = [i for i, n in enumerate(pred_names) if n == name and i not in used]
        if not candidates:
            by_name = []
            break
        by_name.append(candidates[0])
        used.add(candidates[0])
    if by_name and matches(tuple(by_name)):
        return report(tuple(by_name), "matched by column name")

    # 2. Positional prefix — the second-most-common shape (extra columns appended at the end).
    identity = tuple(range(ref.arity))
    if matches(identity):
        return report(identity, "matched by position")

    # 3. Value-based assignment. Bounded: see MAX_PERMUTATION_COLUMNS.
    if pred.arity > MAX_PERMUTATION_COLUMNS:
        return (
            False,
            {},
            f"no match; value search skipped above {MAX_PERMUTATION_COLUMNS} columns",
        )
    for indices in permutations(range(pred.arity), ref.arity):
        if matches(indices):
            return report(indices, "matched by value")

    return (False, {}, "no column assignment reproduces the gold rows")


def score_item(
    predicted: Any,
    gold: Any,
    gold_sql: str = "",
    *,
    predicted_columns: list[str] | None = None,
    gold_columns: list[str] | None = None,
    float_places: int = FLOAT_PLACES,
) -> ScoreDetail:
    """Score one item on both metrics in a single pass. This is what the runner calls."""
    kwargs = {
        "predicted_columns": predicted_columns,
        "gold_columns": gold_columns,
        "float_places": float_places,
    }
    strict = strict_ex(predicted, gold, gold_sql, **kwargs)
    relaxed, mapping, reason = relaxed_detail(predicted, gold, gold_sql, **kwargs)
    return ScoreDetail(
        strict=strict,
        relaxed=relaxed,
        order_sensitive=has_top_level_order_by(gold_sql),
        reason=reason if not strict else "exact match",
        column_mapping=mapping,
    )
