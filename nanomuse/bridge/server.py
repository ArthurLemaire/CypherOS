"""The server's end of the CLI bridge: a request from a command becomes a tool call."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from nanomuse.bridge.tokens import BRIDGE_TOKEN_ENV, BRIDGE_URL_ENV, BridgeGrant, BridgeTokens
from nanomuse.logger import logger
from nanomuse.runtime import DEVICE_SERVER
from nanomuse.schema import Function, ToolCall, ToolResult

KINDS = ("device", "browser", "open")

# what `nanomuse-browser` may ask of the browser tool, and the arguments each takes
_BROWSER_ACTIONS: dict[str, tuple[str, ...]] = {
    "navigate": ("url",),
    "extract": (),
    "click": ("index",),
    "type": ("index", "text", "submit"),
    "press": ("key",),
    "scroll": ("direction",),
    "back": (),
    "screenshot": (),
    "close": (),
}


class BridgeError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Bridge:
    """Mints the call tokens the shell tool hands its commands, and answers their requests.

    ``base_url`` is where the server listens for them (``http://127.0.0.1:8787``); until it
    is set — the CLI (`nanomuse chat`) has no server — no token is minted and the programs
    say so.
    """

    def __init__(self, tools: Any, sentinel: Any, ui: Any, base_url: str = ""):
        self.tools = tools
        self.sentinel = sentinel
        self.ui = ui
        self.base_url = base_url.rstrip("/")
        self.tokens = BridgeTokens()

    # ------------------------------------------------------------------ the shell tool's side
    def env_for(
        self, call_id: str, tool: str, ttl: float
    ) -> tuple[dict[str, str], BridgeGrant] | None:
        """The two variables a command gets, and the grant to revoke when it is done."""
        if not self.base_url:
            return None
        grant = self.tokens.mint(call_id, tool, ttl)
        return {BRIDGE_URL_ENV: self.base_url, BRIDGE_TOKEN_ENV: grant.token}, grant

    def release(self, grant: BridgeGrant | None) -> None:
        if grant is not None:
            self.tokens.revoke(grant.token)

    # ------------------------------------------------------------------ the requests
    def device_tools(self) -> list[dict[str, str]]:
        """What `nanomuse-device list` prints: the device's tools, without their prefix."""
        prefix = DEVICE_SERVER + "_"
        out = []
        for t in self.tools:
            if t.name.startswith(prefix):
                out.append({"name": t.name[len(prefix) :], "description": t.description[:200]})
        return out

    async def handle(self, token: str | None, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        grant = self.tokens.get(token)
        if grant is None:
            raise BridgeError(401, "the call token is missing, unknown or expired")
        if kind not in KINDS:
            raise BridgeError(404, f"unknown bridge '{kind}'")
        grant.calls += 1
        # in the command's own context: its chat, its task, its purpose
        task = asyncio.create_task(self._dispatch(grant, kind, body), context=grant.context.copy())
        return await task

    async def _dispatch(
        self, grant: BridgeGrant, kind: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        tool_name, args = self._plan(kind, body)
        tool = self.tools.get(tool_name)
        if tool is None:
            return self._result(ToolResult.fail(self._missing(kind, tool_name)))
        call = ToolCall(
            function=Function(name=tool_name, arguments=json.dumps(args, ensure_ascii=False))
        )
        try:
            summary = tool.assess(args).summary
        except Exception:  # noqa: BLE001 — a bad argument is reported by the tool itself
            summary = f"{tool_name}(…)"
        thread = self.ui.thread()
        event = self.ui.emit(
            {
                "type": "tool",
                "tool": tool_name,
                "summary": summary,
                "args": _preview(args),
                "status": "running",
                "via": grant.tool,  # the shell / python_execute call it came from
            }
        )
        logger.info("bridge {} → {} from {} {}", kind, summary, grant.tool, grant.call_id)
        result = await self.sentinel.guard(call, tool)
        status = (
            "ok"
            if result.ok
            else ("blocked" if "Sentinel blocked" in (result.error or "") else "error")
        )
        self.ui.patch(
            thread, event["id"], status=status, output=(result.output or result.error or "")[:600]
        )
        if kind == "open" and result.ok:
            self.ui.emit(
                {
                    "type": "notice",
                    "level": "info",
                    "text": f"Opened {args.get('url', '')} in the browser view — you can take it from there.",
                    "handoff": args.get("url", ""),
                }
            )
        return self._result(result)

    @staticmethod
    def _plan(kind: str, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Which tool, with which arguments, a request means."""
        if kind == "device":
            name = str(body.get("tool") or "").strip().replace("-", "_").replace(".", "_")
            if not name or not name.replace("_", "").isalnum():
                raise BridgeError(
                    400, "nanomuse-device needs a capability and an action, e.g. `clipboard read`"
                )
            device_args = body.get("args") or {}
            if not isinstance(device_args, dict):
                raise BridgeError(400, "arguments must be key=value pairs")
            return f"{DEVICE_SERVER}_{name}", device_args
        if kind == "browser":
            action = str(body.get("action") or "").strip()
            if action == "fetch":
                # the page as text, through the plain fetcher; the browser's own signed-in
                # fetch replaces this when the browser backend has one
                url = str(body.get("url") or "")
                if not url:
                    raise BridgeError(400, "fetch needs a URL")
                return "web_fetch", {"url": url}
            wanted = _BROWSER_ACTIONS.get(action)
            if wanted is None:
                raise BridgeError(
                    400,
                    f"unknown browser action '{action}'; one of {', '.join([*_BROWSER_ACTIONS, 'fetch'])}",
                )
            args: dict[str, Any] = {"action": action}
            for key in wanted:
                if body.get(key) is not None:
                    args[key] = body[key]
            return "browser", args
        if kind == "open":
            url = str(body.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                raise BridgeError(400, "nanomuse-open needs an http(s) URL")
            return "browser", {"action": "navigate", "url": url}
        raise BridgeError(404, f"unknown bridge '{kind}'")

    def _missing(self, kind: str, tool_name: str) -> str:
        if kind == "device":
            have = self.device_tools()
            if not have:
                return (
                    "no phone is connected to this nanoMuse, so there are no device capabilities "
                    "here (on the phone they come with the app; on a computer, connect the app)"
                )
            names = ", ".join(sorted(t["name"] for t in have))
            return f"this phone has no '{tool_name.removeprefix(DEVICE_SERVER + '_')}'; it has: {names}"
        if tool_name == "browser":
            return "the browser view is off (Connections → Browser in the app turns it on)"
        return f"the tool '{tool_name}' is not available here"

    @staticmethod
    def _result(result: ToolResult) -> dict[str, Any]:
        return {
            "ok": result.ok,
            "output": result.output,
            "error": result.error,
            "images": list(result.images or []),
        }


def _preview(args: dict[str, Any], limit: int = 400) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in args.items():
        s = v if isinstance(v, (int, float, bool)) or v is None else str(v)
        out[k] = s if not isinstance(s, str) or len(s) <= limit else s[: limit - 1] + "…"
    return out


__all__ = ["KINDS", "Bridge", "BridgeError"]
