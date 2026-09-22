"""Recall by meaning.

The keyword recall in ``store.py`` finds a memory when the message shares a word with
it. It misses "写邮件给房东" → "the landlord is Bob Li" and "book a flight" → "prefers a
window seat". An embedding endpoint closes that gap: every memory is embedded once
(the vector is kept in ``memory.db`` next to a hash of the text, so a changed memory is
embedded again), the message is embedded per turn, and the memories closest in meaning
are fused with the keyword ranking — the two agree often, and where they do not, both
get a say.

Any OpenAI-compatible ``/embeddings`` endpoint works: OpenAI itself, Ollama with an
embedding model pulled (``qwen3-embedding:0.6b`` is small and reads Chinese and English),
most company gateways. DeepSeek has none, so with it recall stays by keyword unless
``memory.embedding_base_url`` points somewhere that has — and in ``auto`` mode that is
found out with one failed call per start, not one per turn.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

import openai
from loguru import logger
from openai import AsyncOpenAI

from openmuse.config import LLMSettings, MemorySettings
from openmuse.memory.store import MemoryItem, MemoryStore, content_hash

OPENAI_DEFAULT = "text-embedding-3-small"
OLLAMA_DEFAULT = "qwen3-embedding:0.6b"
# chat endpoints known to have no /embeddings: not worth a call
KNOWN_WITHOUT = ("api.deepseek.com",)
BATCH = 64
RETRY_AFTER = 300.0  # seconds before a failed endpoint is tried again
RRF_K = 60


def is_ollama(base_url: str) -> bool:
    return ":11434" in base_url


def default_model(base_url: str) -> str:
    """The embedding model to use when none is named, going by the endpoint."""
    if is_ollama(base_url):
        return OLLAMA_DEFAULT
    if "openrouter.ai" in base_url:
        return "openai/" + OPENAI_DEFAULT
    return OPENAI_DEFAULT


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def fuse(*rankings: list[MemoryItem], limit: int) -> list[MemoryItem]:
    """Reciprocal-rank fusion: an item near the top of both lists beats the top of one."""
    score: dict[str, float] = {}
    items: dict[str, MemoryItem] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            score[item.id] = score.get(item.id, 0.0) + 1.0 / (RRF_K + rank + 1)
            items.setdefault(item.id, item)
    order = sorted(score, key=lambda i: -score[i])
    return [items[i] for i in order[:limit]]


def standouts(scored: list[tuple[float, MemoryItem]], limit: int) -> list[MemoryItem]:
    """The memories whose closeness stands out from the crowd, closest first.

    Cosines are model-dependent (one model's "unrelated" is 0.1, another's 0.45), so the
    cut is relative: above the mean, and with enough memories to tell, above the mean by
    a standard deviation.
    """
    if not scored:
        return []
    values = [s for s, _ in scored]
    mean = sum(values) / len(values)
    if len(values) >= 8:
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        cut = mean + std
    else:
        cut = mean
    kept = sorted((p for p in scored if p[0] >= cut), key=lambda p: -p[0])
    return [item for _, item in kept[:limit]]


class Embedder:
    """The embedding endpoint: one client, with the failure bookkeeping ``auto`` needs."""

    def __init__(self, memory: MemorySettings, llm: LLMSettings, api_key: str | None = None):
        self.mode = memory.embeddings
        own_endpoint = bool(memory.embedding_base_url)
        self.base_url = memory.embedding_base_url or llm.base_url or "https://api.openai.com/v1"
        self.model = memory.embedding_model or default_model(self.base_url)
        key = api_key if api_key is not None else (memory.embedding_api_key or llm.api_key)
        # the chat endpoint's headers (a gateway's end-user id) belong to that endpoint only
        headers = None if own_endpoint else (llm.extra_headers or None)
        self.client = AsyncOpenAI(
            api_key=key or "EMPTY",
            base_url=self.base_url,
            timeout=30.0,
            max_retries=1,
            default_headers=headers,
        )
        self.available: bool | None = None  # None: not tried yet
        self.reason = ""
        self.dims = 0
        self._given_up = False
        self._retry_at = 0.0
        if not own_endpoint and any(host in self.base_url for host in KNOWN_WITHOUT):
            self.available, self._given_up = False, True
            self.reason = (
                f"{self.base_url} has no embeddings endpoint — set memory.embedding_base_url "
                f"to one that has (OpenAI, or Ollama with {OLLAMA_DEFAULT}); recall is by keyword"
            )

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def usable(self) -> bool:
        """Worth a call right now: on, and not known to be down (or given up on)."""
        if not self.enabled:
            return False
        if self.available is False:
            return not self._given_up and time.monotonic() >= self._retry_at
        return True

    @property
    def status(self) -> str:
        if not self.enabled:
            return "off"
        where = f"{self.model} at {self.base_url}"
        if self.available is None:
            return f"{where} · not tried yet"
        if self.available:
            return f"{where} · {self.dims} dims"
        return f"not available — {self.reason}"

    def reset(self) -> None:
        """Forget past failures so the next call tries again (a test button, a `doctor`)."""
        if self.available is False and not any(host in self.base_url for host in KNOWN_WITHOUT):
            self.available, self._given_up, self._retry_at = None, False, 0.0

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Vectors for ``texts`` in order, or None when the endpoint cannot be used now."""
        if not texts or not self.usable:
            return None
        try:
            out: list[list[float]] = []
            for start in range(0, len(texts), BATCH):
                batch = texts[start : start + BATCH]
                resp = await self.client.embeddings.create(model=self.model, input=batch)
                data = sorted(resp.data, key=lambda d: d.index)
                if len(data) != len(batch):
                    raise ValueError(f"{len(data)} vectors for {len(batch)} texts")
                out.extend([list(d.embedding) for d in data])
        except Exception as exc:  # noqa: BLE001 — every kind is a reason to fall back
            self._fail(exc)
            return None
        if self.available is not True:
            logger.info("recall by meaning is on: {} ({} dims)", self.model, len(out[0]))
        self.available, self.reason, self.dims = True, "", len(out[0])
        return out

    async def close(self) -> None:
        await self.client.close()

    def _fail(self, exc: Exception) -> None:
        permanent, reason = self._explain(exc)
        was = self.available
        self.available, self.reason = False, reason
        self._retry_at = time.monotonic() + RETRY_AFTER
        # in auto mode an endpoint that has no embeddings is not asked again this run
        self._given_up = permanent and self.mode == "auto"
        if was is not False:
            log = logger.warning if self.mode == "on" else logger.info
            log("recall by meaning is off: {}", reason)

    def _explain(self, exc: Exception) -> tuple[bool, str]:
        """(is it permanent, what to tell the user)."""
        msg = str(exc).replace("\n", " ")
        msg = msg[:200]
        if isinstance(exc, openai.NotFoundError):
            if is_ollama(self.base_url) and "not found" in msg.lower():
                return True, f"Ollama has no model {self.model!r} — `ollama pull {self.model}`"
            return True, (
                f"{self.base_url} has no /embeddings for {self.model!r} — set "
                "memory.embedding_base_url to an endpoint that has one (OpenAI, or Ollama "
                f"with {OLLAMA_DEFAULT})"
            )
        if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
            return True, f"{self.base_url} refused the key for embeddings: {msg}"
        if isinstance(exc, openai.BadRequestError | openai.UnprocessableEntityError):
            return True, f"{self.base_url} rejected the embeddings call: {msg}"
        if isinstance(exc, openai.APIConnectionError | openai.APITimeoutError):
            return False, f"could not reach {self.base_url}: {msg}"
        if isinstance(exc, openai.RateLimitError | openai.InternalServerError):
            return False, f"{self.base_url}: {msg}"
        return True, f"unexpected reply from {self.base_url}: {type(exc).__name__}: {msg}"


class MemoryIndex:
    """Vectors for every memory, kept current, and the fused search over them."""

    def __init__(self, store: MemoryStore, embedder: Embedder):
        self.store = store
        self.embedder = embedder
        self._vectors: dict[str, tuple[str, list[float]]] | None = None
        self._lock = asyncio.Lock()

    def _load(self) -> dict[str, tuple[str, list[float]]]:
        if self._vectors is None:
            self._vectors = self.store.vectors(self.embedder.model)
        return self._vectors

    async def ensure(self, items: list[MemoryItem]) -> bool:
        """Every item embedded with the current model. False when that cannot be done now."""
        if not self.embedder.usable:
            return False
        async with self._lock:
            vectors = self._load()
            wanted = {it.id: content_hash(it.content) for it in items}
            stale = [mid for mid in vectors if mid not in wanted]
            if stale:
                self.store.drop_vectors(stale, self.embedder.model)
                for mid in stale:
                    vectors.pop(mid, None)
            missing = [it for it in items if vectors.get(it.id, ("",))[0] != wanted[it.id]]
            if missing:
                embedded = await self.embedder.embed([it.content for it in missing])
                if embedded is None:
                    return False
                fresh = {
                    it.id: (wanted[it.id], vec) for it, vec in zip(missing, embedded, strict=True)
                }
                self.store.put_vectors(self.embedder.model, fresh)
                vectors.update(fresh)
            return self.embedder.usable

    async def search(self, query: str, limit: int = 10) -> list[MemoryItem]:
        """Keyword hits and meaning hits, fused; the keyword ranking alone when the
        endpoint is not available."""
        items = self.store.all()
        by_keyword = self.store.search(query, limit=max(limit, 2 * limit))
        if not items or not query.strip() or not await self.ensure(items):
            return by_keyword[:limit]
        query_vec = await self.embedder.embed([query])
        if not query_vec:
            return by_keyword[:limit]
        vectors = self._load()
        scored = [(cosine(query_vec[0], vectors[it.id][1]), it) for it in items if it.id in vectors]
        by_meaning = standouts(scored, limit=2 * limit)
        return fuse(by_keyword, by_meaning, limit=limit)

    async def closest(self, text: str, limit: int = 5) -> list[tuple[float, MemoryItem]]:
        """Memories closest in meaning to ``text`` with their cosines — for the CLI and
        the connections test, not the agent."""
        items = self.store.all()
        if not items or not await self.ensure(items):
            return []
        vec = await self.embedder.embed([text])
        if not vec:
            return []
        vectors = self._load()
        scored = [(cosine(vec[0], vectors[it.id][1]), it) for it in items if it.id in vectors]
        scored.sort(key=lambda p: -p[0])
        return scored[:limit]

    def status(self) -> dict[str, Any]:
        e = self.embedder
        indexed = len(self._load()) if e.enabled else 0
        return {
            "mode": e.mode,
            "model": e.model,
            "base_url": e.base_url,
            "available": e.available,
            "reason": e.reason,
            "dims": e.dims,
            "indexed": indexed,
            "total": self.store.count(),
            "status": e.status,
        }


__all__ = [
    "Embedder",
    "MemoryIndex",
    "cosine",
    "default_model",
    "fuse",
    "is_ollama",
    "standouts",
]
