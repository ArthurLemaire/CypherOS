"""Web tools: search (DuckDuckGo, no API key) and fetch (read-only GET → markdown)."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) OpenMuse/0.1 (+https://github.com/OpenMuseAgent/OpenMuse)"
)


def host_of(url: str) -> str | None:
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def _is_private_host(host: str) -> bool:
    """SSRF guard: refuse loopback / link-local / private ranges."""
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False  # let httpx report the DNS error
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


class WebSearch(BaseTool):
    name: str = "web_search"
    description: str = (
        "Search the web (DuckDuckGo). Returns titles, URLs and snippets. Use `web_fetch` to read a "
        "result in full."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
            "region": {
                "type": "string",
                "description": "e.g. 'wt-wt' (default), 'cn-zh', 'us-en'.",
            },
        },
        "required": ["query"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    egress: bool = True

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=RiskLevel.SAFE,
            egress=True,
            egress_target="duckduckgo.com",
            summary=f"web_search: {str(args.get('query', ''))[:120]}",
        )

    async def execute(
        self, query: str = "", max_results: int = 6, region: str = "wt-wt", **_: Any
    ) -> ToolResult:
        if not query.strip():
            return ToolResult.fail("empty query")
        max_results = max(1, min(int(max_results or 6), 20))

        def _search() -> list[dict[str, Any]]:
            from ddgs import DDGS

            with DDGS() as ddgs:
                return list(ddgs.text(query, region=region or "wt-wt", max_results=max_results))

        try:
            results = await asyncio.to_thread(_search)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(f"search failed: {exc}")
        if not results:
            return ToolResult(output="No results.")
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title") or "(no title)"
            url = r.get("href") or r.get("url") or ""
            body = (r.get("body") or "").strip()
            lines.append(f"{i}. {title}\n   {url}\n   {body}")
        return ToolResult(output="\n".join(lines))


class WebFetch(BaseTool):
    name: str = "web_fetch"
    description: str = (
        "Fetch a public web page or API (HTTP GET only) and return its readable content as "
        "markdown/text (HTML is converted, JSON is pretty-printed). Use for reading articles, docs, "
        "prices, schedules."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "max_chars": {"type": "integer", "description": "Truncate output (default 8000)."},
        },
        "required": ["url"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    egress: bool = True
    timeout: float = 30.0

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        url = str(args.get("url", ""))
        return CallAssessment(
            risk=RiskLevel.MODERATE,
            egress=True,
            egress_target=host_of(url),
            summary=f"web_fetch: {url[:160]}",
        )

    async def execute(self, url: str = "", max_chars: int = 8_000, **_: Any) -> ToolResult:
        url = url.strip()
        if not url:
            return ToolResult.fail("empty url")
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        host = host_of(url)
        if not host:
            return ToolResult.fail("invalid url")
        if await asyncio.to_thread(_is_private_host, host):
            return ToolResult.fail(f"refusing to fetch private/internal host '{host}'")
        max_chars = max(500, min(int(max_chars or 8_000), 60_000))
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self.timeout,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en,zh;q=0.8"},
            ) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            return ToolResult.fail(f"request failed: {exc}")
        ctype = resp.headers.get("content-type", "")
        text = _to_text(resp, ctype)
        if resp.status_code >= 400:
            return ToolResult(output=text[:max_chars], error=f"HTTP {resp.status_code}")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated, {len(text)} chars total]"
        return ToolResult(output=f"URL: {resp.url}\nContent-Type: {ctype}\n\n{text}")


def _to_text(resp: httpx.Response, ctype: str) -> str:
    if "json" in ctype:
        try:
            return json.dumps(resp.json(), ensure_ascii=False, indent=2)
        except ValueError:
            return resp.text
    if "html" in ctype or resp.text.lstrip()[:15].lower().startswith(("<!doctype html", "<html")):
        return html_to_markdown(resp.text)
    return resp.text


def html_to_markdown(html: str) -> str:
    from bs4 import BeautifulSoup
    from html2text import HTML2Text

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer", "header"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    main = soup.find("main") or soup.find("article") or soup.body or soup
    h = HTML2Text()
    h.ignore_images = True
    h.ignore_emphasis = False
    h.body_width = 0
    h.skip_internal_links = True
    text = h.handle(str(main))
    # squeeze blank lines
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    body = "\n".join(out).strip()
    return f"# {title}\n\n{body}" if title else body


__all__ = ["WebFetch", "WebSearch", "host_of", "html_to_markdown"]
