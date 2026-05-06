from __future__ import annotations

import json

from showcase_gateway.trials import TrialManager, TrialStore

from .conftest import Clock, body, make_settings


async def client_for(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:8000")


DEVICE = "8f3a9c2e-1b4d-4e6f-9a7b-0c1d2e3f4a5b"


async def test_a_phone_gets_a_trial_and_spends_it(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        r = await c.post(
            "/api/trial", json={"device": DEVICE}, headers={"x-forwarded-for": "1.2.3.4"}
        )
        assert r.status_code == 201, r.text
        trial = body(r)
        assert trial["key"].startswith("nmt_") and trial["model"] == "demo-model"
        assert trial["base_url"] == f"http://localhost:8000/llm/trial/{trial['id']}/main"
        assert trial["gui_base_url"].endswith("/gui")
        assert trial["tokens_limit"] == 1000 and trial["tokens_used"] == 0

        # the key opens the proxy; the upstream sees the real key and the model's own path
        auth = {"authorization": f"Bearer {trial['key']}"}
        r = await c.post(
            f"/llm/trial/{trial['id']}/main/chat/completions",
            json={"model": "demo-model", "messages": []},
            headers=auth,
        )
        assert r.status_code == 200 and body(r)["choices"]
        sent = upstream.calls[-1]
        assert sent.url == "https://models.example/chat/completions"
        assert sent.headers["authorization"] == "Bearer sk-demo"

        # status needs the key and shows what was spent
        assert (await c.get(f"/api/trial/{trial['id']}")).status_code == 401
        status = body(await c.get(f"/api/trial/{trial['id']}", headers=auth))
        assert status["tokens_used"] == 10 and status["requests"] == 1 and "key" not in status

        # a wrong key or id is refused in the OpenAI error shape
        r = await c.post(
            f"/llm/trial/{trial['id']}/main/chat/completions",
            json={},
            headers={"authorization": "Bearer nmt_wrong"},
        )
        assert r.status_code == 401 and body(r)["error"]["code"] == "bad_key"

        # the budget: 1000 tokens, 10 per call → the 100th call spends the last of it
        upstream.usage_total = 990
        r = await c.post(f"/llm/trial/{trial['id']}/main/chat/completions", json={}, headers=auth)
        assert r.status_code == 200
        r = await c.post(f"/llm/trial/{trial['id']}/main/chat/completions", json={}, headers=auth)
        assert r.status_code == 429 and body(r)["error"]["code"] == "trial_exhausted"
        status = body(await c.get(f"/api/trial/{trial['id']}", headers=auth))
        assert status["exhausted"] is True and status["tokens_remaining"] == 0

        info = body(await c.get("/api/demo/info"))
        assert info["trial"]["enabled"] is True
        assert info["trial"]["issued_total"] == 1 and info["trial"]["day_tokens"] == 1000


async def test_one_device_one_trial_and_the_caps(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        ip = {"x-forwarded-for": "9.9.9.9"}
        first = body(await c.post("/api/trial", json={"device": DEVICE}, headers=ip))
        # asking again from the same device rotates the key and keeps the count
        auth = {"authorization": f"Bearer {first['key']}"}
        await c.post(f"/llm/trial/{first['id']}/main/chat/completions", json={}, headers=auth)
        again = body(await c.post("/api/trial", json={"device": DEVICE}, headers=ip))
        assert again["id"] == first["id"] and again["key"] != first["key"]
        assert again["tokens_used"] == 10
        r = await c.post(f"/llm/trial/{first['id']}/main/chat/completions", json={}, headers=auth)
        assert r.status_code == 401  # the old key is gone

        # per address per day: two new trials, then no
        assert (
            await c.post("/api/trial", json={"device": "second-device-0002"}, headers=ip)
        ).status_code == 201
        r = await c.post("/api/trial", json={"device": "third-device-00003"}, headers=ip)
        assert r.status_code == 429 and body(r)["error"] == "trial_ip_limit"
        # a day later the address may again
        clock.now += 86400
        assert (
            await c.post("/api/trial", json={"device": "third-device-00003"}, headers=ip)
        ).status_code == 201
        # the daily total for everyone: 3 → the fourth new one today is refused
        other = {"x-forwarded-for": "8.8.8.8"}
        assert (
            await c.post("/api/trial", json={"device": "fourth-device-0004"}, headers=other)
        ).status_code == 201
        assert (
            await c.post("/api/trial", json={"device": "fifth-device-00005"}, headers=other)
        ).status_code == 201
        r = await c.post(
            "/api/trial",
            json={"device": "sixth-device-00006"},
            headers={"x-forwarded-for": "7.7.7.7"},
        )
        assert r.status_code == 429 and body(r)["error"] == "trial_daily_limit"

        # a device id must look like one
        r = await c.post("/api/trial", json={"device": "short"})
        assert r.status_code == 422


async def test_the_trial_rate_limit_and_switch(world):
    settings, runner, upstream, clock, manager, app = world
    async with app.router.lifespan_context(app):
        c = await client_for(app)
        trial = body(await c.post("/api/trial", json={"device": DEVICE}))
        auth = {"authorization": f"Bearer {trial['key']}"}
        for _ in range(5):
            r = await c.post(
                f"/llm/trial/{trial['id']}/gui/chat/completions", json={}, headers=auth
            )
            assert r.status_code == 200
        r = await c.post(f"/llm/trial/{trial['id']}/gui/chat/completions", json={}, headers=auth)
        assert r.status_code == 429 and body(r)["error"]["code"] == "trial_rate"
        clock.now += 61
        r = await c.post(f"/llm/trial/{trial['id']}/gui/chat/completions", json={}, headers=auth)
        assert r.status_code == 200
        assert upstream.calls[-1].url.host == "gui.example"  # the gui lane goes to the gui model


def test_trials_survive_a_restart(tmp_path):
    settings = make_settings()
    clock = Clock()
    path = tmp_path / "trials.db"
    trials = TrialManager(settings, TrialStore(path), clock=clock)
    trial, key = trials.issue(DEVICE, "1.1.1.1")
    trials.record(trial, 123)
    trials.store.close()

    reopened = TrialManager(settings, TrialStore(path), clock=clock)
    same = reopened.authenticate(trial.id, key)
    assert same.tokens == 123 and same.requests == 1
    assert reopened.stats()["issued_total"] == 1
    assert json.loads(json.dumps(same.public(settings)))["tokens_remaining"] == 877


def test_the_switch(world):
    settings = make_settings(trial_enabled=False)
    trials = TrialManager(settings, TrialStore(":memory:"), clock=Clock())
    try:
        trials.issue(DEVICE, "1.1.1.1")
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "code", "") == "trial_off"
    else:
        raise AssertionError("a switched-off trial was issued")
