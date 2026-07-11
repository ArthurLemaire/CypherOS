"""Tool base classes.

Every capability the agent has is a :class:`BaseTool`. Besides the JSON schema
the model sees, a tool declares *how dangerous it is* so the Sentinel can decide
whether to run it, ask the user, or refuse:

* ``risk`` – static default risk level (see :class:`~openmuse.schema.RiskLevel`)
* ``reads_private_data`` – executing it exposes the user's private data to the
  model (emails, files, memories). Once that happened the session is *tainted*.
* ``egress`` – it can send data out of the machine (network, email...).
* ``accepts_secrets`` – ``{{vault:NAME}}`` placeholders in its arguments are
  resolved to real secrets right before execution (the model never sees them).

Tools may refine these per call by overriding :meth:`assess`.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from openmuse.logger import logger
from openmuse.schema import RiskLevel, ToolResult


class CallAssessment(BaseModel):
    """Per-call risk assessment handed to the Sentinel."""

    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = False
    egress: bool = False
    # Network destination (hostname) if known, e.g. "example.com". ``None`` with
    # ``egress=True`` means "unknown destination" (shell, python...).
    egress_target: str | None = None
    # What a standing approval for this call should be bound to: a host, a recipient, a
    # program name. Defaults to ``egress_target``; ``None`` means "the whole tool".
    target: str | None = None
    # One-line, human-readable description shown in approval prompts / audit log.
    summary: str = ""
    # Extra warnings ("command contains rm -rf", ...).
    warnings: list[str] = Field(default_factory=list)


def short_json(args: dict[str, Any], limit: int = 200) -> str:
    text = json.dumps(args, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


class BaseTool(ABC, BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})

    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = False
    egress: bool = False
    accepts_secrets: bool = False

    async def __call__(self, **kwargs: Any) -> ToolResult:
        return await self.execute(**kwargs)

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool. Must not raise for expected failures – return ``ToolResult.fail``."""

    def to_param(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=self.risk,
            reads_private_data=self.reads_private_data,
            egress=self.egress,
            summary=f"{self.name}({short_json(args)})",
        )

    async def cleanup(self) -> None:  # pragma: no cover - default no-op
        return None


async def safe_execute(tool: BaseTool, args: dict[str, Any] | None = None) -> ToolResult:
    """Run a tool, converting every failure into a :class:`ToolResult` error."""
    args = args or {}
    if "__raw__" in args:
        raw = str(args["__raw__"])
        hint = (
            " The JSON stops mid-way, so the arguments were probably cut off in transit: "
            "call the tool again with less content at a time (write the file in parts with "
            "`append`, or generate it with python_execute)."
            if len(raw) > 1000
            else ""
        )
        return ToolResult.fail(
            f"arguments for {tool.name} were not valid JSON ({len(raw)} chars): "
            f"...{raw[-120:]}{hint}"
        )
    try:
        result = await tool.execute(**args)
    except TypeError as exc:
        return ToolResult.fail(f"bad arguments for {tool.name}: {exc}")
    except Exception as exc:  # noqa: BLE001 – tools must never crash the loop
        logger.exception("tool {} crashed", tool.name)
        return ToolResult.fail(f"{type(exc).__name__}: {exc}")
    if not isinstance(result, ToolResult):
        # third-party tools do not always honour the signature
        result = ToolResult(output=str(result))  # type: ignore[unreachable]
    return result


class ToolCollection:
    """An ordered, name-addressable set of tools."""

    def __init__(self, *tools: BaseTool):
        self.tools: list[BaseTool] = []
        self.tool_map: dict[str, BaseTool] = {}
        self.add(*tools)

    def add(self, *tools: BaseTool) -> ToolCollection:
        for tool in tools:
            if tool.name in self.tool_map:
                logger.warning("tool '{}' already registered – replacing", tool.name)
                self.tools = [t for t in self.tools if t.name != tool.name]
            self.tools.append(tool)
            self.tool_map[tool.name] = tool
        return self

    def remove(self, name: str) -> None:
        self.tool_map.pop(name, None)
        self.tools = [t for t in self.tools if t.name != name]

    def get(self, name: str) -> BaseTool | None:
        return self.tool_map.get(name)

    def to_params(self) -> list[dict[str, Any]]:
        return [t.to_param() for t in self.tools]

    async def execute(self, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult.fail(f"unknown tool: {name}")
        return await safe_execute(tool, args)

    async def cleanup(self) -> None:
        for tool in self.tools:
            try:
                await tool.cleanup()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cleanup of {} failed: {}", tool.name, exc)

    def __iter__(self):
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    def __contains__(self, name: object) -> bool:
        return name in self.tool_map


__all__ = ["BaseTool", "CallAssessment", "ToolCollection", "safe_execute", "short_json"]
