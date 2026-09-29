"""A vector-recall backend (optional ``[vector]`` extra).

Embeddings are pluggable: pass any callable ``str -> list[float]``. The default
is a tiny hashing embedder so the backend works with no model and no network,
which keeps tests fast; swap in a real embedder for production.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from dots.memory.base import Memory, MemoryRecord

Embedder = Callable[[str], list[float]]


def hashing_embedder(dim: int = 256) -> Embedder:
    """A deterministic bag-of-words hashing embedder (no dependencies)."""

    def embed(text: str) -> list[float]:
        vec = [0.0] * dim
        for token in text.lower().split():
            vec[hash(token) % dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    return embed


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class VectorMemory(Memory):
    """Cosine-similarity recall over stored embeddings."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embed = embedder or hashing_embedder()
        self._records: list[MemoryRecord] = []
        self._vectors: dict[str, list[float]] = {}

    async def remember(self, text: str, *, tags: list[str] | None = None) -> MemoryRecord:
        record = MemoryRecord(text=text, tags=tags or [])
        self._records.append(record)
        self._vectors[record.id] = self._embed(text)
        return record

    async def recall(self, query: str, *, k: int = 5) -> list[MemoryRecord]:
        q = self._embed(query)
        scored = [
            record.model_copy(update={"score": _cosine(q, self._vectors[record.id])})
            for record in self._records
        ]
        scored.sort(key=lambda rec: (rec.score or 0.0), reverse=True)
        return scored[:k]

    async def all(self) -> list[MemoryRecord]:
        return list(reversed(self._records))

    async def clear(self) -> None:
        self._records.clear()
        self._vectors.clear()
