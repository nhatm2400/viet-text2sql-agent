"""Verified few-shot example store. STUB — phase 2.

Two rules this store must enforce when it is built, because getting either wrong silently
inflates every number the project reports:

1. **No overlap with `core_vi`.** An example that is also an evaluation item turns execution
   accuracy into a memorisation test.
2. **Verified only.** Same bar as the eval set: every example's SQL is executed and reviewed
   before it can be retrieved. An unverified example teaches the model a wrong pattern.
"""

from __future__ import annotations

from dataclasses import dataclass

from t2sql.retrieval.store import Match

_NOT_YET = "example retrieval is phase 2 (ablation A3); the baseline uses a fixed 3-shot prompt"


@dataclass(frozen=True)
class Example:
    """One verified question -> SQL pair."""

    id: str
    question_vi: str
    question_en: str
    sql: str
    tags: list[str]


def index_examples(path: str | None = None) -> int:
    """Embed the verified example set into pgvector. Returns rows written."""
    raise NotImplementedError(f"index_examples: {_NOT_YET}")  # TODO(phase2)


def search(question: str, k: int = 3, exclude_ids: set[str] | None = None) -> list[Match]:
    """Top-k similar verified examples. `exclude_ids` guards against eval-set leakage."""
    raise NotImplementedError(f"search: {_NOT_YET}")  # TODO(phase2)
