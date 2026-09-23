"""Web search behind the ``web_search`` tool.

DuckDuckGo needs no key and is the default, but it is scraped, not served: it rate-limits
and breaks now and then. When that matters, pick a provider with an API — Brave or
Tavily with a key, or a SearXNG instance you run yourself — in ``[connectors.search]``
or from *Connections → Web search*. Whatever is picked, a failed search falls back to
DuckDuckGo once, with a note in the result, so a lapsed key does not stop a task.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from openmuse.config import SearchSettings
from openmuse.logger import logger
from openmuse.vault import CredentialVault

PROVIDERS: dict[str, dict[str, Any]] = {
    "duckduckgo": {"label": "DuckDuckGo", "needs_key": False, "host": "duckduckgo.com"},
    "brave": {
        "label": "Brave Search",
        "needs_key": True,
        "host": "api.search.brave.com",
        "keys_url": "https://brave.com/search/api/",
    },
    "tavily": {
        "label": "Tavily",
        "needs_key": True,
        "host": "api.tavily.com",
        "keys_url": "https://app.tavily.com/",
    },
    "searxng": {"label": "SearXNG", "needs_key": False, "host": ""},
}
TIMEOUT = 20.0


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def render(self, index: int) -> str:
        return f"{index}. {self.title or '(no title)'}\n   {self.url}\n   {self.snippet}"


class SearchError(Exception):
    """The provider did not answer with results."""


def _region(region: str) -> tuple[str, str]:
    """``'cn-zh'`` → (country ``CN``, language ``zh``); DuckDuckGo's region codes are what
    the tool's parameter uses, the others take country and language apart."""
    region = (region or "").strip().lower()
    if not region or region == "wt-wt" or "-" not in region:
        return "", ""
    country, lang = region.split("-", 1)
    return country.upper(), lang.lower()


class WebSearchProvider:
    """One provider, chosen by settings, with DuckDuckGo behind it as the fallback."""

    def __init__(self, settings: SearchSettings, vault: CredentialVault | None = None):
        self.settings = settings
        self.vault = vault

    @property
    def name(self) -> str:
        return self.settings.provider

    @property
    def label(self) -> str:
        return PROVIDERS[self.name]["label"]

    @property
    def host(self) -> str:
        """Where a search goes — what the Sentinel shows as the egress target."""
        if self.name == "searxng":
            return urlparse(self.settings.base_url).hostname or "searxng"
        return str(PROVIDERS[self.name]["host"])

    def api_key(self) -> str:
        key = self.settings.api_key
        if key and self.vault is not None and self.vault.has_placeholders(key):
            key = self.vault.resolve(key, strict=False)
            if self.vault.has_placeholders(key):
                key = ""
        return key

    @property
    def configured(self) -> bool:
        """Is what the provider needs there — a key, or an instance URL?"""
        if PROVIDERS[self.name]["needs_key"]:
            return bool(self.api_key())
        if self.name == "searxng":
            return bool(self.settings.base_url)
        return True

    def describe(self) -> str:
        if self.name == "duckduckgo":
            return "DuckDuckGo (no key needed)"
        if self.name == "searxng":
            return f"SearXNG at {self.settings.base_url or '(no URL set)'}"
        return f"{self.label} ({'key set' if self.api_key() else 'no key'})"

    async def search(
        self, query: str, max_results: int = 6, region: str = ""
    ) -> tuple[list[SearchResult], str]:
        """Results and a note: empty when the configured provider answered, otherwise why
        DuckDuckGo answered instead."""
        if self.name == "duckduckgo":
            return await self._ddg(query, max_results, region), ""
        if not self.configured:
            missing = "no API key" if PROVIDERS[self.name]["needs_key"] else "no instance URL"
            logger.warning(
                "{} is the search provider but has {}; using DuckDuckGo", self.label, missing
            )
            return await self._ddg(
                query, max_results, region
            ), f"{self.label}: {missing} — results from DuckDuckGo"
        try:
            return await self._call(query, max_results, region), ""
        except Exception as exc:  # noqa: BLE001 — a failed provider must not stop the task
            reason = self.explain(exc)
            logger.warning("{} search failed ({}); using DuckDuckGo", self.label, reason)
            return await self._ddg(
                query, max_results, region
            ), f"{self.label} failed ({reason}) — results from DuckDuckGo"

    async def probe(self, query: str = "OpenMuse personal agent") -> dict[str, Any]:
        """One search against the configured provider, no fallback — for the test button."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            results = (
                await self._ddg(query, 3, "")
                if self.name == "duckduckgo"
                else await self._call(query, 3, "")
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": self.explain(exc)}
        return {
            "ok": True,
            "provider": self.label,
            "results": len(results),
            "first": results[0].title if results else "",
            "ms": int((loop.time() - started) * 1000),
        }

    def explain(self, exc: Exception) -> str:
        """Why a search failed, in words: httpx's timeouts have empty messages."""
        if isinstance(exc, httpx.ConnectTimeout | httpx.ConnectError):
            return f"could not reach {self.host}" + (f" ({exc})" if str(exc) else "")
        if isinstance(exc, httpx.TimeoutException):
            return f"{self.host} did not answer within {TIMEOUT:g}s"
        if isinstance(exc, SearchError):
            return str(exc)
        return f"{type(exc).__name__}: {str(exc)[:160]}".rstrip(": ")

    # ------------------------------------------------------------------ providers
    async def _call(self, query: str, max_results: int, region: str) -> list[SearchResult]:
        if self.name == "brave":
            return await self._brave(query, max_results, region)
        if self.name == "tavily":
            return await self._tavily(query, max_results)
        if self.name == "searxng":
            return await self._searxng(query, max_results, region)
        return await self._ddg(query, max_results, region)

    @staticmethod
    async def _ddg(query: str, max_results: int, region: str) -> list[SearchResult]:
        def _search() -> list[dict[str, Any]]:
            from ddgs import DDGS

            with DDGS() as ddgs:
                return list(ddgs.text(query, region=region or "wt-wt", max_results=max_results))

        rows = await asyncio.to_thread(_search)
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("href") or r.get("url") or "",
                snippet=(r.get("body") or "").strip(),
            )
            for r in rows
        ]

    async def _brave(self, query: str, max_results: int, region: str) -> list[SearchResult]:
        country, lang = _region(region)
        params: dict[str, Any] = {"q": query, "count": min(max_results, 20)}
        if country:
            params["country"] = country
        if lang:
            params["search_lang"] = lang
        async with _client() as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self.api_key(),
                },
            )
        _raise_for(resp)
        rows = (resp.json().get("web") or {}).get("results") or []
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                snippet=(r.get("description") or "").strip(),
            )
            for r in rows[:max_results]
        ]

    async def _tavily(self, query: str, max_results: int) -> list[SearchResult]:
        async with _client() as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"query": query, "max_results": min(max_results, 20), "search_depth": "basic"},
                headers={
                    "Authorization": f"Bearer {self.api_key()}",
                    "Content-Type": "application/json",
                },
            )
        _raise_for(resp)
        rows = resp.json().get("results") or []
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                snippet=(r.get("content") or "").strip()[:400],
            )
            for r in rows[:max_results]
        ]

    async def _searxng(self, query: str, max_results: int, region: str) -> list[SearchResult]:
        country, lang = _region(region)
        params: dict[str, Any] = {"q": query, "format": "json"}
        if lang:
            params["language"] = f"{lang}-{country}" if country else lang
        base = self.settings.base_url.rstrip("/")
        async with _client() as client:
            resp = await client.get(
                f"{base}/search", params=params, headers={"Accept": "application/json"}
            )
        _raise_for(resp)
        rows = resp.json().get("results") or []
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                snippet=(r.get("content") or "").strip(),
            )
            for r in rows[:max_results]
        ]


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code == 401 or resp.status_code == 403:
        raise SearchError(f"the key was refused (HTTP {resp.status_code})")
    if resp.status_code == 429:
        raise SearchError("rate limited (HTTP 429)")
    if resp.status_code >= 400:
        raise SearchError(f"HTTP {resp.status_code}: {resp.text[:120]}")
    try:
        resp.json()
    except ValueError as exc:
        raise SearchError("the reply was not JSON (is the URL a search API?)") from exc


__all__ = ["PROVIDERS", "SearchError", "SearchResult", "WebSearchProvider"]
