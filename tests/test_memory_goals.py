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


def test_memory_search_weighs_rare_words_over_common_ones(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    for city in ("Paris", "Rome", "Oslo", "Lima", "Cairo"):
        store.add(f"Likes the food in {city}")
    store.add("Likes the food in Kyoto, especially tofu")
    store.add("Sister lives in Kyoto")
    # "likes" and "food" are in six lines and say little; "kyoto" is in two and decides
    top = store.search("what does she like to eat in Kyoto", limit=2)
    assert top[0].content.startswith("Likes the food in Kyoto")
    assert {m.content for m in top} == {
        "Likes the food in Kyoto, especially tofu",
        "Sister lives in Kyoto",
    }
    # CJK: bigrams weighted the same way
    store.add("喜欢京都的豆腐料理")
    store.add("喜欢大阪的章鱼烧")
    assert store.search("京都 美食")[0].content == "喜欢京都的豆腐料理"


def test_memory_replace_drop_and_restore_are_logged(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    a = store.add("Prefers window seats", "preference")
    b = store.add("Likes a window seat on flights", "preference", source="user")
    c = store.add("Asked for the weather in Kyoto today")
    assert store.similar("Prefers a window seat")[0][1].id in (a.id, b.id)

    merged = store.replace([a.id, b.id], "Prefers window seats on flights", category="preference")
    assert merged is not None and merged.after is not None
    assert store.get(a.id) is None and store.get(b.id) is None
    assert merged.after.source == "user"  # the user wrote one of them
    assert merged.after.created_at == min(a.created_at, b.created_at)
    dropped = store.drop(c.id, reason="a one-off request")
    assert dropped is not None and store.count() == 1

    history = store.history()
    assert [h.action for h in history] == ["drop", "merge"]
    assert history[1].before[0].content in (
        "Prefers window seats",
        "Likes a window seat on flights",
    )

    # undo the merge: the two old lines come back, the merged one goes
    restored = store.restore(merged.id)
    assert restored is not None and restored.restored
    assert store.get(merged.after.id) is None
    assert {m.content for m in store.all()} == {
        "Prefers window seats",
        "Likes a window seat on flights",
    }
    assert store.restore(merged.id).restored  # a second time is a no-op
    assert store.restore("c_nope") is None

    # update() keeps the id, records when
    u = store.update(a.id, "Prefers window seats, aisle is fine on short flights")
    assert u is not None and u.id == a.id and u.updated_at
    assert store.get_meta("tidied_at") == "" and store.set_meta("tidied_at", "x") is None
    assert store.get_meta("tidied_at") == "x"
    store.close()


def test_memory_store_migrates_an_old_database(tmp_path: Path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, category TEXT NOT NULL "
        "DEFAULT 'general', created_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'agent')"
    )
    conn.execute(
        "INSERT INTO memories VALUES ('m_old', 'Old fact', 'profile', '2026-01-01T00:00:00+00:00', 'agent')"
    )
    conn.commit()
    conn.close()
    store = MemoryStore(path)
    assert store.get("m_old").updated_at == ""
    assert store.history() == []
    store.close()


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


def test_goal_categories_due_dates_and_check_ins(tmp_path: Path):
    from datetime import UTC, datetime, timedelta

    from openmuse.goals import next_check_in, parse_check_in

    store = GoalStore(tmp_path / "g.db")
    g = store.create(
        "Run a 10k",
        category="Health",
        due="2026-06-01",
        check_in="weekdays 07:30",
        steps=["Buy shoes", "Train"],
    )
    assert g.category == "health" and g.due == "2026-06-01" and g.overdue  # June 2026 is past
    assert g.check_in == "weekdays 07:30" and g.next_check_in
    when = datetime.fromisoformat(g.next_check_in).astimezone()
    assert (when.hour, when.minute) == (7, 30) and when.weekday() < 5
    assert "category=health" in g.render() and "OVERDUE" in g.render()
    # unknown categories are dropped, bad dates cleared, bad cadences refused
    assert store.create("x", category="vibes", due="soonish").category == ""
    assert store.get(store.create("y", due="2026-13-40").id).due == ""
    with pytest.raises(ValueError):
        store.create("z", check_in="whenever")
    # the reminder moves on after it fired
    now = datetime.now(UTC)
    assert store.due_check_ins(now + timedelta(days=8))[0].id == g.id
    assert store.due_check_ins(now - timedelta(days=1)) == []
    moved = store.mark_checked_in(g.id, now=when + timedelta(minutes=1))
    assert moved.next_check_in > g.next_check_in
    # clearing the cadence clears the schedule
    assert store.update(g.id, check_in="").next_check_in == ""
    assert store.update(g.id, due="", category="learning").category == "learning"
    assert store.list(category="learning")[0].id == g.id and store.list(category="health") == []
    # cadences
    assert parse_check_in("weekly mon 09:00") == ("weekly", 0, 9, 0)
    assert parse_check_in("monthly 15") == ("monthly", 15, 9, 0)
    assert parse_check_in("daily") == ("daily", None, 9, 0)
    assert parse_check_in("fortnightly") is None
    tz = datetime.now().astimezone().tzinfo
    base = datetime(2026, 9, 22, 12, 0, tzinfo=tz)  # a Tuesday
    assert next_check_in("daily 08:00", base) == datetime(2026, 9, 23, 8, 0, tzinfo=tz)
    assert next_check_in("daily 18:00", base) == datetime(2026, 9, 22, 18, 0, tzinfo=tz)
    assert next_check_in("weekly mon 09:00", base) == datetime(2026, 9, 28, 9, 0, tzinfo=tz)
    assert next_check_in("weekly 09:00", base) == datetime(2026, 9, 29, 9, 0, tzinfo=tz)
    friday_night = datetime(2026, 9, 25, 20, 0, tzinfo=tz)
    assert next_check_in("weekdays 07:30", friday_night) == datetime(2026, 9, 28, 7, 30, tzinfo=tz)
    assert next_check_in("monthly 1 09:00", base) == datetime(2026, 10, 1, 9, 0, tzinfo=tz)


def test_goal_proposals_are_the_users_call(tmp_path: Path):
    store = GoalStore(tmp_path / "g.db")
    g = store.create("Learn Spanish", steps=["Pick an app", "Daily lesson", "Book a tutor"])
    store.update_step(g.id, 1, status="done")
    with pytest.raises(ValueError):
        store.propose(g.id, "", ["x"])
    g = store.propose(g.id, "tutors are booked out until spring", ["Join a conversation group"])
    assert g.proposal["reason"].startswith("tutors") and g.proposal["steps"] == [
        "Join a conversation group"
    ]
    assert "proposal awaiting" in g.render()
    # declining keeps the plan and leaves a note
    kept = store.dismiss_proposal(g.id)
    assert kept.proposal is None and [s.title for s in kept.steps] == [
        "Pick an app",
        "Daily lesson",
        "Book a tutor",
    ]
    assert "kept the plan" in kept.notes
    # accepting keeps what is done and swaps the rest
    store.propose(g.id, "tutors are booked out", ["Join a conversation group", "Watch a series"])
    new = store.accept_proposal(g.id)
    assert new.proposal is None
    assert [(s.idx, s.title, s.status) for s in new.steps] == [
        (1, "Pick an app", "done"),
        (2, "Join a conversation group", "pending"),
        (3, "Watch a series", "pending"),
    ]
    assert "plan adjusted" in new.notes
    # a store from before these columns existed is upgraded in place
    store.close()
    import sqlite3

    legacy = tmp_path / "old.db"
    conn = sqlite3.connect(legacy)
    conn.executescript(
        """
        CREATE TABLE goals (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL);
        CREATE TABLE steps (id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, idx INTEGER NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
        INSERT INTO goals VALUES ('g_old', 'Old goal', '', 'active', '', '2026-01-01T00:00:00+00:00',
            '2026-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()
    old = GoalStore(legacy).get("g_old")
    assert old.category == "" and old.due == "" and old.proposal is None


def test_goal_categories_due_and_check_ins(tmp_path: Path):
    from datetime import UTC, datetime, timedelta

    from openmuse.goals import next_check_in, parse_check_in

    store = GoalStore(tmp_path / "g.db")
    g = store.create(
        "Run 3x a week",
        category="health",
        due="2020-01-01",
        check_in="weekly mon 07:30",
        steps=["Buy shoes"],
    )
    assert g.category == "health" and g.due == "2020-01-01" and g.overdue
    assert g.check_in == "weekly mon 07:30" and g.next_check_in
    assert "category=health" in g.render() and "OVERDUE" in g.render()
    # unknown categories and bad dates are dropped, not stored
    g2 = store.create("Misc", category="fishing", due="soon")
    assert g2.category == "" and g2.due == ""
    with pytest.raises(ValueError):
        store.create("Bad cadence", check_in="every so often")
    # list filters by category; update changes the goal's own fields and clears with ""
    assert [x.id for x in store.list(category="health")] == [g.id]
    g = store.update(g.id, category="finance", due="", check_in="")
    assert g.category == "finance" and g.due == "" and g.next_check_in == "" and not g.overdue

    # cadences
    tz = datetime.now().astimezone().tzinfo
    wed = datetime(2026, 9, 23, 12, 0, tzinfo=tz)  # a Wednesday, noon
    assert parse_check_in("weekly mon 09:00") == ("weekly", 0, 9, 0)
    assert parse_check_in("daily") == ("daily", None, 9, 0)
    assert parse_check_in("monthly 15 18:30") == ("monthly", 15, 18, 30)
    assert parse_check_in("fortnightly") is None
    assert next_check_in("daily 08:00", wed) == datetime(2026, 9, 24, 8, 0, tzinfo=tz)
    assert next_check_in("daily 18:00", wed) == datetime(2026, 9, 23, 18, 0, tzinfo=tz)
    assert next_check_in("weekdays 08:00", datetime(2026, 9, 25, 9, 0, tzinfo=tz)) == datetime(
        2026, 9, 28, 8, 0, tzinfo=tz
    )  # Friday after 08:00 -> Monday
    assert next_check_in("weekly mon 09:00", wed) == datetime(2026, 9, 28, 9, 0, tzinfo=tz)
    assert next_check_in("weekly", wed) == datetime(2026, 9, 30, 9, 0, tzinfo=tz)
    assert next_check_in("monthly 1 09:00", wed) == datetime(2026, 10, 1, 9, 0, tzinfo=tz)

    # due check-ins: one in the past is picked up, then moved to the next occurrence
    h = store.create("Meditate", check_in="daily 06:00")
    store._conn.execute(
        "UPDATE goals SET next_check_in = ? WHERE id = ?",
        ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds"), h.id),
    )
    store._conn.commit()
    assert [x.id for x in store.due_check_ins()] == [h.id]
    h = store.mark_checked_in(h.id)
    assert h.next_check_in > datetime.now(UTC).isoformat(timespec="seconds")
    assert store.due_check_ins() == []


def test_goal_proposals(tmp_path: Path):
    store = GoalStore(tmp_path / "g.db")
    g = store.create("Learn to swim", steps=["Find a pool", "Book lessons", "Swim 25 m"])
    store.update_step(g.id, 1, status="done")
    with pytest.raises(ValueError):
        store.propose(g.id, "", [])
    g = store.propose(g.id, "the pool closes in winter", ["Join the indoor gym", "Swim 25 m"])
    assert g.proposal["reason"] == "the pool closes in winter"
    assert "proposal awaiting" in g.render()
    # dismissing keeps the plan and notes the decision
    g = store.dismiss_proposal(g.id)
    assert g.proposal is None and [s.title for s in g.steps][1:] == ["Book lessons", "Swim 25 m"]
    assert "kept the plan" in g.notes
    # accepting keeps finished steps and swaps the rest
    store.propose(g.id, "lessons are full", ["Self-teach with videos", "Swim 25 m"])
    g = store.accept_proposal(g.id)
    assert g.proposal is None
    assert [(s.idx, s.title, s.status) for s in g.steps] == [
        (1, "Find a pool", "done"),
        (2, "Self-teach with videos", "pending"),
        (3, "Swim 25 m", "pending"),
    ]
    assert "plan adjusted: lessons are full" in g.notes


def test_goal_categories_due_dates_and_proposals(tmp_path: Path):
    store = GoalStore(tmp_path / "g.db")
    g = store.create(
        "Run a 10k",
        steps=["Buy shoes", "Train 3x a week", "Register"],
        category="health",
        due="2020-01-01",
    )
    assert g.category == "health" and g.due == "2020-01-01" and g.overdue
    assert "OVERDUE" in g.render()
    # unknown categories and unparseable dates are dropped rather than stored
    other = store.create("Misc", category="nonsense", due="someday")
    assert other.category == "" and other.due == "" and not other.overdue
    assert [x.id for x in store.list(category="health")] == [g.id]
    g = store.update(g.id, category="learning", due="", title="Run a 10k in spring")
    assert g.category == "learning" and g.due == "" and g.title == "Run a 10k in spring"

    # the agent suggests a new plan; nothing changes until the user says so
    store.update_step(g.id, 1, status="done")
    with pytest.raises(ValueError):
        store.propose(g.id, "", [])
    g = store.propose(
        g.id, "the race is full; aim for the autumn one", ["Find another race", "Train"]
    )
    assert g.proposal["steps"] == ["Find another race", "Train"]
    assert [s.title for s in g.steps] == ["Buy shoes", "Train 3x a week", "Register"]
    assert "proposal awaiting" in g.render()
    g = store.dismiss_proposal(g.id)
    assert g.proposal is None and "kept the plan" in g.notes
    g = store.propose(g.id, "race is full", ["Find another race", "Train"])
    g = store.accept_proposal(g.id)
    # finished steps stay, the open ones are replaced, numbering continues
    assert [(s.idx, s.title, s.status) for s in g.steps] == [
        (1, "Buy shoes", "done"),
        (2, "Find another race", "pending"),
        (3, "Train", "pending"),
    ]
    assert g.proposal is None and "plan adjusted" in g.notes
    store.close()


def test_goal_check_ins(tmp_path: Path):
    from datetime import UTC, datetime, timedelta

    from openmuse.goals import next_check_in, parse_check_in

    assert parse_check_in("daily 08:00") == ("daily", None, 8, 0)
    assert parse_check_in("weekly mon 09:30") == ("weekly", 0, 9, 30)
    assert parse_check_in("monthly 15") == ("monthly", 15, 9, 0)
    assert parse_check_in("weekdays") == ("weekdays", None, 9, 0)
    assert parse_check_in("every other tuesday") is None

    tz = datetime.now().astimezone().tzinfo
    # Wednesday 2026-01-07 10:00
    now = datetime(2026, 1, 7, 10, 0, tzinfo=tz)
    assert next_check_in("daily 08:00", now) == datetime(2026, 1, 8, 8, 0, tzinfo=tz)
    assert next_check_in("daily 12:00", now) == datetime(2026, 1, 7, 12, 0, tzinfo=tz)
    # Friday evening → Monday for weekdays
    friday = datetime(2026, 1, 9, 20, 0, tzinfo=tz)
    assert next_check_in("weekdays 07:30", friday) == datetime(2026, 1, 12, 7, 30, tzinfo=tz)
    assert next_check_in("weekly mon 09:00", now) == datetime(2026, 1, 12, 9, 0, tzinfo=tz)
    assert next_check_in("weekly", now) == datetime(2026, 1, 14, 9, 0, tzinfo=tz)  # same weekday
    assert next_check_in("monthly 1 09:00", now) == datetime(2026, 2, 1, 9, 0, tzinfo=tz)
    assert next_check_in("monthly 31", datetime(2026, 2, 1, tzinfo=tz)) == datetime(
        2026, 3, 31, 9, 0, tzinfo=tz
    )

    store = GoalStore(tmp_path / "g.db")
    with pytest.raises(ValueError):
        store.create("Walk", check_in="whenever")
    g = store.create("Walk every day", steps=["Walk"], category="health", check_in="daily 08:00")
    assert g.next_check_in and datetime.fromisoformat(g.next_check_in) > datetime.now(UTC)
    assert store.due_check_ins() == []
    # a reminder whose time has come is due; marking it moves it to the next occurrence
    later = datetime.now(UTC) + timedelta(days=2)
    assert [x.id for x in store.due_check_ins(later)] == [g.id]
    g = store.mark_checked_in(g.id, later)
    assert datetime.fromisoformat(g.next_check_in) > later
    # paused goals do not nag
    store.set_status(g.id, "paused")
    assert store.due_check_ins(later + timedelta(days=5)) == []
    g = store.update(g.id, check_in="")
    assert g.check_in == "" and g.next_check_in == ""
    store.close()


def test_goal_store_upgrades_an_old_database(tmp_path: Path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE goals (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL);
        CREATE TABLE steps (id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, idx INTEGER NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
        INSERT INTO goals VALUES ('g_old', 'Old goal', '', 'active', '', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
        INSERT INTO steps VALUES ('s_old', 'g_old', 1, 'Step', 'pending', '', '2026-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()
    store = GoalStore(path)
    g = store.get("g_old")
    assert (
        g
        and g.category == ""
        and g.due == ""
        and g.proposal is None
        and g.next_step.title == "Step"
    )
    assert store.update(g.id, category="finance").category == "finance"
    store.close()
