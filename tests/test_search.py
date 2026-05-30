"""Web search providers: DuckDuckGo by default, Brave / Tavily / SearXNG by settings, the
fallback to DuckDuckGo with a note, keys from the vault, the tool, the API and the doctor."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from openmuse import search as search_mod
from openmuse.config import SearchSettings, Settings, apply_app_settings, load_app_settings
from openmuse.llm import MockLLM
from openmuse.search import SearchResult, WebSearchProvider, _region
from openmuse.server.api import create_app
from openmuse.server.service import MuseService
from openmuse.tools import WebSearch
from openmuse.vault import CredentialVault

DDG_ROWS = [
    {"title": "OpenMuse", "href": "https://github.com/OpenMuseAgent/OpenMuse", "body": "An agent."},
    {"title": "Muse", "href": "https://example.com/muse", "body": "Something else."},
]


class Wire:
    """Answers the HTTP a provider sends; records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.body: Any = {}
        self.text: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.text is not None:
            return httpx.Response(self.status, text=self.text)
        return httpx.Response(self.status, json=self.body)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            search_mod,
            "_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.handler)),
        )


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    w = Wire()
    w.install(monkeypatch)
    return w


@pytest.fixture
def ddg(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """DuckDuckGo answers from a list instead of the network; records the calls."""
    calls: list[dict[str, Any]] = []

    async def fake(query: str, max_results: int, region: str) -> list[SearchResult]:
        calls.append({"query": query, "max_results": max_results, "region": region})
        return [
            SearchResult(title=r["title"], url=r["href"], snippet=r["body"])
            for r in DDG_ROWS[:max_results]
        ]

    monkeypatch.setattr(WebSearchProvider, "_ddg", staticmethod(fake))
    return calls


def test_region_codes():
    assert _region("") == ("", "")
    assert _region("wt-wt") == ("", "")
    assert _region("cn-zh") == ("CN", "zh")
    assert _region("US-EN") == ("US", "en")
    assert _region("nonsense") == ("", "")


async def test_duckduckgo_is_the_default(ddg):
    p = WebSearchProvider(SearchSettings())
    assert p.name == "duckduckgo" and p.configured and p.host == "duckduckgo.com"
    assert p.describe() == "DuckDuckGo (no key needed)"
    results, note = await p.search("openmuse", 1, "cn-zh")
    assert note == "" and [r.title for r in results] == ["OpenMuse"]
    assert ddg == [{"query": "openmuse", "max_results": 1, "region": "cn-zh"}]


async def test_brave(wire: Wire, ddg):
    wire.body = {
        "web": {
            "results": [
                {"title": "A", "url": "https://a.example", "description": " first "},
                {"title": "B", "url": "https://b.example", "description": "second"},
                {"title": "C", "url": "https://c.example", "description": "third"},
            ]
        }
    }
    p = WebSearchProvider(SearchSettings(provider="brave", api_key="brv-key"))
    assert p.configured and p.host == "api.search.brave.com"
    assert p.describe() == "Brave Search (key set)"
    results, note = await p.search("openmuse", 2, "cn-zh")
    assert note == "" and ddg == []
    assert [(r.title, r.snippet) for r in results] == [("A", "first"), ("B", "second")]
    req = wire.requests[0]
    assert req.method == "GET" and req.url.host == "api.search.brave.com"
    assert req.headers["X-Subscription-Token"] == "brv-key"
    assert req.url.params["q"] == "openmuse" and req.url.params["count"] == "2"
    assert req.url.params["country"] == "CN" and req.url.params["search_lang"] == "zh"
    # no region → no country/lang parameters
    await p.search("x", 1, "")
    assert "country" not in wire.requests[1].url.params


async def test_tavily(wire: Wire, ddg):
    wire.body = {
        "results": [
            {"title": "T", "url": "https://t.example", "content": "x" * 1000},
        ]
    }
    p = WebSearchProvider(SearchSettings(provider="tavily", api_key="tvly-key"))
    results, note = await p.search("openmuse", 5, "")
    assert note == "" and ddg == []
    assert results[0].title == "T" and len(results[0].snippet) == 400
    req = wire.requests[0]
    assert req.method == "POST" and req.url == "https://api.tavily.com/search"
    assert req.headers["Authorization"] == "Bearer tvly-key"
    assert json.loads(req.content) == {
        "query": "openmuse",
        "max_results": 5,
        "search_depth": "basic",
    }


async def test_searxng(wire: Wire, ddg):
    wire.body = {"results": [{"title": "S", "url": "https://s.example", "content": "from searx"}]}
    p = WebSearchProvider(SearchSettings(provider="searxng", base_url="http://127.0.0.1:8080/"))
    assert p.configured and p.host == "127.0.0.1"
    assert p.describe() == "SearXNG at http://127.0.0.1:8080/"
    results, note = await p.search("openmuse", 3, "cn-zh")
    assert note == "" and results[0].snippet == "from searx" and ddg == []
    req = wire.requests[0]
    assert str(req.url).startswith("http://127.0.0.1:8080/search?")
    assert req.url.params["format"] == "json" and req.url.params["language"] == "zh-CN"
    await p.search("x", 1, "")
    assert "language" not in wire.requests[1].url.params
    # a SearXNG that is not one (HTML instead of JSON) is a clear error, not a traceback
    wire.text = "<html>not a search api</html>"
    results, note = await p.search("openmuse", 3, "")
    assert "not JSON" in note and "results from DuckDuckGo" in note
    assert [r.title for r in results] == ["OpenMuse", "Muse"]


async def test_failures_fall_back_to_duckduckgo_with_a_note(
    wire: Wire, ddg, monkeypatch: pytest.MonkeyPatch
):
    p = WebSearchProvider(SearchSettings(provider="brave", api_key="k"))
    wire.status = 429
    results, note = await p.search("openmuse", 2, "")
    assert (
        results
        and note == "Brave Search failed (rate limited (HTTP 429)) — results from DuckDuckGo"
    )
    wire.status = 401
    _, note = await p.search("openmuse", 2, "")
    assert "the key was refused (HTTP 401)" in note
    wire.status = 500
    wire.text = "boom"
    _, note = await p.search("openmuse", 2, "")
    assert "HTTP 500: boom" in note
    assert len(ddg) == 3

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("")

    monkeypatch.setattr(
        search_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(unreachable))
    )
    _, note = await p.search("openmuse", 2, "")
    assert (
        note
        == "Brave Search failed (could not reach api.search.brave.com) — results from DuckDuckGo"
    )
    wire.install(monkeypatch)
    # the probe (the test button) does not fall back
    wire.status = 429
    wire.text = None
    r = await p.probe()
    assert r["ok"] is False and "rate limited" in r["error"] and len(ddg) == 4


async def test_unconfigured_provider_uses_duckduckgo_and_says_so(wire: Wire, ddg):
    p = WebSearchProvider(SearchSettings(provider="brave"))
    assert not p.configured and p.describe() == "Brave Search (no key)"
    results, note = await p.search("openmuse", 2, "")
    assert results and note == "Brave Search: no API key — results from DuckDuckGo"
    assert wire.requests == []
    p = WebSearchProvider(SearchSettings(provider="searxng"))
    assert not p.configured
    _, note = await p.search("openmuse", 2, "")
    assert note == "SearXNG: no instance URL — results from DuckDuckGo"


async def test_key_from_the_vault(tmp_path, wire: Wire):
    vault = CredentialVault(tmp_path / "vault")
    p = WebSearchProvider(
        SearchSettings(provider="tavily", api_key="{{vault:SEARCH_API_KEY}}"), vault=vault
    )
    assert p.api_key() == "" and not p.configured  # placeholder, nothing behind it
    vault.set("SEARCH_API_KEY", "tvly-real")
    assert p.api_key() == "tvly-real" and p.configured
    wire.body = {"results": []}
    await p.probe()
    assert wire.requests[0].headers["Authorization"] == "Bearer tvly-real"


async def test_probe_reports_the_provider(wire: Wire):
    wire.body = {"web": {"results": [{"title": "Hit", "url": "https://h", "description": "d"}]}}
    p = WebSearchProvider(SearchSettings(provider="brave", api_key="k"))
    r = await p.probe()
    assert r["ok"] and r["provider"] == "Brave Search" and r["results"] == 1
    assert r["first"] == "Hit" and isinstance(r["ms"], int)


async def test_tool_renders_results_and_the_note(wire: Wire, ddg):
    tool = WebSearch(provider=WebSearchProvider(SearchSettings(provider="brave", api_key="k")))
    assessment = tool.assess({"query": "q"})
    assert assessment.egress_target == "api.search.brave.com" and assessment.egress_configured
    wire.body = {
        "web": {"results": [{"title": "A", "url": "https://a.example", "description": "first"}]}
    }
    out = await tool.execute(query="openmuse", max_results=1)
    assert out.output == "1. A\n   https://a.example\n   first"
    wire.status = 429
    out = await tool.execute(query="openmuse", max_results=2)
    lines = out.output.splitlines()
    assert lines[0].startswith("(Brave Search failed") and lines[1] == "1. OpenMuse"
    assert (await tool.execute(query="  ")).error
    # the default tool is DuckDuckGo
    plain = WebSearch()
    assert plain.provider.name == "duckduckgo"
    assert plain.assess({"query": "q"}).egress_target == "duckduckgo.com"


def test_settings_layering(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    apply_app_settings(
        settings,
        {"search": {"provider": "searxng", "base_url": "http://searx.lan:8080/", "api_key": None}},
    )
    web = settings.connectors.search
    assert web.provider == "searxng" and web.base_url == "http://searx.lan:8080"
    apply_app_settings(settings, {"search": {"provider": "nonsense"}})
    assert web.provider == "searxng"  # ignored, not crashed
    apply_app_settings(settings, {"search": {"api_key": "{{vault:SEARCH_API_KEY}}"}})
    assert web.api_key == "{{vault:SEARCH_API_KEY}}"
    # environment variables
    monkeypatch.chdir(settings.data_dir)  # no ./config/config.toml here
    monkeypatch.delenv("OPENMUSE_CONFIG", raising=False)
    monkeypatch.setenv("OPENMUSE_SEARCH_PROVIDER", "brave")
    monkeypatch.setenv("OPENMUSE_SEARCH_API_KEY", "env-key")
    monkeypatch.setenv("OPENMUSE_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENMUSE_WORKSPACE", str(settings.agent.workspace))
    from openmuse.config import load_settings

    loaded = load_settings(None)
    assert loaded.connectors.search.provider == "brave"
    assert loaded.connectors.search.api_key == "env-key"


def test_connections_search(settings: Settings, wire: Wire, ddg):
    settings.server.token = "secret-token"
    service = MuseService(settings, llm=MockLLM([]))
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        view = client.get("/api/connections").json()["search"]
        assert view["provider"] == "duckduckgo" and view["configured"] and not view["from_app"]
        assert view["key_source"] == "none"
        assert [p["id"] for p in view["providers"]] == ["duckduckgo", "brave", "tavily", "searxng"]
        assert view["providers"][1]["needs_key"] and view["providers"][1]["keys_url"]

        # Brave without a key: allowed, but not configured — searches fall back
        r = client.put("/api/connections/search", json={"provider": "brave"})
        assert r.status_code == 200
        view = r.json()
        assert view["provider"] == "brave" and view["configured"] is False and view["from_app"]
        r = client.post("/api/connections/search/test").json()
        assert r["ok"] is False and "needs an API key" in r["error"]
        tool = service.app.tools.get("web_search")
        assert isinstance(tool, WebSearch) and tool.provider.name == "brave"

        # the key goes to the vault, never into the settings file
        r = client.put("/api/connections/search", json={"api_key": " brv-key "}).json()
        assert r["key_source"] == "vault" and r["configured"] is True
        assert service.app.vault.get("SEARCH_API_KEY") == "brv-key"
        saved = load_app_settings(settings.data_dir)
        assert saved["search"] == {"provider": "brave", "api_key": "{{vault:SEARCH_API_KEY}}"}
        wire.body = {"web": {"results": [{"title": "Hit", "url": "https://h", "description": "d"}]}}
        r = client.post("/api/connections/search/test").json()
        assert r["ok"] and r["provider"] == "Brave Search" and r["results"] == 1
        assert wire.requests[-1].headers["X-Subscription-Token"] == "brv-key"

        # removing the key
        r = client.put("/api/connections/search", json={"api_key": ""}).json()
        assert r["key_source"] == "none" and r["configured"] is False
        assert service.app.vault.get("SEARCH_API_KEY") is None

        # SearXNG by URL; bad input is a 400
        assert client.put("/api/connections/search", json={"provider": "bing"}).status_code == 400
        assert (
            client.put("/api/connections/search", json={"base_url": "ftp://x"}).status_code == 400
        )
        r = client.put(
            "/api/connections/search",
            json={"provider": "searxng", "base_url": "http://127.0.0.1:8080/"},
        ).json()
        assert r["provider"] == "searxng" and r["base_url"] == "http://127.0.0.1:8080"
        assert r["configured"] is True
        assert tool.provider.host == "127.0.0.1"

        # back to DuckDuckGo: the test runs a real (here: faked) search
        r = client.put("/api/connections/search", json={"provider": "duckduckgo"}).json()
        assert r["configured"] is True
        r = client.post("/api/connections/search/test").json()
        assert r["ok"] and r["provider"] == "DuckDuckGo" and r["results"] == 2
