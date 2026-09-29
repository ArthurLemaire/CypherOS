"""A zero-dependency in-memory backend with keyword-overlap recall."""

from __future__ import annotations

import re

from dots.memory.base import Memory, MemoryRecord

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


class InMemoryMemory(Memory):
    """Keeps records in a list. Recall ranks by Jaccard token overlap.

    Good enough for tests, demos, and short-lived dots. For anything that must
    survive a restart, use :class:`~dots.memory.sqlite.SqliteMemory`.
    """

    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []

    async def remember(self, text: str, *, tags: list[str] | None = None) -> MemoryRecord:
        record = MemoryRecord(text=text, tags=tags or [])
        self._records.append(record)
        return record

    async def recall(self, query: str, *, k: int = 5) -> list[MemoryRecord]:
        q = _tokens(query)
        if not q:
            return await self.all()

        scored: list[MemoryRecord] = []
        for record in self._records:
            r = _tokens(record.text)
            union = q | r
            overlap = len(q & r) / len(union) if union else 0.0
            if overlap > 0:
                scored.append(record.model_copy(update={"score": overlap}))

        scored.sort(key=lambda rec: (rec.score or 0.0), reverse=True)
        return scored[:k]

    async def all(self) -> list[MemoryRecord]:
        return list(reversed(self._records))

    async def clear(self) -> None:
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)
