"""`lookup_glossary` — Vietnamese business term → schema mapping.

Phase-1 behaviour: exact and alias lookup against `db/glossary.yaml`, plus a diacritics-folded
comparison so "doanh so" finds "doanh số". Nothing fuzzy, nothing embedded, nothing ranked.

Fuzzy/semantic matching is deliberately deferred: an approximate match on a metric definition
produces a query that runs, returns a number, and is quietly wrong — the worst possible failure
mode for this project. Phase 2 wires this to pgvector (see retrieval/glossary.py) and measures
the change instead of assuming it helps.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import tool

from t2sql.config import get_settings
from t2sql.tools import ToolResult, ok


def fold(text: str) -> str:
    """Lowercase and strip diacritics — 'Miền Nam' and 'mien nam' fold to the same key."""
    decomposed = unicodedata.normalize("NFD", (text or "").strip().lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").replace("đ", "d")


@lru_cache(maxsize=2)
def load_glossary(path: str | None = None) -> dict[str, dict[str, Any]]:
    """`{term: entry}` for every entry in glossary.yaml, TODO stubs included."""
    target = Path(path) if path else get_settings().glossary_path
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return raw.get("terms", {})


@lru_cache(maxsize=2)
def _alias_index(path: str | None = None) -> dict[str, str]:
    index: dict[str, str] = {}
    for term, entry in load_glossary(path).items():
        index[fold(term)] = term
        for alias in (entry or {}).get("aliases", []) or []:
            index[fold(alias)] = term
    return index


def completed_terms() -> dict[str, dict[str, Any]]:
    """Only the verified entries — what the system prompt is allowed to assert as fact."""
    return {t: e for t, e in load_glossary().items() if (e or {}).get("status") == "done"}


def glossary_block() -> str:
    """Prompt rendering of the verified terms. TODO entries are not shown: an unverified
    mapping in the prompt is worse than no mapping, because the agent will trust it."""
    lines = []
    for term, entry in completed_terms().items():
        definition = " ".join((entry.get("definition") or "").split())
        lines.append(f"- {term}: {definition}")
        if fragment := entry.get("sql_fragment"):
            lines.append(f"    SQL: {' '.join(fragment.split())}")
    return "\n".join(lines)


def lookup(term: str) -> ToolResult:
    entries = load_glossary()
    canonical = _alias_index().get(fold(term))
    if canonical is None:
        known = ", ".join(sorted(completed_terms()))
        return ToolResult(
            status="ok",
            message=f"no glossary entry for {term!r}. Verified terms: {known}",
            data={"term": term, "found": False},
        )

    entry = entries.get(canonical) or {}
    if entry.get("status") != "done":
        return ToolResult(
            status="ok",
            message=(
                f"{canonical!r} is a known term but its mapping is not verified yet "
                "— do not guess it; ask the user what they mean."
            ),
            data={"term": canonical, "found": True, "verified": False},
        )
    return ok(
        f"glossary: {canonical}",
        term=canonical,
        found=True,
        verified=True,
        maps_to=entry.get("maps_to", []),
        sql_fragment=" ".join((entry.get("sql_fragment") or "").split()),
        definition=" ".join((entry.get("definition") or "").split()),
    )


@tool
def lookup_glossary(term: str) -> dict:
    """Resolve a Vietnamese business term to the exact columns and SQL expression that define it.

    Call this before writing SQL for any business metric ("doanh thu", "quý trước", "miền Nam",
    "khách hàng active"). These terms do NOT map to the obvious column — "doanh thu" is
    payments.amount where status='succeeded', not orders.total_amount.

    If the term is known but unverified, do not guess: use ask_clarification instead.

    Args:
        term: the Vietnamese (or English) term, e.g. "doanh thu". Diacritics optional.
    """
    return lookup(term).to_dict()
