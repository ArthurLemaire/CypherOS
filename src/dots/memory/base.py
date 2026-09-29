"""The memory protocol every backend implements."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """One remembered fact."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    text: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    score: float | None = None  # populated by ranked recall


@runtime_checkable
class Memory(Protocol):
    """Append + recall. Backends may add persistence or vector search."""

    async def remember(self, text: str, *, tags: list[str] | None = None) -> MemoryRecord:
        """Store a fact and return the created record."""
        ...

    async def recall(self, query: str, *, k: int = 5) -> list[MemoryRecord]:
        """Return up to ``k`` records most relevant to ``query``."""
        ...

    async def all(self) -> list[MemoryRecord]:
        """Return every stored record (newest first)."""
        ...

    async def clear(self) -> None:
        """Drop everything."""
        ...
