"""The CLI bridge: call tokens, the three programs, and a command that reaches back in."""

from __future__ import annotations

import json
import shlex
import sys
import time
from typing import Any

import pytest

from nanomuse.bridge.cli import BridgeClient, browser_main, device_main, open_main, parse_pairs
from nanomuse.bridge.server import Bridge, BridgeError
from nanomuse.bridge.tokens import BRIDGE_TOKEN_ENV, BRIDGE_URL_ENV, BridgeTokens
from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.runtime import Device, device, device_mcp_server
from nanomuse.schema import LLMResponse, RiskLevel, ToolResult
from nanomuse.server import bridge_url, create_app
from nanomuse.server.service import MuseService
from nanomuse.tools.base import BaseTool, CallAssessment
from tests.test_server import tc, wait_for, wait_idle


# ----------------------------------------------------------------------------- tokens
def test_tokens_live_for_the_command_and_a_grace_period():
    tokens = BridgeTokens()
    grant = tokens.mint("call1", "shell", ttl=10)
    assert tokens.get(grant.token) is grant
    assert tokens.get("nope") is None and tokens.get(None) is None
    grant.expires_at = time.monotonic() - 1
    assert tokens.get(grant.token) is None  # expired tokens are gone
    other = tokens.mint("call2", "python_execute", ttl=5)
    tokens.revoke(other.token)
    assert len(tokens) == 0


def test_pairs_parse_json_values_and_keep_strings():
    assert parse_pairs(["text=hello world", "count=3", "on=true", "when=07:30", 'tags=["a"]']) == {
        "text": "hello world",
        "count": 3,
        "on": True,
        "when": "07:30",
        "tags": ["a"],
    }
    assert parse_pairs(["with-dash=1"]) == {"with_dash": 1}
    with pytest.raises(SystemExit):
        parse_pairs(["novalue"])


# ----------------------------------------------------------------------------- the plan
def test_requests_map_to_tool_calls():
    plan = Bridge._plan
    assert plan("device", {"tool": "clipboard_read", "args": {}}) == ("device_clipboard_read", {})
    assert plan("device", {"tool": "alarm-set", "args": {"time": "07:30"}}) == (
        "device_alarm_set",
        {"time": "07:30"},
    )
    assert plan("browser", {"action": "navigate", "url": "https://example.com"}) == (
        "browser",
        {"action": "navigate", "url": "https://example.com"},
    )
    assert plan("browser", {"action": "type", "index": 3, "text": "hi", "submit": True}) == (
        "browser",
        {"action": "type", "index": 3, "text": "hi", "submit": True},
    )
    # fetch goes through the browser: a signed-in request with its cookies
    assert plan("browser", {"action": "fetch", "url": "https://example.com"}) == (
        "browser",
        {"action": "fetch", "url": "https://example.com"},
    )
    assert plan(
        "browser",
        {"action": "fetch", "url": "https://example.com", "method": "POST", "body": "a=1"},
    ) == (
        "browser",
        {"action": "fetch", "url": "https://example.com", "method": "POST", "body": "a=1"},
    )
    assert plan("browser", {"action": "profile", "profile": "desktop"}) == (
        "browser",
        {"action": "profile", "profile": "desktop"},
    )
    assert plan("open", {"url": "https://example.com/pay"}) == (
        "browser",
        {"action": "navigate", "url": "https://example.com/pay"},
    )
    for kind, body in [
        ("device", {"tool": ""}),
        ("device", {"tool": "rm -rf"}),
        ("browser", {"action": "explode"}),
        ("open", {"url": "file:///etc/passwd"}),
        ("teleport", {}),
    ]:
        with pytest.raises(BridgeError):
            plan(kind, body)


def test_bridge_url_prefers_the_loopback():
    assert bridge_url("0.0.0.0", 8787) == "http://127.0.0.1:8787"
    assert bridge_url("127.0.0.1", 1234) == "http://127.0.0.1:1234"
    assert bridge_url("::", 8787) == "http://[::1]:8787"
    assert bridge_url("192.168.1.20", 8787) == "http://192.168.1.20:8787"


# ----------------------------------------------------------------------------- the programs
def test_programs_say_when_the_bridge_is_not_here(monkeypatch, capsys):
    monkeypatch.delenv(BRIDGE_URL_ENV, raising=False)
    monkeypatch.delenv(BRIDGE_TOKEN_ENV, raising=False)
    assert device_main(["clipboard", "read"]) == 2
    assert browser_main(["extract"]) == 2
    assert open_main(["https://example.com"]) == 2
    assert "nanomuse serve" in capsys.readouterr().err


def test_client_reports_an_unreachable_server(monkeypatch):
    client = BridgeClient(url="http://127.0.0.1:9", token="t", timeout=1)
    result = client.post("device", {"tool": "clipboard_read", "args": {}})
    assert result["ok"] is False and "cannot reach" in result["error"]


# ----------------------------------------------------------------------------- where it runs
def test_device_is_read_from_the_environment():
    assert device({}) is None
    dev = device(
        {
            "NANOMUSE_DEVICE": "android",
            "NANOMUSE_DEVICE_MODEL": "Pixel 8",
            "NANOMUSE_DEVICE_SDK": "34",
            "NANOMUSE_HOST_URL": "http://127.0.0.1:41234/",
            "NANOMUSE_HOST_TOKEN": "h/t",
        }
    )
    assert dev == Device("android", "Pixel 8", "34", "http://127.0.0.1:41234", "h/t")
    assert dev.describe() == "on this phone (Pixel 8, Android 14)"
    assert dev.to_dict()["host"] is True
    server = device_mcp_server(dev)
    assert server.name == "device" and server.url == "http://127.0.0.1:41234/mcp?token=h%2Ft"
    assert server.reads_private_data is True
    assert Device("android", sdk="33").describe() == "on this phone (Android 13)"
    assert Device("android").describe() == "on this phone (Android)"


# ----------------------------------------------------------------------------- end to end
class FakeClipboard(BaseTool):
    """Stands in for the phone's `device_clipboard_read` (an MCP tool in real life)."""

    name: str = "device_clipboard_read"
    description: str = "Read the phone's clipboard."
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    risk: RiskLevel = RiskLevel.MODERATE

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(risk=self.risk, egress=False, summary="clipboard: read")

    async def execute(self, **_: Any) -> ToolResult:
        return ToolResult(output="hello from the clipboard")


def _bridge_command(*args: str) -> str:
    """Run the program from this interpreter (the venv's bin may not be on PATH here)."""
    code = f"from nanomuse.bridge.cli import device_main; raise SystemExit(device_main({list(args)!r}))"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def test_a_command_reaches_the_phone_through_the_bridge(settings: Settings):
    """The whole way round, on a real loopback port: the model runs a shell command, the
    command runs `nanomuse-device clipboard read`, the request comes back in as a tool call
    in the same chat, and its answer ends up in the command's output."""
    import threading

    import httpx
    import uvicorn

    settings.server.token = "secret-token"
    settings.sandbox.mode = "off"
    settings.sentinel.mode = "auto"
    llm = MockLLM([])
    service = MuseService(settings, llm=llm)
    service.app.tools.add(FakeClipboard())
    app = create_app(settings, service)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for(lambda: server.started)
    port = server.servers[0].sockets[0].getsockname()[1]
    service.bridge.base_url = bridge_url("127.0.0.1", port)
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}", headers={"Authorization": "Bearer secret-token"}
    )
    anon = httpx.Client(base_url=f"http://127.0.0.1:{port}")

    def tool_events() -> list[dict[str, Any]]:
        data = client.get("/api/threads/main/events").json()["events"]
        return [e for e in data if e["type"] == "tool"]

    try:
        llm.script.extend(
            [
                LLMResponse(tool_calls=[tc("shell", command=_bridge_command("clipboard", "read"))]),
                LLMResponse(content="Done."),
            ]
        )
        assert (
            client.post("/api/threads/main/send", json={"text": "read my clipboard"}).status_code
            == 200
        )
        wait_for(lambda: service.threads["main"].busy or not service.threads["main"].inbox.empty())
        wait_idle(service)
        tools = tool_events()
        shell = [e for e in tools if e["tool"] == "shell"][0]
        assert shell["status"] == "ok", shell
        assert "hello from the clipboard" in shell["output"]
        nested = [e for e in tools if e["tool"] == "device_clipboard_read"][0]
        assert nested["status"] == "ok" and nested["via"] == "shell"
        assert nested["output"] == "hello from the clipboard"
        # the call token died with the command
        assert len(service.bridge.tokens) == 0
        # without a token the endpoint refuses
        assert anon.post("/api/bridge/device", json={"tool": "clipboard_read"}).status_code == 401
        assert anon.get("/api/bridge/tools").status_code == 401
        # `list` names the device's tools without the prefix
        grant = service.bridge.tokens.mint("x", "shell", 5)
        auth = {"X-Nanomuse-Bridge": grant.token}
        r = anon.get("/api/bridge/tools", headers=auth)
        assert r.json()["tools"] == [
            {"name": "clipboard_read", "description": "Read the phone's clipboard."}
        ]
        # an unknown capability says what the phone does have
        r = anon.post(
            "/api/bridge/device", json={"tool": "photos_latest", "args": {}}, headers=auth
        )
        assert r.status_code == 200 and r.json()["ok"] is False
        assert "clipboard_read" in r.json()["error"]
        # the browser is off here
        r = anon.post("/api/bridge/open", json={"url": "https://example.com"}, headers=auth)
        assert r.json()["ok"] is False and "browser view is off" in r.json()["error"]
        # a bad request is a 400 with the reason
        r = anon.post("/api/bridge/browser", json={"action": "explode"}, headers=auth)
        assert r.status_code == 400 and "unknown browser action" in r.json()["detail"]
        assert json.dumps(r.json())  # serialisable
    finally:
        client.close()
        anon.close()
        server.should_exit = True
        thread.join(timeout=10)
