from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from showcase_gateway.app import create_app
from showcase_gateway.config import Lane, Settings
from showcase_gateway.sessions import SessionManager


class FakeRunner:
    """Containers that exist only as names; every one comes up at 10.0.0.<n>."""

    def __init__(self) -> None:
        self.running: dict[str, dict[str, str]] = {}
        self.stopped: list[str] = []

    async def start(self, name: str, env: dict[str, str]) -> str:
        self.running[name] = env
        return f"10.0.0.{len(self.running) + 1}"

    async def stop(self, name: str) -> None:
        self.running.pop(name, None)
        self.stopped.append(name)

    async def leftovers(self) -> list[str]:
        return []

    async def gateway_address(self) -> str | None:
        return "10.0.0.1"


class Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


def make_settings(**over) -> Settings:
    base = Settings.from_env()
    values = dict(
        public_scheme="http",
        site_host="localhost",
        session_domain="s.localhost",
        public_port=":8000",
        trust_proxy=True,
        site_dir="",
        cdn_dir="",
        image="nanomuse:test",
        internal_url="",
        session_ttl_s=600,
        idle_ttl_s=120,
        start_timeout_s=5,
        max_sessions=3,
        per_ip_active=1,
        per_ip_daily=3,
        main=Lane("openai", "demo-model", "https://models.example", "sk-demo"),
        gui=Lane("openai", "gui-model", "https://gui.example", "sk-gui"),
        session_requests=3,
        session_tokens=1000,
        daily_requests=100,
        daily_tokens=100_000,
        byok_hosts=("models.example", "byok.example", "localhost"),
    )
    values.update(over)
    return replace(base, **values)


class Wire(httpx.AsyncByteStream):
    """A response body that is still on the wire, as the gateway sees real ones."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    async def __aiter__(self):
        yield self.data


def wire(status: int, text: str, **headers: str) -> httpx.Response:
    return httpx.Response(status, stream=Wire(text.encode()), headers=headers)


class Upstream:
    """Stands in for the containers (``/api/health``, the app) and the model providers."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.usage_total = 10
        self.stream = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.url.path == "/api/health":
            return wire(200, '{"ok": true}', **{"content-type": "application/json"})
        if request.url.host.startswith("10.0.0."):
            return wire(200, f"container says {request.url.path}", **{"x-upstream": "yes"})
        # a model provider
        if self.stream:
            body = (
                'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
                f'data: {{"choices":[],"usage":{{"total_tokens":{self.usage_total}}}}}\n\n'
                "data: [DONE]\n\n"
            )
            return wire(200, body, **{"content-type": "text/event-stream"})
        return wire(
            200,
            json.dumps(
                {
                    "choices": [{"message": {"content": "hi"}}],
                    "usage": {"total_tokens": self.usage_total},
                }
            ),
            **{"content-type": "application/json"},
        )


@pytest.fixture
def world():
    settings = make_settings()
    runner = FakeRunner()
    upstream = Upstream()
    clock = Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler))
    manager = SessionManager(settings, runner, http=client, clock=clock)
    manager.resolve = lambda host, port: ["93.184.216.34"]
    app = create_app(settings, manager, client=client)
    return settings, runner, upstream, clock, manager, app


def body(resp: httpx.Response) -> dict:
    return json.loads(resp.content)
