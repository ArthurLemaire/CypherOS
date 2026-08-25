from __future__ import annotations

from pathlib import Path

import pytest

from openmuse.goals import GoalStore
from openmuse.memory import MemoryStore
from openmuse.memory.store import tokenize


def test_tokenize_mixed():
    tokens = tokenize("I prefer 靠窗 seats on flights")
    assert "prefer" in tokens and "seats" in tokens and "靠窗" in tokens


def test_memory_add_search_forget(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    a = store.add("Prefers window seats on flights", "preference")
    store.add("伴侣是素食主义者，不吃肉", "contact")
    store.add("Works at Acme in Shanghai, timezone UTC+8", "profile")
    assert store.count() == 3
    # exact duplicate is ignored
    assert store.add("Prefers window seats on flights").id == a.id
    assert store.search("window seat")[0].id == a.id
    assert "素食" in store.search("素食")[0].content
    assert store.forget(a.id) and not store.forget(a.id)
    assert store.forget_matching("Acme") == 1
    assert store.count() == 1
    store.close()


def test_memory_relevant_prefers_matches(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    for i in range(30):
        store.add(f"fact number {i}")
    store.add("Loves hiking in the Alps")
    rel = store.relevant("plan a hiking trip", limit=5)
    assert rel[0].content == "Loves hiking in the Alps"
    assert len(rel) == 5


def test_goals_lifecycle(tmp_path: Path):
    store = GoalStore(tmp_path / "g.db")
    goal = store.create(
        "Sell my old car", "Get at least 8000", ["Take photos", "Post listing", "Handle buyers"]
    )
    assert goal.status == "active" and goal.progress == "0/3"
    assert goal.next_step.title == "Take photos"
    goal = store.update_step(goal.id, 1, status="done", note="12 photos")
    assert goal.progress == "1/3" and goal.next_step.idx == 2
    store.append_note(goal.id, "buyer asked for inspection")
    goal = store.add_step(goal.id, "Transfer title")
    assert len(goal.steps) == 4
    with pytest.raises(ValueError):
        store.update_step(goal.id, 99, status="done")
    for idx in (2, 3, 4):
        goal = store.update_step(goal.id, idx, status="done")
    assert goal.status == "done"  # auto-completed
    assert store.list("done")[0].id == goal.id
    rendered = goal.render()
    assert "[x] 1. Take photos" in rendered and "buyer asked" in rendered
    assert store.delete(goal.id) and store.get(goal.id) is None
