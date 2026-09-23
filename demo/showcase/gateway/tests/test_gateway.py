from __future__ import annotations

import httpx
import pytest

from showcase_gateway.llm import extract_usage, prepare_body
from showcase_gateway.sessions import Refused, check_provider

from .conftest import body


async def client_for(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:8000")


async def test_a_visitor_gets_a_private_muse(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "1.2.3.4"})
        assert r.status_code == 201, r.text
        sess = body(r)
        assert sess["server_url"].startswith("http://") and sess["server_url"].endswith(
            ".s.localhost:8000"
        )
        assert sess["token"] and sess["ttl_s"] == 600 and sess["byok"] is False
        name = f"nm-{sess['id']}"
        env = runner.running[name]
        # the container's model lives behind this gateway, with a key of its own
        assert env["NANOMUSE_LLM_BASE_URL"] == f"http://10.0.0.1:8000/llm/{sess['id']}/main"
        assert env["NANOMUSE_GUI_BASE_URL"] == f"http://10.0.0.1:8000/llm/{sess['id']}/gui"
        assert env["NANOMUSE_LLM_API_KEY"] != settings.main.api_key
        assert env["NANOMUSE_SERVER_TOKEN"] == sess["token"]
        assert env["NANOMUSE_GUI_ENABLED"] == "1"
        # the phone's traffic on the session host reaches the container
        host = sess["server_url"].split("//")[1]
        r = await c.get("/api/state?token=x", headers={"host": host})
        assert r.status_code == 200 and r.text == "container says /api/state"
        assert r.headers["x-upstream"] == "yes"
        # one at a time per visitor
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "1.2.3.4"})
        assert r.status_code == 429 and body(r)["error"] == "already_running"
        # another visitor is fine
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "5.6.7.8"})
        assert r.status_code == 201
        # status needs the token; ending it stops the container
        r = await c.get(f"/api/demo/session/{sess['id']}")
        assert r.status_code == 404
        r = await c.get(
            f"/api/demo/session/{sess['id']}", headers={"authorization": f"Bearer {sess['token']}"}
        )
        assert r.status_code == 200 and body(r)["id"] == sess["id"]
        r = await c.delete(
            f"/api/demo/session/{sess['id']}", headers={"authorization": f"Bearer {sess['token']}"}
        )
        assert r.status_code == 204 and name in runner.stopped
        r = await c.get("/api/state", headers={"host": host})
        assert r.status_code == 404
        info = body(await c.get("/api/demo/info"))
        assert info["active_sessions"] == 1 and info["demo_model"] == "demo-model"


async def test_the_showcase_is_full_and_the_daily_count(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        for i in range(3):
            r = await c.post(
                "/api/demo/session", json={}, headers={"x-forwarded-for": f"9.9.9.{i}"}
            )
            assert r.status_code == 201
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "9.9.9.9"})
        assert r.status_code == 503 and body(r)["error"] == "full"
        # a visitor who starts and ends sessions all day hits the daily count
        for sid in list(manager.sessions):
            await manager.end(sid)
        for _ in range(2):
            r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "9.9.9.0"})
            assert r.status_code == 201
            await manager.end(body(r)["id"])
        r = await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "9.9.9.0"})
        assert r.status_code == 429 and body(r)["error"] == "daily_limit"


async def test_model_calls_are_metered(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        sess = body(await c.post("/api/demo/session", json={}))
        env = runner.running[f"nm-{sess['id']}"]
        key = env["NANOMUSE_LLM_API_KEY"]
        path = f"/llm/{sess['id']}/main/chat/completions"
        # wrong key
        r = await c.post(path, json={"model": "x"}, headers={"authorization": "Bearer nope"})
        assert r.status_code == 401
        # the demo key goes on, the container's key does not
        r = await c.post(path, json={"model": "x"}, headers={"authorization": f"Bearer {key}"})
        assert r.status_code == 200
        sent = upstream.calls[-1]
        assert sent.headers["authorization"] == "Bearer sk-demo"
        assert str(sent.url) == "https://models.example/chat/completions"
        # the gui lane has its own upstream
        r = await c.post(
            f"/llm/{sess['id']}/gui/chat/completions",
            json={"model": "x", "stream": True},
            headers={"authorization": f"Bearer {key}"},
        )
        assert r.status_code == 200
        sent = upstream.calls[-1]
        assert sent.headers["authorization"] == "Bearer sk-gui"
        assert str(sent.url) == "https://gui.example/chat/completions"
        assert b'"include_usage": true' in sent.content
        s = manager.get(sess["id"])
        assert s.requests == 2 and s.tokens == 20
        assert manager.day_requests == 2 and manager.day_tokens == 20
        # the third call is the last one allowed (3 per session), the fourth is refused
        upstream.stream = True
        r = await c.post(
            path, json={"model": "x", "stream": True}, headers={"authorization": f"Bearer {key}"}
        )
        assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
        assert s.requests == 3 and s.tokens == 30
        r = await c.post(path, json={"model": "x"}, headers={"authorization": f"Bearer {key}"})
        assert r.status_code == 429
        assert body(r)["error"]["type"] == "session_budget"


async def test_bring_your_own_key(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        r = await c.post(
            "/api/demo/session",
            json={
                "provider": {
                    "base_url": "http://byok.example/v1",
                    "api_key": "sk-visitor-1",
                    "model": "m",
                }
            },
        )
        assert r.status_code == 400 and body(r)["error"] == "bad_provider"
        r = await c.post(
            "/api/demo/session",
            json={
                "provider": {
                    "base_url": "https://evil.example/v1",
                    "api_key": "sk-visitor-1",
                    "model": "m",
                }
            },
        )
        assert r.status_code == 400 and body(r)["error"] == "provider_not_allowed"
        r = await c.post(
            "/api/demo/session",
            json={
                "provider": {
                    "base_url": "https://byok.example/v1/",
                    "api_key": "sk-visitor-1",
                    "model": "m",
                }
            },
        )
        assert r.status_code == 201, r.text
        sess = body(r)
        assert sess["byok"] is True and sess["quota"]["requests"] is None
        env = runner.running[f"nm-{sess['id']}"]
        assert env["NANOMUSE_LLM_MODEL"] == "m" and env["NANOMUSE_GUI_MODEL"] == "m"
        # the visitor's key never reaches the container
        assert "sk-visitor-1" not in env.values()
        key = env["NANOMUSE_LLM_API_KEY"]
        for _ in range(5):  # no budget of ours applies
            r = await c.post(
                f"/llm/{sess['id']}/main/chat/completions",
                json={"model": "m"},
                headers={"authorization": f"Bearer {key}"},
            )
            assert r.status_code == 200
        sent = upstream.calls[-1]
        assert sent.headers["authorization"] == "Bearer sk-visitor-1"
        assert str(sent.url) == "https://byok.example/v1/chat/completions"
        assert manager.day_requests == 0


async def test_sessions_end_on_their_own(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        a = body(await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "1.1.1.1"}))
        b = body(await c.post("/api/demo/session", json={}, headers={"x-forwarded-for": "2.2.2.2"}))
        clock.now += 130  # past the idle limit, both untouched
        await c.get("/api/state", headers={"host": f"{b['id']}.s.localhost"})  # b is in use
        await manager.reap_once()
        assert manager.get(a["id"]) is None and f"nm-{a['id']}" in runner.stopped
        assert manager.get(b["id"]) is not None
        clock.now += 600  # past the session's whole lifetime
        await manager.reap_once()
        assert manager.get(b["id"]) is None


def test_check_provider_refuses_private_addresses():
    def resolve(host: str, port: int) -> list[str]:
        return {"models.example": ["93.184.216.34"], "inside.example": ["10.1.2.3"]}[host]

    with pytest.raises(Refused) as exc:
        check_provider("https://inside.example/v1", ("inside.example",), resolve)
    assert exc.value.code == "bad_provider"
    with pytest.raises(Refused) as exc:
        check_provider("https://models.example:8443/v1", ("models.example",), lambda h, p: [])
    assert exc.value.code == "bad_provider"
    assert (
        check_provider("https://models.example/v1/", ("models.example",), resolve)
        == "https://models.example/v1"
    )


def test_usage_parsing():
    assert extract_usage(b'{"usage": {"prompt_tokens": 3, "completion_tokens": 4}}') == 7
    sse = b'data: {"x":1}\n\ndata: {"usage":{"total_tokens":42}}\n\ndata: [DONE]\n\n'
    assert extract_usage(sse) == 42
    responses = b'data: {"type":"response.completed","response":{"usage":{"input_tokens":5,"output_tokens":6}}}\n\n'
    assert extract_usage(responses) == 11
    assert extract_usage(b"nothing here") is None
    assert prepare_body(b'{"stream": false}', "chat/completions") == b'{"stream": false}'
    assert b"include_usage" in prepare_body(b'{"stream": true}', "v1/chat/completions")
    assert prepare_body(b'{"stream": true}', "responses") == b'{"stream": true}'
