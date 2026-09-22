"""End-to-end tests for the app server: REST, WebSocket, approvals, threads, goals, memory."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openmuse.config import Settings
from openmuse.llm import MockLLM
from openmuse.schema import Function, LLMResponse, ToolCall
from openmuse.server import create_app
from openmuse.server.service import MuseService, _parse_ideas
from openmuse.server.webui import current_thread


def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


@pytest.fixture()
def server(settings: Settings) -> Iterator[tuple[TestClient, MuseService, MockLLM]]:
    settings.server.token = "secret-token"
    llm = MockLLM([])
    service = MuseService(settings, llm=llm)
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        yield client, service, llm


def wait_for(pred, timeout: float = 5.0, interval: float = 0.05):  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = pred()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


def events_of(
    client: TestClient, thread: str = "main", kind: str | None = None
) -> list[dict[str, Any]]:
    data = client.get(f"/api/threads/{thread}/events").json()["events"]
    return [e for e in data if kind is None or e["type"] == kind]


# ----------------------------------------------------------------------------- auth & state
def test_auth_required(server):
    client, _, _ = server
    assert client.get("/api/health").json()["auth"] is True
    anon = TestClient(client.app)
    assert anon.get("/api/state").status_code == 401
    assert anon.get("/api/state?token=secret-token").status_code == 200
    state = client.get("/api/state").json()
    assert state["profile"]["name"] == "Muse"
    assert [t["id"] for t in state["threads"]] == ["main"]
    assert state["settings"]["sentinel"]["mode"] == "ask"


# ----------------------------------------------------------------------------- chat
def test_send_message_runs_agent_and_records_timeline(server):
    client, _, llm = server
    llm.script.append(LLMResponse(content="Hello there! I can help."))
    r = client.post("/api/threads/main/send", json={"text": "hi"})
    assert r.status_code == 200
    assert r.json()["event"]["type"] == "user"
    assistant = wait_for(lambda: events_of(client, kind="assistant"))
    assert assistant[-1]["text"] == "Hello there! I can help."
    types = [e["type"] for e in events_of(client)]
    assert types == ["user", "assistant"]
    meta = client.get("/api/threads").json()[0]
    assert meta["busy"] is False and meta["events"] == 2


def test_terminate_summary_becomes_assistant_bubble(server):
    client, _, llm = server
    llm.script.append(
        LLMResponse(tool_calls=[tc("terminate", status="success", summary="All done ✔")])
    )
    client.post("/api/threads/main/send", json={"text": "do it"})
    assistant = wait_for(lambda: events_of(client, kind="assistant"))
    assert assistant[-1]["text"] == "All done ✔"
    # the summary is the bubble; no chip is shown for the terminate call itself
    assert events_of(client, kind="tool") == []


def test_approval_card_flow(server, settings: Settings):
    client, service, llm = server
    llm.script.extend(
        [
            LLMResponse(
                content="Running a command.", tool_calls=[tc("shell", command="echo approved-run")]
            ),
            LLMResponse(content="Done."),
        ]
    )
    client.post("/api/threads/main/send", json={"text": "run echo"})
    card = wait_for(
        lambda: [e for e in events_of(client, kind="approval") if e["status"] == "pending"]
    )[0]
    assert card["tool"] == "shell" and card["risk"] == "sensitive"
    assert client.get("/api/state").json()["pending_approvals"][0]["id"] == card["id"]

    assert card["purpose"] == "run echo"
    assert card["grant_key"] == "shell:echo" or card["grant_key"] == "shell"
    assert "session" in card["grant_options"]

    r = client.post(f"/api/approvals/{card['id']}", json={"approved": True, "scope": "session"})
    assert r.status_code == 200
    wait_for(lambda: [e for e in events_of(client, kind="approval") if e["status"] == "approved"])
    tool = wait_for(lambda: [e for e in events_of(client, kind="tool") if e["status"] == "ok"])[0]
    assert "approved-run" in tool["output"]
    grants = client.get("/api/activity").json()["grants"]
    assert [g["scope"] for g in grants] == ["session"] and grants[0]["tool"] == "shell"
    # deciding twice is rejected
    assert client.post(f"/api/approvals/{card['id']}", json={"approved": False}).status_code == 404
    # revoke one permission, then reset everything
    assert client.delete(f"/api/approvals/grants/{grants[0]['key']}").status_code == 200
    assert client.delete(f"/api/approvals/grants/{grants[0]['key']}").status_code == 404
    assert client.get("/api/activity").json()["grants"] == []
    assert client.delete("/api/approvals").status_code == 200


def test_denied_approval_blocks_tool(server):
    client, _, llm = server
    llm.script.extend(
        [
            LLMResponse(tool_calls=[tc("shell", command="echo nope")]),
            LLMResponse(content="Understood, I won't."),
        ]
    )
    client.post("/api/threads/main/send", json={"text": "run something"})
    card = wait_for(
        lambda: [e for e in events_of(client, kind="approval") if e["status"] == "pending"]
    )[0]
    client.post(f"/api/approvals/{card['id']}", json={"approved": False, "reason": "not now"})
    tool = wait_for(
        lambda: [e for e in events_of(client, kind="tool") if e["status"] != "running"]
    )[0]
    assert tool["status"] == "blocked"
    notices = wait_for(lambda: events_of(client, kind="notice"))
    assert "Sentinel blocked" in notices[0]["text"]


def test_ask_user_question_is_answered_by_next_message(server):
    client, _, llm = server
    llm.script.extend(
        [
            LLMResponse(tool_calls=[tc("ask_user", question="Which city?")]),
            LLMResponse(content="Great, Kyoto it is."),
        ]
    )
    client.post("/api/threads/main/send", json={"text": "plan a trip"})
    q = wait_for(
        lambda: [e for e in events_of(client, kind="question") if e["status"] == "pending"]
    )[0]
    assert q["text"] == "Which city?"
    client.post("/api/threads/main/send", json={"text": "Kyoto"})
    answered = wait_for(
        lambda: [e for e in events_of(client, kind="question") if e["status"] == "answered"]
    )[0]
    assert answered["answer"] == "Kyoto"
    final = wait_for(lambda: events_of(client, kind="assistant"))
    assert final[-1]["text"] == "Great, Kyoto it is."
    # the user's answer went to the model as a tool result, not as a new task
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role.value == "tool"]
    assert any("Kyoto" in (m.content or "") for m in tool_msgs)


def test_messages_sent_while_busy_are_folded_into_the_run(server):
    client, _, llm = server
    llm.script.extend(
        [
            LLMResponse(content="first reply", tool_calls=[tc("shell", command="echo x")]),
            LLMResponse(content="second reply"),
        ]
    )
    client.post("/api/threads/main/send", json={"text": "task one"})
    # The shell call needs approval, so the run is parked on the approval card → send another message now.
    card = wait_for(
        lambda: [e for e in events_of(client, kind="approval") if e["status"] == "pending"]
    )[0]
    client.post("/api/threads/main/send", json={"text": "also do task two"})
    client.post(f"/api/approvals/{card['id']}", json={"approved": True})
    wait_for(
        lambda: [e for e in events_of(client, kind="assistant") if e["text"] == "second reply"]
    )
    user_msgs = [m.content for m in llm.calls[1]["messages"] if m.role.value == "user"]
    assert "also do task two" in user_msgs, (
        "queued message should be visible to the model in the same run"
    )
    assert len(llm.calls) == 2


# ----------------------------------------------------------------------------- websocket
def test_websocket_hello_and_live_events(server):
    client, _, llm = server
    llm.script.append(LLMResponse(content="ws reply"))
    with client.websocket_connect("/ws?token=secret-token") as ws:
        hello = ws.receive_json()
        assert hello["kind"] == "hello" and hello["state"]["profile"]["name"] == "Muse"
        ws.send_json({"kind": "send", "thread": "main", "text": "hello over ws"})
        seen: list[str] = []
        deadline = time.time() + 5
        while time.time() < deadline and "ws reply" not in seen:
            msg = ws.receive_json()
            if msg["kind"] == "event" and msg["event"]["type"] in ("user", "assistant"):
                seen.append(msg["event"]["text"])
        assert seen == ["hello over ws", "ws reply"]


def test_websocket_rejects_bad_token(server):
    client, _, _ = server
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws?token=wrong") as ws:
        ws.receive_json()


# ----------------------------------------------------------------------------- side chats
def test_side_chats_are_isolated(server):
    client, _, llm = server
    t = client.post("/api/threads", json={"title": "Trip"}).json()
    assert t["title"] == "Trip"
    llm.script.append(LLMResponse(content="side reply"))
    client.post(f"/api/threads/{t['id']}/send", json={"text": "side question"})
    wait_for(lambda: events_of(client, t["id"], "assistant"))
    assert events_of(client, "main") == []
    assert (
        client.patch(f"/api/threads/{t['id']}", json={"title": "Kyoto trip"}).json()["title"]
        == "Kyoto trip"
    )
    assert client.delete("/api/threads/main").status_code == 400
    assert client.delete(f"/api/threads/{t['id']}").status_code == 200
    assert client.get(f"/api/threads/{t['id']}/events").status_code == 404


# ----------------------------------------------------------------------------- goals / memory / settings / files
def test_goals_api(server):
    client, _, llm = server
    g = client.post(
        "/api/goals",
        json={"title": "Run a 10k", "description": "by June", "steps": ["Plan", "Train"]},
    ).json()
    assert g["progress"] == {"done": 0, "total": 2} and g["next_step"] == "Plan"
    g = client.patch(
        f"/api/goals/{g['id']}", json={"step_index": 1, "step_status": "done", "step_note": "ok"}
    ).json()
    assert g["steps"][0]["status"] == "done" and g["progress"]["done"] == 1
    g = client.post(f"/api/goals/{g['id']}/steps", json={"title": "Race"}).json()
    assert [s["title"] for s in g["steps"]] == ["Plan", "Train", "Race"]
    # advancing posts a notice in the main chat and runs the agent there
    llm.script.append(
        LLMResponse(tool_calls=[tc("terminate", status="success", summary="Trained today.")])
    )
    assert client.post(f"/api/goals/{g['id']}/advance").status_code == 200
    notice = wait_for(lambda: events_of(client, kind="notice"))[0]
    assert "Run a 10k" in notice["text"] and notice["source"] == "goal"
    assert events_of(client, kind="user") == []  # the goal prompt is not shown as a user bubble
    reply = wait_for(lambda: events_of(client, kind="assistant"))[0]
    # work done on the agent's own initiative is tagged, so the Feed can show it
    assert reply["source"] == "background" and "Run a 10k" in reply["about"]
    # one Feed entry per pass: its final word, not the step-by-step narration
    feed = client.get("/api/feed").json()
    assert [i["kind"] for i in feed] == ["background"]
    assert feed[0]["title"] == "Working on your goal: Run a 10k"
    assert feed[0]["text"] == "Trained today." and feed[0]["thread_title"] == "Main chat"
    g = client.patch(f"/api/goals/{g['id']}", json={"status": "paused"}).json()
    assert g["status"] == "paused"
    assert client.post(f"/api/goals/{g['id']}/advance").status_code == 409
    assert client.delete(f"/api/goals/{g['id']}").status_code == 200
    assert client.get("/api/goals").json() == []


def test_goal_categories_check_ins_and_proposals_api(server):
    client, service, llm = server
    g = client.post(
        "/api/goals",
        json={
            "title": "Call mum weekly",
            "category": "family",
            "due": "2026-12-31",
            "check_in": "weekly sun 18:00",
            "steps": ["Pick a time", "Call"],
        },
    ).json()
    assert g["category"] == "family" and g["due"] == "2026-12-31" and g["overdue"] is False
    assert g["check_in"] == "weekly sun 18:00" and g["next_check_in"]
    assert client.get("/api/goals?category=family").json()[0]["id"] == g["id"]
    assert client.get("/api/goals?category=health").json() == []
    up = client.get("/api/upcoming").json()
    assert up["check_ins"][0]["goal_id"] == g["id"] and up["queue"][0]["category"] == "family"
    assert client.post("/api/goals", json={"title": "x", "check_in": "whenever"}).status_code == 400
    # the goal's own fields can be edited; "" clears
    g = client.patch(
        f"/api/goals/{g['id']}", json={"category": "relationships", "due": "", "check_in": ""}
    ).json()
    assert g["category"] == "relationships" and g["due"] == "" and g["next_check_in"] is None

    # a check-in is a message from the agent, delivered whatever the proactivity level
    client.put("/api/settings", json={"profile": {"proactivity": "off"}})
    llm.script.append(LLMResponse(content="How did the call go on Sunday? Want to pick a slot?"))
    assert client.post(f"/api/goals/{g['id']}/check-in").status_code == 200
    said = wait_for(lambda: events_of(client, kind="assistant"))
    assert said[-1]["about"] == "Call mum weekly" or "Call mum weekly" in said[-1]["about"]
    assert not said[-1].get("quiet")
    sent = llm.calls[-1]["messages"][-1].content
    assert "check-in time" in sent and "Call mum weekly" in sent

    # the agent proposes a plan change; the user accepts it in the app
    llm.script.append(
        LLMResponse(
            tool_calls=[
                tc(
                    "goals",
                    action="propose",
                    goal_id=g["id"],
                    note="Sundays never work; evenings do",
                    steps=["Pick a weekday evening", "Call"],
                ),
                tc("terminate", status="success", summary="I suggested a change to the plan."),
            ]
        )
    )
    client.post("/api/threads/main/send", json={"text": "the plan isn't working"})
    wait_for(lambda: len(events_of(client, kind="assistant")) >= 2)
    g = client.get(f"/api/goals/{g['id']}").json()
    assert g["proposal"]["reason"] == "Sundays never work; evenings do"
    assert [s["title"] for s in g["steps"]] == ["Pick a time", "Call"]  # untouched until accepted
    assert client.delete(f"/api/goals/{g['id']}/proposal").status_code == 200
    assert client.delete(f"/api/goals/{g['id']}/proposal").status_code == 409
    llm.script.append(
        LLMResponse(
            tool_calls=[
                tc("goals", action="propose", goal_id=g["id"], note="evenings", steps=["Call Tue"]),
                tc("terminate", status="success", summary="Proposed."),
            ]
        )
    )
    client.post("/api/threads/main/send", json={"text": "try again"})
    wait_for(lambda: client.get(f"/api/goals/{g['id']}").json()["proposal"] is not None)
    g = client.post(f"/api/goals/{g['id']}/proposal/accept").json()
    assert g["proposal"] is None and [s["title"] for s in g["steps"]] == ["Call Tue"]
    assert "plan adjusted" in g["notes"]


def test_goal_check_ins_and_proposals_api(server):
    client, service, llm = server
    g = client.post(
        "/api/goals",
        json={
            "title": "Walk every morning",
            "steps": ["Walk 20 min"],
            "category": "health",
            "due": "2030-06-01",
            "check_in": "daily 07:00",
        },
    ).json()
    assert g["category"] == "health" and g["due"] == "2030-06-01" and not g["overdue"]
    assert g["check_in"] == "daily 07:00" and g["next_check_in"]
    assert client.get("/api/goals", params={"category": "finance"}).json() == []
    assert client.get("/api/goals", params={"category": "health"}).json()[0]["id"] == g["id"]
    up = client.get("/api/upcoming").json()
    assert (
        up["check_ins"][0]["goal_id"] == g["id"] and up["check_ins"][0]["cadence"] == "daily 07:00"
    )
    assert (
        client.post("/api/goals", json={"title": "x", "check_in": "sometimes"}).status_code == 400
    )

    # a check-in is a message from the agent, delivered whatever the proactivity level says
    client.put("/api/settings", json={"profile": {"proactivity": "off"}})
    llm.script.append(LLMResponse(content="Morning! Did the walk happen today?"))
    assert client.post(f"/api/goals/{g['id']}/check-in").status_code == 200
    said = wait_for(lambda: events_of(client, kind="assistant"))[0]
    assert said["about"] == "Check-in: Walk every morning" and not said.get("quiet")
    sent = llm.calls[-1]["messages"][-1].content
    assert "check-in time" in sent and "Walk every morning" in sent
    # the reminder moved on to its next occurrence
    nxt = client.get(f"/api/goals/{g['id']}").json()["next_check_in"]
    assert nxt > g["next_check_in"]
    # the scheduler only fires reminders whose time has come
    service._run_due_check_ins()
    assert len(events_of(client, kind="notice")) == 1

    # the agent proposes a plan change; the user accepts it in the app
    assert client.post(f"/api/goals/{g['id']}/proposal/accept").status_code == 409
    service.app.goals.propose(
        g["id"], "knee hurts — swap to cycling", ["Cycle 20 min", "See a physio"]
    )
    g2 = client.get(f"/api/goals/{g['id']}").json()
    assert g2["proposal"]["reason"].startswith("knee hurts")
    g3 = client.post(f"/api/goals/{g['id']}/proposal/accept").json()
    assert [s["title"] for s in g3["steps"]] == ["Cycle 20 min", "See a physio"] and g3[
        "proposal"
    ] is None
    service.app.goals.propose(g["id"], "again", ["Nothing"])
    assert client.delete(f"/api/goals/{g['id']}/proposal").json()["proposal"] is None
    # editing the goal's own fields
    g4 = client.patch(
        f"/api/goals/{g['id']}", json={"category": "learning", "due": "", "check_in": ""}
    ).json()
    assert g4["category"] == "learning" and g4["due"] == "" and g4["next_check_in"] is None
    assert client.get("/api/upcoming").json()["check_ins"] == []


def test_memory_api(server):
    client, _, _ = server
    m = client.post(
        "/api/memory", json={"content": "I am vegetarian", "category": "preference"}
    ).json()
    assert m["source"] == "user"
    assert client.get("/api/memory").json()[0]["content"] == "I am vegetarian"
    assert client.delete(f"/api/memory/{m['id']}").status_code == 200
    assert client.get("/api/memory").json() == []
    assert client.delete("/api/memory/m_nope").status_code == 404


def test_settings_and_profile(server, settings: Settings):
    client, service, _ = server
    view = client.put(
        "/api/settings",
        json={
            "profile": {"name": "Veda", "emoji": "🌙", "style": "warm and concise"},
            "sentinel_mode": "strict",
        },
    ).json()
    assert view["profile"]["name"] == "Veda" and view["sentinel"]["mode"] == "strict"
    assert settings.agent.name == "Veda"
    assert "warm and concise" in settings.agent.instructions
    assert (settings.data_dir / "profile.json").exists()
    # a fresh service picks the profile up again
    fresh = MuseService(settings, llm=MockLLM([]))
    assert fresh.profile.name == "Veda"
    assert (
        client.put("/api/settings", json={"sentinel_mode": "bogus"}).json()["sentinel"]["mode"]
        == "strict"
    )


def test_user_name_reaches_the_instructions(server, settings: Settings):
    client, _, _ = server
    client.put("/api/settings", json={"profile": {"user_name": "Sam"}})
    assert "The user's name is Sam" in settings.agent.instructions


# ----------------------------------------------------------------------------- connections
def test_connections_model_key_goes_to_the_vault(server, settings: Settings):
    client, service, _ = server
    view = client.get("/api/connections").json()
    assert view["llm"]["key_source"] == "config" and "deepseek" in view["providers"]
    assert view["onboarded"] is False
    # the test endpoint talks to the current (mock) model
    service.app.llm.script.append(LLMResponse(content="OK"))
    result = client.post("/api/connections/llm/test").json()
    assert result["ok"] is True and result["reply"] == "OK"

    r = client.put(
        "/api/connections/llm",
        json={
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/",
            "api_key": "sk-secret-123",
        },
    )
    assert r.status_code == 200
    llm = r.json()
    assert llm["model"] == "deepseek-chat" and llm["key_source"] == "vault" and llm["from_app"]
    # the key itself never comes back over the API, only its name
    assert "sk-secret-123" not in json.dumps(client.get("/api/connections").json())
    assert client.get("/api/vault").json() == ["LLM_API_KEY"]
    assert service.app.vault.get("LLM_API_KEY") == "sk-secret-123"
    # settings carry a reference, and every thread now talks to the new client
    assert settings.llm.api_key == "{{vault:LLM_API_KEY}}"
    assert settings.llm.base_url == "https://api.deepseek.com"
    assert all(t.agent.llm is service.app.llm for t in service.threads.values())
    # the file on disk holds the reference, not the key
    on_disk = (settings.data_dir / "app-settings.json").read_text()
    assert "sk-secret-123" not in on_disk and "vault:LLM_API_KEY" in on_disk

    # the new client got the real key, resolved from the vault
    assert service.app.llm.settings.api_key == "sk-secret-123"
    assert service.app.llm.settings.model == "deepseek-chat"
    assert client.put("/api/connections/llm", json={"tool_mode": "bogus"}).status_code == 400


def test_connections_email_and_browser(server, settings: Settings):
    client, service, _ = server
    email = client.put(
        "/api/connections/email",
        json={
            "address": "alice@example.com",
            "password": "app-pass",
            "imap_host": "imap.example.com",
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_starttls": False,
        },
    ).json()
    assert email["enabled"] and email["configured"] and email["address"] == "alice@example.com"
    assert email["password_set"] is True and "app-pass" not in json.dumps(email)
    assert settings.connectors.email.smtp_port == 465 and settings.connectors.email.enabled
    assert "read_emails" in service.app.tools and "send_email" in service.app.tools
    assert service.app.vault.get("EMAIL_PASSWORD") == "app-pass"

    # an unreachable server fails the test cleanly instead of hanging
    settings.connectors.email.imap_host = "127.0.0.1"
    settings.connectors.email.imap_port = 9
    assert client.post("/api/connections/email/test").json()["ok"] is False

    off = client.delete("/api/connections/email").json()
    assert off["enabled"] is False and off["configured"] is False and off["password_set"] is False
    assert "read_emails" not in service.app.tools
    assert service.app.vault.get("EMAIL_PASSWORD") is None

    browser = client.put("/api/connections/browser", json={"enabled": True}).json()
    assert browser["enabled"] is True
    assert (
        client.put("/api/connections/browser", json={"enabled": False}).json()["enabled"] is False
    )


def test_connections_mcp_and_vault(server):
    client, _, _ = server
    # a server that cannot start is reported, not swallowed
    r = client.post(
        "/api/connections/mcp", json={"name": "broken", "command": "/nonexistent/mcp-server"}
    )
    assert r.status_code == 502
    assert client.post("/api/connections/mcp", json={"name": "x"}).status_code == 400
    assert client.delete("/api/connections/mcp/nope").status_code == 404

    assert client.put("/api/vault/GITHUB_TOKEN", json={"value": "ghp_x"}).json() == ["GITHUB_TOKEN"]
    assert client.put("/api/vault/bad name", json={"value": "x"}).status_code == 400
    assert client.delete("/api/vault/GITHUB_TOKEN").json() == {"ok": True}
    assert client.delete("/api/vault/GITHUB_TOKEN").status_code == 404

    client.post("/api/onboarded", json={"done": True})
    assert client.get("/api/settings").json()["onboarded"] is True


def test_app_settings_are_layered_on_config(server, settings: Settings):
    from openmuse.config import Settings as S
    from openmuse.config import apply_app_settings, load_app_settings

    client, _, _ = server
    client.put("/api/connections/llm", json={"model": "m2", "api_key": "k"})
    client.put("/api/connections/email", json={"imap_host": "imap.x", "smtp_host": "smtp.x"})
    client.put("/api/connections/browser", json={"enabled": True})
    fresh = S()
    apply_app_settings(fresh, load_app_settings(settings.data_dir))
    assert fresh.llm.model == "m2" and fresh.llm.api_key == "{{vault:LLM_API_KEY}}"
    assert fresh.connectors.email.imap_host == "imap.x" and fresh.browser.enabled is True


def test_files_are_scoped_to_workspace(server, settings: Settings):
    client, _, _ = server
    (settings.agent.workspace / "notes").mkdir()
    (settings.agent.workspace / "notes" / "plan.md").write_text("# plan", "utf-8")
    listing = client.get("/api/files").json()
    assert listing[0]["path"] == "notes/plan.md"
    assert client.get("/api/files/notes/plan.md").text == "# plan"
    # encoded traversal reaches the handler (a literal ".." is normalised away by the client)
    assert client.get("/api/files/%2e%2e/config.toml").status_code in (403, 404)
    with pytest.raises(PermissionError):
        server[1].resolve_workspace_path("../config.toml")
    assert client.get("/api/files/nope.txt").status_code == 404


def test_any_tool_that_writes_a_file_yields_one_artifact_card(server, settings: Settings):
    client, _, llm = server
    # python_execute is auto-allowed in the test settings; it writes a page, then rewrites it
    code = "open('report.html','w').write('<h1>{}</h1>')"
    llm.script.extend(
        [
            LLMResponse(tool_calls=[tc("python_execute", code=code.format("v1"))]),
            LLMResponse(tool_calls=[tc("python_execute", code=code.format("v2"))]),
            LLMResponse(tool_calls=[tc("files", action="write", path="notes.md", content="hi")]),
            LLMResponse(content="Made the report and a note."),
        ]
    )
    client.post("/api/threads/main/send", json={"text": "make a report"})
    wait_for(lambda: events_of(client, kind="assistant"))
    cards = events_of(client, kind="artifact")
    # the second write refreshed the first card (action → update) instead of adding another
    assert [(c["path"], c["action"]) for c in cards] == [
        ("report.html", "update"),
        ("notes.md", "write"),
    ]
    assert cards[0]["updated_ts"]
    assert (settings.agent.workspace / "report.html").read_text() == "<h1>v2</h1>"
    assert client.get("/api/feed").json() == []  # your own request is not "while you were away"


def test_html_artifacts_are_served_sandboxed(server, settings: Settings):
    client, _, _ = server
    (settings.agent.workspace / "page.html").write_text("<script>alert(1)</script>", "utf-8")
    r = client.get("/api/files/page.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "sandbox" in r.headers["content-security-policy"]
    (settings.agent.workspace / "notes.md").write_text("# hi", "utf-8")
    assert "content-security-policy" not in client.get("/api/files/notes.md").headers


def test_feed_and_upcoming(server):
    client, service, llm = server
    assert client.get("/api/feed").json() == []
    # background work is on at the default level from the start, like Muse; nothing is
    # queued until there is a goal
    up = client.get("/api/upcoming").json()
    assert up["proactivity"] == "default" and up["proactive"] is True and up["queue"] == []
    client.put("/api/settings", json={"profile": {"proactivity": "off"}})
    up = client.get("/api/upcoming").json()
    assert up["proactive"] is False and up["next_pass_at"] is None

    g = client.post("/api/goals", json={"title": "Learn Spanish", "steps": ["Pick an app"]}).json()
    client.put("/api/settings", json={"profile": {"proactive": True, "goal_interval_minutes": 30}})
    up = client.get("/api/upcoming").json()
    assert up["proactive"] is True and up["interval_minutes"] == 30
    assert up["proactivity"] == "default" and up["effective_interval_minutes"] == 30
    # the dial stretches or shrinks the interval
    client.put("/api/settings", json={"profile": {"proactivity": "low"}})
    assert client.get("/api/upcoming").json()["effective_interval_minutes"] == 60
    client.put("/api/settings", json={"profile": {"proactivity": "high"}})
    assert client.get("/api/upcoming").json()["effective_interval_minutes"] == 15
    client.put("/api/settings", json={"profile": {"proactivity": "default"}})
    assert up["queue"] == [
        {
            "goal_id": g["id"],
            "title": "Learn Spanish",
            "category": "",
            "due": None,
            "overdue": False,
            "next_step": "Pick an app",
            "progress": {"done": 0, "total": 1},
        }
    ]
    assert up["check_ins"] == []

    # a pending approval is something the Feed shows, whatever thread it belongs to
    side = client.post("/api/threads", json={"title": "Side"}).json()
    llm.script.extend(
        [
            LLMResponse(tool_calls=[tc("shell", command="echo hi")]),
            LLMResponse(content="ok"),
        ]
    )
    client.post(f"/api/threads/{side['id']}/send", json={"text": "run it"})
    card = wait_for(
        lambda: [e for e in events_of(client, side["id"], "approval") if e["status"] == "pending"]
    )[0]
    feed = client.get("/api/feed").json()
    assert feed[0]["kind"] == "approval" and feed[0]["thread"] == side["id"]
    assert feed[0]["id"] == card["id"] and feed[0]["thread_title"] == "Side"
    assert client.get("/api/state").json()["pending_approvals"][0]["id"] == card["id"]
    client.post(f"/api/approvals/{card['id']}", json={"approved": False})
    wait_for(lambda: events_of(client, side["id"], "assistant"))
    assert client.get("/api/feed").json() == []


def test_quiet_passes_stay_out_of_the_way(server, settings: Settings):
    client, service, llm = server
    g = client.post(
        "/api/goals", json={"title": "Water the plants", "steps": ["Check soil"]}
    ).json()
    # the pass finds nothing to report: the summary starts with the quiet marker
    llm.script.append(LLMResponse(content="[quiet] Soil is still damp; nothing to do today."))
    client.post(f"/api/goals/{g['id']}/advance")
    said = wait_for(lambda: events_of(client, kind="assistant"))
    assert said[-1]["quiet"] is True and said[-1]["source"] == "background"
    assert said[-1]["text"] == "Soil is still damp; nothing to do today."
    feed = client.get("/api/feed").json()
    background = [i for i in feed if i["kind"] == "background"]
    assert background and background[0]["quiet"] is True
    # the level decides what the pass is told about reaching out
    client.put("/api/settings", json={"profile": {"proactivity": "high"}})
    llm.script.append(LLMResponse(content="Still on track."))
    client.post(f"/api/goals/{g['id']}/advance")
    wait_for(lambda: len(events_of(client, kind="assistant")) >= 2)
    sent = llm.calls[-1]["messages"][-1].content
    assert "Always report" in sent
    assert not events_of(client, kind="assistant")[-1].get("quiet")


def test_quiet_hours_push_the_next_pass_out(server):
    from openmuse.server.service import Profile

    client, service, _ = server
    client.put("/api/settings", json={"profile": {"quiet_hours": "22:00-08:00"}})
    assert service.profile.quiet_hours == "22:00-08:00"
    assert (
        client.put("/api/settings", json={"profile": {"quiet_hours": "nope"}}).json()["profile"][
            "quiet_hours"
        ]
        == ""
    )
    p = Profile(quiet_hours="22:00-08:00")
    tz = datetime.now().astimezone().tzinfo
    assert p.in_quiet_hours(datetime(2026, 1, 1, 23, 30, tzinfo=tz))
    assert p.in_quiet_hours(datetime(2026, 1, 1, 7, 59, tzinfo=tz))
    assert not p.in_quiet_hours(datetime(2026, 1, 1, 12, 0, tzinfo=tz))
    end = p.quiet_hours_end(datetime(2026, 1, 1, 23, 30, tzinfo=tz))
    assert end is not None and (end.hour, end.minute, end.day) == (8, 0, 2)
    assert Profile(quiet_hours="09:00-17:00").in_quiet_hours(datetime(2026, 1, 1, 12, 0, tzinfo=tz))
    assert Profile(proactivity="off").proactive is False
    # a profile written before the dial existed
    assert Profile.from_dict({"proactive": True}).proactivity == "default"
    assert Profile.from_dict({"proactive": False}).proactivity == "off"


def test_ideas_fallback_and_parsing(server):
    client, _, llm = server
    data = client.get("/api/ideas").json()
    assert data["source"] == "starter" and len(data["ideas"]) >= 3
    llm.script.append(
        LLMResponse(
            content='Here you go: [{"title": "Book the dentist", "detail": "You mentioned it.", "prompt": "Find a dentist near me"}]'
        )
    )
    client.post(
        "/api/memory", json={"content": "Needs a dentist appointment", "category": "general"}
    )
    data = client.get("/api/ideas?refresh=1").json()
    assert data["source"] == "model" and data["ideas"][0]["title"] == "Book the dentist"
    assert _parse_ideas("no json here") == []
    assert _parse_ideas('<think>x</think>[{"title":"a","prompt":"b"}]')[0]["title"] == "a"


def test_timeline_survives_restart(server, settings: Settings):
    client, service, llm = server
    llm.script.append(LLMResponse(content="persisted"))
    client.post("/api/threads/main/send", json={"text": "remember this"})
    wait_for(lambda: events_of(client, kind="assistant"))
    fresh = MuseService(settings, llm=MockLLM([]))
    texts = [e["text"] for e in fresh.threads["main"].timeline.events]
    assert texts == ["remember this", "persisted"]
    # and the model context was restored as well
    assert [m.role.value for m in fresh.threads["main"].agent.messages] == ["user", "assistant"]


# ----------------------------------------------------------------------------- push
FAKE_SUB = {
    "endpoint": "https://push.example/sub/1",
    "keys": {"p256dh": "BPk", "auth": "abc"},
}


def test_push_keys_subscriptions_and_gone_endpoints(settings: Settings, monkeypatch):
    from openmuse.server import push as push_mod
    from openmuse.server.push import PushService

    svc = PushService(settings.data_dir)
    assert svc.enabled and svc.public_key and (settings.data_dir / "push-vapid.json").is_file()
    # the same keys come back on the next start; a phone stays subscribed across restarts
    assert PushService(settings.data_dir).public_key == svc.public_key

    with pytest.raises(ValueError):
        svc.subscribe({"endpoint": "http://not-https", "keys": {}})
    assert svc.subscribe(FAKE_SUB, ua="Safari on iPhone") == 1
    assert svc.subscribe({**FAKE_SUB, "endpoint": "https://push.example/sub/2"}) == 2
    assert svc.subscribe(FAKE_SUB) == 2  # re-subscribing the same endpoint replaces it
    assert PushService(settings.data_dir).view()["subscriptions"] == 2

    sent: list[tuple[str, dict[str, Any]]] = []

    class Gone(Exception):
        response = type("R", (), {"status_code": 410})()

    def fake_webpush(subscription_info, data, **_kw):  # noqa: ANN001
        if subscription_info["endpoint"].endswith("/2"):
            raise Gone("gone")
        sent.append((subscription_info["endpoint"], json.loads(data)))

    import pywebpush

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    monkeypatch.setattr(pywebpush, "WebPushException", Gone)
    svc._send_all({"title": "t", "body": "b", "tag": "x", "url": "/", "badge": 1, "kind": "test"})
    assert [e for e, _ in sent] == ["https://push.example/sub/1"]
    assert sent[0][1]["title"] == "t" and sent[0][1]["badge"] == 1
    # the endpoint the push service reported gone is forgotten
    assert [s["endpoint"] for s in svc.subscriptions] == ["https://push.example/sub/1"]
    assert svc.unsubscribe("https://push.example/sub/1") and svc.subscriptions == []
    assert push_mod.available()


def test_cards_and_background_results_reach_the_phone(server, monkeypatch):
    client, service, llm = server
    pushed: list[dict[str, Any]] = []
    monkeypatch.setattr(
        service.push,
        "notify",
        lambda title, body, **kw: pushed.append({"title": title, "body": body, **kw}),
    )
    r = client.post("/api/push/subscribe", json={"subscription": FAKE_SUB})
    assert r.status_code == 200 and r.json()["subscriptions"] == 1
    assert client.get("/api/push").json()["public_key"]

    llm.script.extend(
        [
            LLMResponse(content="Running a command.", tool_calls=[tc("shell", command="echo hi")]),
            LLMResponse(content="Done."),
        ]
    )
    client.post("/api/threads/main/send", json={"text": "run echo"})
    card = wait_for(
        lambda: [e for e in events_of(client, kind="approval") if e["status"] == "pending"]
    )[0]
    assert pushed and pushed[-1]["kind"] == "approval"
    assert pushed[-1]["title"].endswith("needs your approval") and pushed[-1]["badge"] == 1
    assert pushed[-1]["tag"] == f"approval-{card['id']}" and pushed[-1]["url"] == "/"
    client.post(f"/api/approvals/{card['id']}", json={"approved": True})
    wait_for(lambda: not service.threads["main"].busy)
    # the user's own turn ending is not pushed: only background results are
    assert [p["kind"] for p in pushed] == ["approval"]

    # a background pass that had something to say
    service.push.subscriptions and service._maybe_push(
        {
            "id": "a1",
            "type": "assistant",
            "thread": "main",
            "source": "background",
            "about": "Working on your goal: Learn Rust",
            "text": "**Chapter 3** is done — [notes](notes.md) are in the library.",
        }
    )
    assert pushed[-1]["title"] == "Learn Rust" and pushed[-1]["kind"] == "background"
    assert pushed[-1]["body"] == "Chapter 3 is done — notes are in the library."
    # a quiet pass stays in the app
    before = len(pushed)
    service._maybe_push(
        {
            "id": "a2",
            "type": "assistant",
            "thread": "main",
            "source": "background",
            "quiet": True,
            "text": "nothing new",
        }
    )
    assert len(pushed) == before

    r = client.post("/api/push/unsubscribe", json={"endpoint": FAKE_SUB["endpoint"]})
    assert r.json()["subscriptions"] == 0
    # nothing subscribed: nothing to send
    assert client.post("/api/push/test").json()["ok"] is False


# ----------------------------------------------------------------------------- browser view
def test_browser_frames_make_one_live_card_per_run(server):
    from openmuse.tools.browser import BrowserFrame

    client, service, _ = server
    ui = service.ui
    ui.begin_run("main")
    token = current_thread.set("main")
    try:
        ui.on_browser_frame(
            BrowserFrame("https://a.example/", "A", "Opened a.example", b"\xff\xd8one")
        )
        ui.on_browser_frame(
            BrowserFrame("https://a.example/x", "A/x", "Clicked 'x'", b"\xff\xd8two")
        )
    finally:
        current_thread.reset(token)
    cards = events_of(client, kind="browser")
    assert len(cards) == 1
    card = cards[0]
    assert card["status"] == "live" and card["frames"] == 2 and card["action"] == "Clicked 'x'"
    assert card["url"] == "https://a.example/x" and card["title"] == "A/x"
    # the latest frame is served as a JPEG; older ones stay for a while, unknown ones 404
    r = client.get(f"/api/browser/main/frames/{card['frame']}.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8two"
    assert client.get("/api/browser/main/frames/f_nope.jpg").status_code == 404

    ui.end_run("main")
    assert events_of(client, kind="browser")[0]["status"] == "done"

    # the user driving between runs refreshes the last card instead of adding one
    ui.on_browser_frame(
        BrowserFrame(
            "https://a.example/login",
            "Login",
            "You tapped the page",
            b"\xff\xd8three",
            True,
            "main",
        )
    )
    cards = events_of(client, kind="browser")
    assert len(cards) == 1 and cards[0]["by_user"] and cards[0]["frames"] == 3
    assert cards[0]["status"] == "done"

    # a new run gets a new card
    ui.begin_run("main")
    token = current_thread.set("main")
    try:
        ui.on_browser_frame(
            BrowserFrame("https://b.example/", "B", "Opened b.example", b"\xff\xd8four")
        )
    finally:
        current_thread.reset(token)
    ui.end_run("main")
    assert len(events_of(client, kind="browser")) == 2

    # taking over needs the browser tool
    r = client.post("/api/browser/main/control", json={"action": "click", "x": 0.5, "y": 0.5})
    assert r.status_code == 409
    assert client.post("/api/browser/main/control", json={"action": "fly"}).status_code in (
        400,
        409,
    )
    assert (
        client.post("/api/browser/main/control", json={"action": "click", "x": 2}).status_code
        == 422
    )


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
    except Exception:  # noqa: BLE001
        return False
    return True


@pytest.mark.skipif(not _chromium_available(), reason="playwright + chromium not installed")
async def test_browser_tool_reports_frames_and_user_takeover(tmp_path):
    import http.server
    import threading

    from openmuse.tools.browser import Browser, BrowserFrame

    html = (
        b"<title>Login</title><h1>Sign in</h1><input id=u placeholder=User>"
        b"<button onclick=\"document.querySelector('h1').textContent='Welcome'\">Go</button>"
    )

    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *_):  # noqa: ANN002
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    page = f"http://127.0.0.1:{httpd.server_port}/"

    frames: list[BrowserFrame] = []
    tool = Browser(workspace=tmp_path, on_frame=frames.append)
    try:
        result = await tool.execute(action="navigate", url=page)
        assert not result.error and "Sign in" in result.output and "[0]" in result.output
        assert (
            frames and frames[-1].jpeg[:2] == b"\xff\xd8" and frames[-1].action.startswith("Opened")
        )
        assert frames[-1].title == "Login" and not frames[-1].by_user

        # the agent clicks: the caption names the button, the page changed
        result = await tool.execute(action="click", index=1)
        assert "Welcome" in result.output and frames[-1].action == "Clicked 'Go'"

        # the user takes over, then the model is told what happened
        state = await tool.user_action("navigate", "main", url=page)
        assert state["title"] == "Login" and frames[-1].by_user and frames[-1].thread == "main"
        await tool.user_action("click", "main", x=0.5, y=0.5)
        await tool.user_action("type", "main", text="alice")
        result = await tool.execute(action="extract")
        assert "the user took over the browser" in result.output
        assert "typed 5 characters" in result.output and "clicked at" in result.output
        # reported once
        result = await tool.execute(action="extract")
        assert "took over" not in result.output
    finally:
        await tool.cleanup()
        httpd.shutdown()
