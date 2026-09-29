from __future__ import annotations

from dots import Dot, Event, Goal


async def test_step_records_diary(dot: Dot) -> None:
    await dot.step(Event.tick())
    diary = dot.diary()
    assert any("created" in line for line in diary)
    assert any("note" in line for line in diary)


async def test_pause_blocks_stepping(dot: Dot) -> None:
    dot.pause()
    result = await dot.step(Event.tick())
    assert not result.acted
    assert dot.state.paused


async def test_resume_reenables(dot: Dot) -> None:
    dot.pause()
    dot.resume()
    result = await dot.step(Event.manual("go"))
    assert result.acted


async def test_memory_accumulates(dot: Dot) -> None:
    await dot.step(Event.manual("one"))
    await dot.step(Event.manual("two"))
    records = await dot.memory.all()
    assert len(records) >= 2


async def test_goal_from_string_is_wrapped() -> None:
    d = Dot(name="x", goal="just do it")
    assert isinstance(d.goal, Goal)
    assert d.goal.objective == "just do it"
