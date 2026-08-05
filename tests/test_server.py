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
            "next_step": "Pick an app",
            "progress": {"done": 0, "total": 1},
        }
    ]

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
