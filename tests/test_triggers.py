from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openmuse.tools import Triggers
from openmuse.triggers import TriggerStore, matches


def test_matches_needs_every_word_anywhere():
    assert matches("", "anything")
    assert matches("landlord", "From: The Landlord <l@x.io>", "Subject: rent")
    assert matches("landlord rent", "The Landlord", "about the RENT")
    assert not matches("landlord rent", "The Landlord", "about the flat")
    assert matches("房东", "房东 <fd@example.cn>", "本月房租")
    assert matches("  Review   ", "Design review")


def test_store_creates_fires_once_per_key_and_cancels(tmp_path: Path):
    store = TriggerStore(tmp_path / "t.db")
    with pytest.raises(ValueError):
        store.create("sms", "x")
    with pytest.raises(ValueError):
        store.create("mail", "   ")
    with pytest.raises(ValueError):
        store.create("event", "brief me", lead_minutes=99999)

    mail = store.create(
        "mail", "summarise it and draft a reply", match=" landlord  rent ", thread="t_1"
    )
    assert mail.kind == "mail" and mail.match == "landlord rent" and mail.thread == "t_1"
    assert (
        mail.status == "active" and mail.fired == 0 and mail.secret == "" and mail.lead_minutes == 0
    )
    assert mail.describe() == "mail matching “landlord rent”"

    event = store.create("event", "put together a one-page brief", match="review", lead_minutes=45)
    assert event.lead_minutes == 45 and event.describe() == "45 min before events matching “review”"
    assert store.create("event", "x").describe() == "30 min before any event"

    hook = store.create("hook", "check the site is up", match="deploy")
    assert len(hook.secret) >= 20 and hook.to_dict()["secret"] == hook.secret
    assert mail.to_dict()["secret"] == ""  # only a hook has a key
    assert hook.describe() == "webhook “deploy”"

    # a key fires once
    assert store.mark_fired(mail.id, "uid:41")
    assert not store.mark_fired(mail.id, "uid:41")
    assert store.mark_fired(mail.id, "uid:42")
    assert store.has_fired(mail.id, "uid:41") and not store.has_fired(mail.id, "uid:43")
    got = store.get(mail.id)
    assert got is not None and got.fired == 2 and got.last_fired_at
    assert store.forget_fired_before("2999-01-01T00:00:00+00:00") == 2
    assert not store.has_fired(mail.id, "uid:41")

    assert [t.id for t in store.active("mail")] == [mail.id]
    assert len(store.list("active")) == 4
    cancelled = store.cancel(event.id)
    assert cancelled is not None and cancelled.status == "cancelled"
    assert store.cancel(event.id) is None and store.cancel("t_nope") is None
    assert [t.id for t in store.active("event")] != [event.id]
    assert store.delete(hook.id) and store.get(hook.id) is None
    assert store.get_meta("mail_uid", "0") == "0"
    store.set_meta("mail_uid", "77")
    store.set_meta("mail_uid", "78")
    assert store.get_meta("mail_uid") == "78"
    assert mail.render().startswith(f"[{mail.id}] when mail matching")
    store.close()


def test_triggers_tool(tmp_path: Path):
    store = TriggerStore(tmp_path / "t.db")
    changes: list[int] = []
    tool = Triggers(store=store)
    tool.thread_of = lambda: "t_9"
    tool.on_change = lambda: changes.append(1)
    tool.base_url = "http://phone.local:8787"
    tool.available = lambda: {"mail": False, "event": True, "hook": True}
    run = asyncio.run

    assert run(tool.execute(action="create", kind="mail", text="x")).error
    assert "email connector" in (
        run(tool.execute(action="create", kind="mail", text="x")).error or ""
    )
    assert run(tool.execute(action="create", kind="event", text="")).error
    assert run(tool.execute(action="create", text="x")).error  # no kind
    assert run(tool.execute(action="list")).output == "No triggers."

    r = run(
        tool.execute(
            action="create", kind="event", match="review", text="brief me", lead_minutes=20
        )
    )
    assert not r.error and r.output.startswith("Trigger set.")
    items = store.list("active")
    assert len(items) == 1 and items[0].thread == "t_9" and items[0].lead_minutes == 20
    assert changes == [1]

    r = run(tool.execute(action="create", kind="hook", match="deploy", text="check the site"))
    hook = store.active("hook")[0]
    assert f"http://phone.local:8787/api/hooks/{hook.id}?key={hook.secret}" in r.output

    listed = run(tool.execute(action="list")).output
    assert items[0].id in listed and hook.id in listed
    assert run(tool.execute(action="cancel")).error
    assert run(tool.execute(action="cancel", trigger_id="t_nope")).error
    assert run(tool.execute(action="cancel", trigger_id=hook.id)).output.startswith("Cancelled.")
    assert store.active("hook") == [] and changes == [1, 1, 1]
    assert run(tool.execute(action="rename")).error

    summary = tool.assess(
        {"action": "create", "kind": "mail", "match": "landlord", "text": "draft a reply"}
    ).summary
    assert summary == "triggers create: mail “landlord” — draft a reply"
    store.close()
