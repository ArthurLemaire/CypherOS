"""Pluggable memory backends behind a single protocol."""

from __future__ import annotations

from dots.memory.base import Memory, MemoryRecord
from dots.memory.inmemory import InMemoryMemory
from dots.memory.sqlite import SqliteMemory

__all__ = ["InMemoryMemory", "Memory", "MemoryRecord", "SqliteMemory"]


def default_memory() -> Memory:
    """Return the zero-config backend (in-memory)."""
    return InMemoryMemory()
