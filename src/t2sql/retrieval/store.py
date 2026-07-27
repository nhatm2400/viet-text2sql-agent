"""pgvector store interface. STUB — phase 2.

Embedding shortlist for the retrieval experiments (proposal §8): BGE-M3, multilingual-e5,
Cohere Embed Multilingual v3. The choice is an experiment variable, so it is a constructor
argument here rather than a hardcoded model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_NOT_YET = (
    "pgvector retrieval is phase 2. This build answers from the full schema and the verified "
    "glossary; see docs/DECISIONS.md for why it is not approximated in the meantime."
)


@dataclass(frozen=True)
class Match:
    """One retrieved item plus its similarity score."""

    id: str
    text: str
    score: float
    metadata: dict[str, Any]


class VectorStore:
    """Thin wrapper over a pgvector table. Nothing here is implemented yet."""

    def __init__(self, table: str, embedding_model: str = "BAAI/bge-m3", dim: int = 1024) -> None:
        self.table = table
        self.embedding_model = embedding_model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed `texts` with `self.embedding_model`."""
        raise NotImplementedError(f"VectorStore.embed: {_NOT_YET}")  # TODO(phase2)

    def upsert(self, ids: list[str], texts: list[str], metadata: list[dict[str, Any]]) -> int:
        """Insert or update rows, returning the number written."""
        raise NotImplementedError(f"VectorStore.upsert: {_NOT_YET}")  # TODO(phase2)

    def search(self, query: str, k: int = 5, threshold: float = 0.0) -> list[Match]:
        """Top-k nearest neighbours above `threshold`, most similar first."""
        raise NotImplementedError(f"VectorStore.search: {_NOT_YET}")  # TODO(phase2)
