"""Model Context Protocol client: expose tools of MCP servers as OpenMuse tools.

Configure in ``config.toml``::

    [[mcp.servers]]
    name = "filesystem"
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "./workspace"]
    risk = "moderate"          # safe | moderate | sensitive (default moderate)

    [[mcp.servers]]
    name = "remote"
    url = "http://localhost:8000/mcp"   # streamable HTTP (or SSE)

Compatible with mcp 1.x and 2.x.
"""

from __future__ import annotations

import json
import re
from contextlib import AsyncExitStack
from typing import Any

from openmuse.config import MCPServerSettings
from openmuse.logger import logger
from openmuse.schema import ToolResult
from openmuse.tools.base import BaseTool, CallAssessment

_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first present attribute – mcp 2.x uses snake_case, 1.x camelCase."""
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _safe_name(server: str, tool: str) -> str:
    name = _NAME_RE.sub("_", f"{server}__{tool}")
    return name[:64]


class MCPTool(BaseTool):
    session: Any
    server: str
    original_name: str

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        base = super().assess(args)
        base.summary = (
            f"mcp:{self.server}.{self.original_name}({json.dumps(args, ensure_ascii=False)[:150]})"
        )
        return base

    async def execute(self, **kwargs: Any) -> ToolResult:
        result = await self.session.call_tool(self.original_name, kwargs or None)
        parts: list[str] = []
        for item in getattr(result, "content", None) or []:
            itype = getattr(item, "type", "")
            if itype == "text":
                parts.append(getattr(item, "text", ""))
            elif itype == "image":
                parts.append(f"[image {_attr(item, 'mime_type', 'mimeType', default='')}]")
            elif itype == "resource":
                res = getattr(item, "resource", None)
                parts.append(getattr(res, "text", None) or f"[resource {getattr(res, 'uri', '')}]")
            else:
                parts.append(str(item))
        structured = _attr(result, "structured_content", "structuredContent")
        if structured and not parts:
            parts.append(json.dumps(structured, ensure_ascii=False, indent=2, default=str))
        text = "\n".join(p for p in parts if p) or "(no output)"
        if _attr(result, "is_error", "isError", default=False):
            return ToolResult.fail(text)
        return ToolResult(output=text)


class MCPManager:
    """Connects to configured MCP servers and keeps the sessions alive."""

    def __init__(self, servers: list[MCPServerSettings]):
        self.servers = servers
        self._stack = AsyncExitStack()
        self.tools: list[MCPTool] = []

    async def connect(self) -> list[MCPTool]:
        from mcp import ClientSession

        for cfg in self.servers:
            try:
                read, write = await self._open_transport(cfg)
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listed = await session.list_tools()
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP server '{}' unavailable: {}", cfg.name, exc)
                continue
            for t in listed.tools:
                schema = _attr(t, "input_schema", "inputSchema") or {
                    "type": "object",
                    "properties": {},
                }
                tool = MCPTool(
                    name=_safe_name(cfg.name, t.name),
                    description=(t.description or f"{t.name} (from MCP server {cfg.name})")[:1000],
                    parameters=schema,
                    risk=cfg.risk,
                    egress=cfg.egress,
                    reads_private_data=cfg.reads_private_data,
                    session=session,
                    server=cfg.name,
                    original_name=t.name,
                )
                self.tools.append(tool)
            logger.info("MCP server '{}' connected with {} tools", cfg.name, len(listed.tools))
        return self.tools

    async def _open_transport(self, cfg: MCPServerSettings) -> tuple[Any, Any]:
        if cfg.url:
            try:  # mcp >= 2
                from mcp.client.streamable_http import streamable_http_client as http_client
            except ImportError:  # mcp 1.x
                from mcp.client.streamable_http import (  # type: ignore[attr-defined,no-redef]
                    streamablehttp_client as http_client,
                )
            try:
                streams = await self._stack.enter_async_context(http_client(cfg.url))
            except Exception:
                from mcp.client.sse import sse_client

                streams = await self._stack.enter_async_context(sse_client(cfg.url))
            return streams[0], streams[1]
        if not cfg.command:
            raise ValueError(f"MCP server '{cfg.name}' needs either `command` or `url`")
        import os

        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=cfg.command, args=cfg.args, env={**os.environ, **cfg.env} if cfg.env else None
        )
        streams = await self._stack.enter_async_context(stdio_client(params))
        return streams[0], streams[1]

    async def close(self) -> None:
        try:
            await self._stack.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.debug("MCP shutdown: {}", exc)


__all__ = ["MCPManager", "MCPTool"]
