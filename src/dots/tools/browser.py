"""A minimal fetch-and-extract browsing tool built on httpx."""

from __future__ import annotations

import re
from typing import Any

from dots.tools.base import ToolResult

try:  # httpx is a runtime dep, but keep the import defensive for docs builds
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _to_text(html: str, *, limit: int = 4000) -> str:
    text = _TAG.sub(" ", html)
    text = _WS.sub(" ", text).strip()
    return text[:limit]


class BrowserTool:
    """Fetch a URL and return readable text.

    Real deployments back this with a headless browser; the default keeps things
    light with an HTTP GET plus naive tag-stripping — enough for many read-only
    research goals.
    """

    name = "browser"

    def __init__(self, *, timeout: float = 15.0, user_agent: str = "dots/0.4") -> None:
        self._timeout = timeout
        self._headers = {"User-Agent": user_agent}

    async def run(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        if not url:
            return ToolResult.failure("browser requires 'url'")
        if httpx is None:  # pragma: no cover
            return ToolResult.failure("httpx is not installed")

        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as client:
                resp = await client.get(str(url), follow_redirects=True)
                resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - surface as a tool failure
            return ToolResult.failure(f"fetch failed: {exc}")

        text = _to_text(resp.text)
        return ToolResult.success(
            output=text,
            observations=[f"fetched {url} ({len(text)} chars)"],
        )
