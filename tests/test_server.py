"""End-to-end tests for the app server: REST, WebSocket, approvals, threads, goals, memory."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openmuse.config import Settings
from openmuse.llm import MockLLM
from openmuse.schema import Function, LLMResponse, ToolCall
from openmuse.server import create_app
from openmuse.server.service import MuseService, _parse_ideas


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
    tools = events_of(client, kind="tool")
    assert tools and tools[0]["tool"] == "terminate" and tools[0]["status"] == "ok"


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

    r = client.post(f"/api/approvals/{card['id']}", json={"approved": True, "scope": "session"})
    assert r.status_code == 200
    wait_for(lambda: [e for e in events_of(client, kind="approval") if e["status"] == "approved"])
    tool = wait_for(lambda: [e for e in events_of(client, kind="tool") if e["status"] == "ok"])[0]
    assert "approved-run" in tool["output"]
    activity = client.get("/api/activity").json()
    assert "shell" in activity["approvals"]["session"]
    # deciding twice is rejected
    assert client.post(f"/api/approvals/{card['id']}", json={"approved": False}).status_code == 404
    # reset permissions
    assert client.delete("/api/approvals").status_code == 200
    assert client.get("/api/activity").json()["approvals"]["session"] == []


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
    wait_for(lambda: events_of(client, kind="assistant"))
    g = client.patch(f"/api/goals/{g['id']}", json={"status": "paused"}).json()
    assert g["status"] == "paused"
    assert client.post(f"/api/goals/{g['id']}/advance").status_code == 409
    assert client.delete(f"/api/goals/{g['id']}").status_code == 200
    assert client.get("/api/goals").json() == []


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
