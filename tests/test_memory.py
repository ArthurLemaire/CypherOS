from __future__ import annotations

import pytest

from dots.memory.inmemory import InMemoryMemory
from dots.memory.sqlite import SqliteMemory
from dots.memory.vector import VectorMemory


@pytest.fixture(params=["inmemory", "sqlite", "vector"])
async def backend(request, tmp_path):
    if request.param == "inmemory":
        yield InMemoryMemory()
    elif request.param == "vector":
        yield VectorMemory()
    else:
        mem = SqliteMemory(tmp_path / "m.db")
        yield mem
        mem.close()


async def test_remember_and_all(backend) -> None:
    await backend.remember("lithium supply tightened in Q3", tags=["news"])
    await backend.remember("cobalt prices flat", tags=["news"])
    records = await backend.all()
    assert len(records) == 2
    assert {r.text for r in records} == {
        "lithium supply tightened in Q3",
        "cobalt prices flat",
    }


async def test_recall_ranks_relevant_first(backend) -> None:
    await backend.remember("lithium supply tightened in Q3")
    await backend.remember("weather is sunny today")
    hits = await backend.recall("lithium supply", k=1)
    assert hits
    assert "lithium" in hits[0].text


async def test_clear(backend) -> None:
    await backend.remember("something")
    await backend.clear()
    assert await backend.all() == []
