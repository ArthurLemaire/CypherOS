from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openmuse.reminders import ReminderStore, parse_when
from openmuse.tools import Reminders


def test_parse_when_reads_what_the_model_writes():
    tz = datetime.now().astimezone().tzinfo
    assert parse_when("2026-09-23 18:00") == datetime(2026, 9, 23, 18, 0, tzinfo=tz)
    assert parse_when("2026-09-23T18:00") == datetime(2026, 9, 23, 18, 0, tzinfo=tz)
    assert parse_when("2026-09-23 18:00:30") == datetime(2026, 9, 23, 18, 0, 30, tzinfo=tz)
    # an explicit offset is kept
    assert parse_when("2026-09-23T18:00:00+02:00").utcoffset() == timedelta(hours=2)
    assert parse_when("tomorrow at six") is None
    assert parse_when("") is None


def test_reminders_fire_once_and_routines_repeat(tmp_path: Path):
    store = ReminderStore(tmp_path / "r.db")
    with pytest.raises(ValueError):
        store.create("call mum", at="yesterday")
    with pytest.raises(ValueError):
        store.create("call mum", at="2020-01-01 10:00")  # in the past
    with pytest.raises(ValueError):
        store.create("standup", repeat="every other tuesday")
    with pytest.raises(ValueError):
        store.create("   ", at="2999-01-01 10:00")

    soon = (datetime.now().astimezone() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
    once = store.create("call mum", at=soon, thread="t_1")
    assert once.kind == "remind" and once.status == "active" and not once.repeating
    assert once.thread == "t_1"
    assert datetime.fromisoformat(once.next_at) > datetime.now(UTC)
    assert store.due() == []
    later = datetime.now(UTC) + timedelta(minutes=10)
    assert [r.id for r in store.due(later)] == [once.id]
    fired = store.mark_fired(once.id, later)
    assert fired.status == "done" and fired.next_at == "" and fired.fired == 1
    assert store.due(later + timedelta(days=1)) == []
    # a finished one-off shows in the full list, not the active one
    assert store.list("active") == []
    assert [r.id for r in store.list(None)] == [once.id]
    assert store.mark_fired(once.id) is None  # already done

    routine = store.create("summarise unread email", repeat="daily 08:00", kind="task")
    assert routine.repeating and routine.kind == "task"
    first = datetime.fromisoformat(routine.next_at)
    fired = store.mark_fired(routine.id, first + timedelta(seconds=30))
    assert fired.status == "active" and fired.fired == 1
    assert datetime.fromisoformat(fired.next_at) - first == timedelta(days=1)
    # "at" is ignored for routines: the cadence decides
    weekly = store.create("weekly review", at="2020-01-01 10:00", repeat="weekly mon 09:00")
    assert datetime.fromisoformat(weekly.next_at).astimezone().weekday() == 0

    # cancel: only active items, and never twice
    cancelled = store.cancel(routine.id)
    assert cancelled.status == "cancelled" and cancelled.next_at == ""
    assert store.cancel(routine.id) is None
    assert store.cancel("r_nope") is None
    assert [r.id for r in store.list("active")] == [weekly.id]
    assert store.delete(weekly.id) and store.get(weekly.id) is None
    assert store.list("active") == []
    assert once.render().startswith(f"[{once.id}] ") and "call mum" in once.render()
    store.close()


def test_reminders_tool(tmp_path: Path):
    store = ReminderStore(tmp_path / "r.db")
    changes: list[int] = []
    tool = Reminders(store=store)
    tool.thread_of = lambda: "t_9"
    tool.on_change = lambda: changes.append(1)

    run = asyncio.run
    r = run(tool.execute(action="create", text="call mum"))
    assert not r.ok and "at" in (r.error or "")
    r = run(tool.execute(action="create", text="call mum", at="not a time"))
    assert not r.ok and "could not read" in (r.error or "")

    soon = (datetime.now().astimezone() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    r = run(tool.execute(action="create", text="call mum", at=soon))
    assert r.ok and r.output.startswith("Reminder set.") and changes == [1]
    item = store.list("active")[0]
    assert item.thread == "t_9" and item.kind == "remind"

    r = run(
        tool.execute(action="create", text="check the weather", repeat="daily 07:00", kind="task")
    )
    assert r.ok and r.output.startswith("Routine set.")
    r = run(tool.execute(action="list"))
    assert "call mum" in r.output and "daily 07:00" in r.output
    r = run(tool.execute(action="cancel", reminder_id=item.id))
    assert r.ok and r.output.startswith("Cancelled.") and len(changes) == 3
    r = run(tool.execute(action="cancel", reminder_id=item.id))
    assert not r.ok
    assert tool.assess({"action": "create", "text": "call mum", "at": soon}).summary.startswith(
        f"reminders create: {soon}"
    )
    store.close()
