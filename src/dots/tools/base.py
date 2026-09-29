"""The Tool protocol, a typed result, and a small registry."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """What a tool hands back to the runtime."""

    ok: bool = True
    output: Any = None
    error: str | None = None
    observations: list[str] = Field(default_factory=list)

    @classmethod
    def success(cls, output: Any = None, *, observations: list[str] | None = None) -> ToolResult:
        return cls(ok=True, output=output, observations=observations or [])

    @classmethod
    def failure(cls, error: str) -> ToolResult:
        return cls(ok=False, error=error)


@runtime_checkable
class Tool(Protocol):
    """A named, async, side-effecting capability."""

    name: str

    async def run(self, **kwargs: Any) -> ToolResult: ...


class ToolRegistry:
    """Name → tool lookup with helpful errors."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            known = ", ".join(sorted(self._tools)) or "<none>"
            raise KeyError(f"unknown tool {name!r}; registered: {known}") from None

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)
