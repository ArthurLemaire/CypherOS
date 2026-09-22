"""Recall by meaning: the embedding client, the vector index, the fused ranking, and the
places they plug in — the agent's system prompt, the recall tool, the Connections API.

The endpoint is a fake with four "concept" axes (travel, food, people, work) chosen by
keywords in either language, so "写邮件给房东" and "the landlord is Bob Li" share an axis
while sharing no word — the case keyword recall cannot do.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from openmuse.agent import MuseAgent
from openmuse.config import LLMSettings, MemorySettings, Settings, apply_app_settings
from openmuse.llm import MockLLM
from openmuse.memory import Embedder, MemoryIndex, MemoryStore
from openmuse.memory import embeddings as emb_mod
from openmuse.memory.embeddings import cosine, default_model, fuse, standouts
from openmuse.memory.store import MemoryItem
from openmuse.schema import LLMResponse
from openmuse.sentinel import AuditLog, Sentinel
from openmuse.server.api import create_app
from openmuse.server.service import MuseService
from openmuse.tools import Recall, Terminate, ToolCollection
from openmuse.ui import HeadlessUI

AXES = {
    0: ("flight", "fly", "seat", "window", "机票", "飞机", "tokyo", "trip"),
    1: ("cook", "dinner", "vegetarian", "mushroom", "做饭", "晚饭"),
    2: ("landlord", "rent", "bob", "房东", "写邮件给房东"),
    3: ("alice", "meeting", "1:1", "会议"),
}


def fake_vector(text: str) -> list[float]:
    """Four concept axes plus eight dims of per-text noise, so that texts on the same axis
    are close, texts on different axes are not, and texts on no axis are not close to
    anything in particular."""
    low = text.lower()
    axes = [1.0 if any(w in low for w in words) else 0.0 for words in AXES.values()]
    digest = hashlib.sha1(low.encode()).digest()
    noise = [(b - 128) / 128 for b in digest[:8]]
    norm = math.sqrt(sum(n * n for n in noise)) or 1.0
    return axes + [0.3 * n / norm for n in noise]


DIMS = len(fake_vector("x"))


class FakeEmbeddings:
    """An OpenAI-compatible /embeddings with a switchable failure."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.fail: int | None = None  # an HTTP status to answer with instead

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append(
            {"path": request.url.path, "model": body.get("model"), "n": len(body["input"])}
        )
        if self.fail:
            # Ollama's wording for a model that is not pulled
            msg = (
                f'model "{body.get("model")}" not found, try pulling it first'
                if self.fail == 404
                else f"status {self.fail}"
            )
            return httpx.Response(self.fail, json={"error": {"message": msg, "type": "x"}})
        texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": body.get("model"),
                "data": [
                    {"object": "embedding", "index": i, "embedding": fake_vector(t)}
                    for i, t in enumerate(texts)
                ],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def make(**kw: Any) -> AsyncOpenAI:
            # one transport per client: an Embedder closes its client when replaced
            kw["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
            return AsyncOpenAI(**kw)

        monkeypatch.setattr(emb_mod, "AsyncOpenAI", make)


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeEmbeddings:
    f = FakeEmbeddings()
    f.install(monkeypatch)
    return f


def seed(store: MemoryStore) -> None:
    for text in (
        "Prefers a window seat when flying",
        "The landlord is Bob Li, bob@example.com",
        "Vegetarian; no mushrooms",
        "Weekly 1:1 with Alice on Thursdays",
        "Lives in Shenzhen, works remotely",
        "Timezone UTC+8",
    ):
        store.add(text)


def ollama(**kw: Any) -> Embedder:
    return Embedder(
        MemorySettings(embedding_base_url="http://127.0.0.1:11434/v1", **kw),
        LLMSettings(base_url="https://api.deepseek.com", api_key="sk-chat"),
    )


# ----------------------------------------------------------------------------- pure functions
def test_default_model_by_endpoint():
    assert default_model("http://127.0.0.1:11434/v1") == "qwen3-embedding:0.6b"
    assert default_model("https://openrouter.ai/api/v1") == "openai/text-embedding-3-small"
    assert default_model("https://api.openai.com/v1") == "text-embedding-3-small"
    assert default_model("https://gateway.corp/v1") == "text-embedding-3-small"


def test_cosine_fuse_and_standouts():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 1]) == 0.0
    items = [
        MemoryItem(id=f"m{i}", content=f"c{i}", category="x", created_at="", source="")
        for i in range(5)
    ]
    # 2nd in both lists beats 1st in one
    fused = fuse([items[0], items[1]], [items[2], items[1]], limit=3)
    assert [m.id for m in fused] == ["m1", "m0", "m2"]
    # a stand-out needs to be a standard deviation above the mean once there are enough
    scored = [(0.4, items[0]), (0.41, items[1]), (0.39, items[2]), (0.4, items[3]), (0.9, items[4])]
    scored += [
        (0.4, MemoryItem(id=f"n{i}", content="", category="", created_at="", source=""))
        for i in range(4)
    ]
    assert [m.id for m in standouts(scored, limit=3)] == ["m4"]
    # with only a few, above the mean is enough
    few = [(0.5, items[0]), (0.3, items[1]), (0.6, items[2])]
    assert [m.id for m in standouts(few, limit=3)] == ["m2", "m0"]
    assert standouts([], limit=3) == []


# ----------------------------------------------------------------------------- the client
async def test_embedder_batches_and_reports(fake: FakeEmbeddings):
    e = ollama()
    assert e.usable and e.available is None and "not tried yet" in e.status
    vectors = await e.embed([f"text {i}" for i in range(70)])
    assert vectors is not None and len(vectors) == 70 and e.dims == DIMS
    assert [r["n"] for r in fake.requests] == [64, 6]
    assert fake.requests[0]["model"] == "qwen3-embedding:0.6b"
    assert fake.requests[0]["path"] == "/v1/embeddings"
    assert e.available is True and f"{DIMS} dims" in e.status
    assert await e.embed([]) is None
    await e.close()


async def test_embedder_gives_up_on_a_missing_endpoint_in_auto(fake: FakeEmbeddings):
    fake.fail = 404
    e = ollama()
    assert await e.embed(["x"]) is None
    assert e.available is False and not e.usable
    assert "ollama pull qwen3-embedding:0.6b" in e.reason
    # not asked again this run — one failed call, not one per turn
    assert await e.embed(["y"]) is None
    assert len(fake.requests) == 1
    # a test button or the doctor may insist
    e.reset()
    assert e.usable and e.available is None
    fake.fail = None
    assert await e.embed(["z"]) is not None and e.available is True
    await e.close()


async def test_embedder_retries_a_flaky_endpoint_later(fake: FakeEmbeddings):
    fake.fail = 500
    e = ollama()
    assert await e.embed(["x"]) is None and not e.usable
    assert "127.0.0.1:11434" in e.reason and not e._given_up
    # the client retried once on its own; we do not pile on
    assert len(fake.requests) == 2
    assert await e.embed(["x"]) is None and len(fake.requests) == 2
    # ...until the retry window has passed
    e._retry_at = time.monotonic() - 1
    assert e.usable
    fake.fail = None
    assert await e.embed(["x"]) is not None
    await e.close()


async def test_embedder_in_on_mode_never_gives_up(fake: FakeEmbeddings):
    fake.fail = 404
    e = ollama(embeddings="on")
    assert await e.embed(["x"]) is None
    assert not e._given_up and e.available is False
    await e.close()


def test_known_endpoint_without_embeddings_is_not_called(fake: FakeEmbeddings):
    e = Embedder(MemorySettings(), LLMSettings(base_url="https://api.deepseek.com", api_key="sk"))
    assert e.available is False and not e.usable
    assert "embedding_base_url" in e.reason and "keyword" in e.reason
    e.reset()  # nothing to retry: there is no endpoint
    assert not e.usable
    # pointed elsewhere, the chat endpoint no longer matters
    assert ollama().usable
    off = Embedder(MemorySettings(embeddings="off"), LLMSettings(api_key="sk"))
    assert not off.enabled and off.status == "off"


def test_embedder_headers_follow_the_endpoint():
    llm = LLMSettings(base_url="https://gw.corp/v1", api_key="k", extra_headers={"X-User": "u"})
    same = Embedder(MemorySettings(), llm)
    assert same.client.default_headers.get("X-User") == "u"
    assert same.base_url == "https://gw.corp/v1"
    other = Embedder(MemorySettings(embedding_base_url="http://127.0.0.1:11434/v1/"), llm)
    assert other.client.default_headers.get("X-User") is None
    assert other.base_url == "http://127.0.0.1:11434/v1"


# ----------------------------------------------------------------------------- the index
async def test_index_finds_by_meaning_and_keeps_vectors(tmp_path: Path, fake: FakeEmbeddings):
    store = MemoryStore(tmp_path / "m.db")
    seed(store)
    e = ollama()
    store.index = MemoryIndex(store, e)

    # no word in common, same meaning
    assert store.search("写邮件给房东") == []
    hits = await store.search_async("写邮件给房东", limit=3)
    assert hits and hits[0].content.startswith("The landlord")
    # keyword and meaning agree → top; the fused list carries both kinds
    hits = await store.search_async("book a flight, window seat please", limit=3)
    assert hits[0].content.startswith("Prefers a window seat")
    # every memory embedded in one batch, the query in another
    assert [r["n"] for r in fake.requests[:2]] == [6, 1]
    stored = store.vectors("qwen3-embedding:0.6b")
    assert len(stored) == 6 and all(len(v) == DIMS for _, v in stored.values())

    # a changed memory is embedded again; a forgotten one loses its vector
    alice = next(m for m in store.all() if "Alice" in m.content)
    store.update(alice.id, "Weekly 1:1 with Alice moved to Fridays")
    tz = next(m for m in store.all() if "UTC" in m.content)
    store.forget(tz.id)
    before = len(fake.requests)
    await store.search_async("meeting with alice", limit=2)
    assert len(fake.requests) == before + 2  # one re-embed, one query
    assert fake.requests[before]["n"] == 1
    stored = store.vectors("qwen3-embedding:0.6b")
    assert tz.id not in stored and len(stored) == 5
    status = store.index.status()
    assert status["indexed"] == 5 and status["total"] == 5 and status["available"] is True

    # a new index over the same store starts from the stored vectors: only the query is embedded
    fresh = MemoryIndex(store, ollama())
    before = len(fake.requests)
    assert (await fresh.search("房东", limit=1))[0].content.startswith("The landlord")
    assert len(fake.requests) == before + 1

    # closest, with the cosines, for the CLI
    top = await store.index.closest("做饭 dinner", limit=2)
    assert top[0][1].content.startswith("Vegetarian") and top[0][0] > top[1][0]
    store.close()


async def test_index_falls_back_to_keywords_when_the_endpoint_is_down(
    tmp_path: Path, fake: FakeEmbeddings
):
    store = MemoryStore(tmp_path / "m.db")
    seed(store)
    fake.fail = 503
    store.index = MemoryIndex(store, ollama())
    hits = await store.search_async("window seat", limit=3)
    assert hits[0].content.startswith("Prefers a window seat")
    assert await store.search_async("写邮件给房东", limit=3) == []
    assert (
        len(fake.requests) == 2
    )  # one call (and the client's own retry); not asked again right away
    rel = await store.relevant_async("anything", limit=3)
    assert len(rel) == 3
    store.close()


async def test_relevant_async_fills_with_recent(tmp_path: Path, fake: FakeEmbeddings):
    store = MemoryStore(tmp_path / "m.db")
    seed(store)
    store.index = MemoryIndex(store, ollama())
    rel = await store.relevant_async("写邮件给房东", limit=4)
    assert rel[0].content.startswith("The landlord") and len(rel) == 4
    assert len({m.id for m in rel}) == 4
    # few enough memories: all of them, no call at all
    small = MemoryStore(tmp_path / "s.db")
    small.add("one")
    small.index = MemoryIndex(small, ollama())
    before = len(fake.requests)
    assert len(await small.relevant_async("x", limit=20)) == 1 and len(fake.requests) == before
    store.close()
    small.close()


# ----------------------------------------------------------------------------- settings
def test_settings_and_app_layering(settings: Settings):
    assert settings.memory.embeddings == "auto" and settings.memory.embedding_model == ""
    apply_app_settings(
        settings,
        {
            "embeddings": {
                "mode": "on",
                "base_url": "http://127.0.0.1:11434/v1/",
                "model": "bge-m3",
                "api_key": "",
            }
        },
    )
    m = settings.memory
    assert (m.embeddings, m.embedding_base_url, m.embedding_model, m.embedding_api_key) == (
        "on",
        "http://127.0.0.1:11434/v1",
        "bge-m3",
        "",
    )
    apply_app_settings(settings, {"embeddings": {"mode": "sideways", "model": None}})
    assert m.embeddings == "on" and m.embedding_model == "bge-m3"
    assert MemorySettings(embedding_base_url="http://x/").embedding_base_url == "http://x"


# ----------------------------------------------------------------------------- the agent
async def test_agent_recalls_by_meaning_into_the_prompt(settings: Settings, fake: FakeEmbeddings):
    settings.memory.embedding_base_url = "http://127.0.0.1:11434/v1"
    settings.memory.max_inject = 2
    memory = MemoryStore(settings.memory_db)
    seed(memory)
    memory.index = MemoryIndex(memory, Embedder(settings.memory, settings.llm))
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    llm = MockLLM([LLMResponse(content="Sure — drafting to Bob.")])
    agent = MuseAgent(
        settings,
        llm,
        ToolCollection(Terminate(), Recall(store=memory)),
        Sentinel(settings.sentinel, audit, ui),
        ui,
        audit,
        memory=memory,
    )
    await agent.run("写邮件给房东，问下周能不能修水龙头")
    system = llm.calls[0]["messages"][0].content
    assert "The landlord is Bob Li" in system
    section = system.split("## What you remember about the user", 1)[1].split("\n##", 1)[0]
    listed = [ln for ln in section.splitlines() if ln.startswith("- ")]
    assert len(listed) == 2 and "landlord" in listed[0]  # max_inject respected, the match first
    # the recall tool goes through the fused search as well
    out = await Recall(store=memory).execute(query="给房东写信", limit=2)
    assert "landlord" in out.output
    memory.close()


async def test_agent_survives_a_recall_error(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    memory = MemoryStore(settings.memory_db)
    seed(memory)

    class Broken:
        async def search(self, *_: Any, **__: Any) -> list[MemoryItem]:
            raise RuntimeError("index exploded")

    memory.index = Broken()  # type: ignore[assignment]
    settings.memory.max_inject = 2
    ui = HeadlessUI()
    audit = AuditLog(settings.audit_file)
    llm = MockLLM([LLMResponse(content="ok")])
    agent = MuseAgent(
        settings,
        llm,
        ToolCollection(Terminate()),
        Sentinel(settings.sentinel, audit, ui),
        ui,
        audit,
        memory=memory,
    )
    await agent.run("window seat?")
    assert "Prefers a window seat" in llm.calls[0]["messages"][0].content
    memory.close()


# ----------------------------------------------------------------------------- the app and the API
def test_connections_embeddings(settings: Settings, fake: FakeEmbeddings):
    settings.server.token = "secret-token"
    settings.llm.base_url = "https://api.deepseek.com"
    service = MuseService(settings, llm=MockLLM([]))
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        seed(service.app.memory)
        view = client.get("/api/connections").json()["embeddings"]
        assert view["mode"] == "auto" and view["memory_enabled"] and view["available"] is False
        assert "embedding_base_url" in view["reason"] and view["key_source"] == "model"
        assert view["default_model"] == "text-embedding-3-small"
        # DeepSeek has none: the test says so without a call
        r = client.post("/api/connections/embeddings/test").json()
        assert r["ok"] is False and "embedding_base_url" in r["error"] and fake.requests == []

        # point it at Ollama next door
        r = client.put(
            "/api/connections/embeddings",
            json={"base_url": "http://127.0.0.1:11434/v1", "api_key": ""},
        )
        assert r.status_code == 200
        view = r.json()
        assert view["base_url"] == "http://127.0.0.1:11434/v1" and view["from_app"]
        assert view["default_model"] == "qwen3-embedding:0.6b" and view["available"] is None
        assert (
            client.put("/api/connections/embeddings", json={"base_url": "ftp://x"}).status_code
            == 400
        )
        assert client.put("/api/connections/embeddings", json={"mode": "maybe"}).status_code == 400
        r = client.post("/api/connections/embeddings/test").json()
        assert (
            r["ok"]
            and r["dims"] == DIMS
            and r["indexed"] == 6
            and r["model"] == "qwen3-embedding:0.6b"
        )
        view = client.get("/api/connections").json()["embeddings"]
        assert view["available"] is True and view["indexed"] == 6 and view["total"] == 6
        # remembered across restarts
        saved = json.loads((settings.data_dir / "app-settings.json").read_text())
        assert saved["embeddings"] == {"base_url": "http://127.0.0.1:11434/v1", "api_key": ""}

        # a key of its own goes to the vault
        client.put("/api/connections/embeddings", json={"api_key": "sk-emb"})
        assert service.app.vault.get("EMBEDDINGS_API_KEY") == "sk-emb"
        view = client.get("/api/connections").json()["embeddings"]
        assert view["key_source"] == "vault"
        assert service.app.embedder is not None and service.app.embedder.client.api_key == "sk-emb"

        # off: no index, keyword recall only
        view = client.put("/api/connections/embeddings", json={"mode": "off"}).json()
        assert view["mode"] == "off" and view["status"] == "off"
        assert service.app.memory.index is None and service.app.embedder is None
        r = client.post("/api/connections/embeddings/test").json()
        assert r["ok"] is False

        # a model switch rebuilds an embedder that rides on the model's endpoint
        client.put("/api/connections/embeddings", json={"mode": "auto", "base_url": ""})
        client.put(
            "/api/connections/llm",
            json={
                "provider": "openai",
                "model": "qwen3:8b",
                "base_url": "http://127.0.0.1:11434/v1",
                "api_key": "",
            },
        )
        assert service.app.embedder is not None
        assert service.app.embedder.base_url == "http://127.0.0.1:11434/v1"
        assert service.app.embedder.model == "qwen3-embedding:0.6b"


def test_embeddings_key_from_the_vault(settings: Settings):
    from rich.console import Console

    from openmuse.app import OpenMuseApp
    from openmuse.console import ConsoleUI

    settings.memory.embedding_base_url = "https://emb.example/v1"
    settings.memory.embedding_api_key = "{{vault:EMB}}"
    app_ = OpenMuseApp(settings, ConsoleUI(Console()))
    assert app_.embedder is not None and app_.embedder.client.api_key == "EMPTY"  # not set yet
    app_.vault.set("EMB", "sk-real")
    app_.attach_embedder()
    assert app_.embedder is not None and app_.embedder.client.api_key == "sk-real"
    settings.memory.embeddings = "off"
    app_.attach_embedder()
    assert app_.embedder is None and app_.memory is not None and app_.memory.index is None


# ----------------------------------------------------------------------------- the CLI
def test_cli_memory_recall(settings: Settings, tmp_path: Path, fake: FakeEmbeddings):
    from typer.testing import CliRunner

    from openmuse.cli import app as cli_app

    settings.memory.embedding_base_url = "http://127.0.0.1:11434/v1"
    seed(MemoryStore(settings.memory_db))
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'data_dir = "{settings.data_dir}"\n[llm]\napi_key = "k"\nstream = false\n'
        f'[agent]\nworkspace = "{settings.agent.workspace}"\n'
        '[memory]\nembedding_base_url = "http://127.0.0.1:11434/v1"\n'
    )
    runner = CliRunner()
    result = runner.invoke(
        cli_app, ["memory", "recall", "-c", str(cfg), "写邮件给房东", "--limit", "2"]
    )
    out = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert result.exit_code == 0, out
    assert "by meaning: qwen3-embedding:0.6b" in out and "landlord" in out and "closeness" in out
