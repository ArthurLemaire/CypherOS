"""Shared fixtures."""

from __future__ import annotations

import pytest

from dots import Dot, Goal
from dots.memory.inmemory import InMemoryMemory


@pytest.fixture
def memory() -> InMemoryMemory:
    return InMemoryMemory()


@pytest.fixture
def dot() -> Dot:
    return Dot(name="test", goal=Goal("do the thing whenever woken"))
