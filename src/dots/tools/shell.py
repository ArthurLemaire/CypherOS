"""A sandboxed shell tool with an explicit allow-list."""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from dots.tools.base import ToolResult

_DEFAULT_ALLOW = frozenset({"ls", "cat", "echo", "pwd", "head", "tail", "wc", "date"})


class ShellTool:
    """Run a whitelisted command. Never uses ``shell=True``.

    The allow-list defaults to a handful of read-only commands. Callers opt into
    more by passing ``allow=``. Anything not on the list is refused before it runs.
    """

    name = "shell"

    def __init__(self, *, allow: set[str] | None = None, timeout: float = 20.0) -> None:
        self._allow = frozenset(allow) if allow else _DEFAULT_ALLOW
        self._timeout = timeout

    async def run(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command")
        if not command:
            return ToolResult.failure("shell requires 'command'")

        argv = shlex.split(str(command))
        if not argv:
            return ToolResult.failure("empty command")
        if argv[0] not in self._allow:
            return ToolResult.failure(f"command not allowed: {argv[0]!r}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            return ToolResult.failure(f"timed out after {self._timeout}s")
        except FileNotFoundError:
            return ToolResult.failure(f"not found: {argv[0]!r}")

        out = stdout.decode(errors="replace").strip()
        if proc.returncode != 0:
            return ToolResult.failure(stderr.decode(errors="replace").strip() or "non-zero exit")
        return ToolResult.success(output=out, observations=[f"ran {argv[0]} -> {len(out)} chars"])
