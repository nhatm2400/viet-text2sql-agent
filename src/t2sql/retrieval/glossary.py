"""Semantic glossary lookup. STUB — phase 2.

Phase 1 does exact + alias + diacritics-folded matching in `tools/glossary_tools.py`, which is
enough for the 18 terms in `db/glossary.yaml` and has no false-positive mode. Semantic matching
is what makes "khách VIP mua nhiều" resolve to a term nobody spelled out — and also what makes a
near-miss silently return the wrong metric definition. It ships when it can be measured.
"""

from __future__ import annotations

from t2sql.retrieval.store import Match

_NOT_YET = "semantic glossary lookup is phase 2; use tools.glossary_tools.lookup for exact matching"


def index_glossary(path: str | None = None) -> int:
    """Embed every verified glossary entry into pgvector. Returns rows written."""
    raise NotImplementedError(f"index_glossary: {_NOT_YET}")  # TODO(phase2)


def search_terms(question: str, k: int = 3) -> list[Match]:
    """Return the glossary terms most likely to be implied by `question`."""
    raise NotImplementedError(f"search_terms: {_NOT_YET}")  # TODO(phase2)


def resolve_time_expression(phrase: str, as_of: str) -> tuple[str, str]:
    """Resolve a Vietnamese relative-time phrase to a concrete [start, end) window.

    E.g. ("quý trước", "2026-07-27") -> ("2026-04-01", "2026-07-01").

    Explicitly out of scope for the scaffold. The hard part is not parsing "quý trước" — it is
    that fiscal quarters, "tháng này" mid-month, and "cùng kỳ năm ngoái" all need an agreed
    convention with the business before any of them can be called correct.
    """
    raise NotImplementedError(  # TODO(phase2)
        "Vietnamese time-expression resolution is phase 2. For now the agent must either read the "
        "window from the question or call ask_clarification."
    )
