"""Core data structures shared across the agent, LLM providers and tools."""

from __future__ import annotations

import json
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


class RiskLevel(str, Enum):
    """How dangerous a tool is when it runs unattended.

    * ``safe``      – read-only, local, no side effects worth mentioning.
    * ``moderate``  – has side effects, but reversible / low blast radius (write a
      file in the workspace, fetch a public web page).
    * ``sensitive`` – irreversible or externally visible (send an email, make a
      purchase, run an arbitrary shell command).
    """

    SAFE = "safe"
    MODERATE = "moderate"
    SENSITIVE = "sensitive"

    @property
    def rank(self) -> int:
        return {"safe": 0, "moderate": 1, "sensitive": 2}[self.value]


def new_id(prefix: str = "call") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Function(BaseModel):
    name: str
    arguments: str = "{}"

    def parsed_arguments(self) -> dict[str, Any]:
        if not self.arguments or not self.arguments.strip():
            return {}
        try:
            data = json.loads(self.arguments)
        except json.JSONDecodeError:
            return {"__raw__": self.arguments}
        return data if isinstance(data, dict) else {"value": data}


class ToolCall(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["function"] = "function"
    function: Function

    @property
    def name(self) -> str:
        return self.function.name

    @property
    def arguments(self) -> dict[str, Any]:
        return self.function.parsed_arguments()


class Message(BaseModel):
    role: Role
    content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    reasoning: str | None = None
    # Free-form metadata that never reaches the model (timestamps, step ids...)
    meta: dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------ factories
    @classmethod
    def system(cls, content: str) -> Message:
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(
        cls,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        reasoning: str | None = None,
    ) -> Message:
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls, reasoning=reasoning)

    @classmethod
    def tool(cls, content: str, tool_call_id: str, name: str | None = None) -> Message:
        return cls(role=Role.TOOL, content=content, tool_call_id=tool_call_id, name=name)

    # ------------------------------------------------------------------ export
    def to_openai(self, include_reasoning: bool = False) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role.value}
        if self.role == Role.TOOL:
            msg["tool_call_id"] = self.tool_call_id
            msg["content"] = self.content or ""
            if self.name:
                msg["name"] = self.name
            return msg
        msg["content"] = self.content if self.content is not None else ""
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in self.tool_calls
            ]
        if include_reasoning and self.reasoning and self.role == Role.ASSISTANT:
            msg["reasoning_content"] = self.reasoning
        return msg


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reasoning: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None

    def to_message(self) -> Message:
        return Message.assistant(
            content=self.content, tool_calls=self.tool_calls or None, reasoning=self.reasoning
        )


class ToolResult(BaseModel):
    """What a tool hands back to the agent."""

    output: str = ""
    error: str | None = None
    # Text shown to the human but not to the model (e.g. "saved screenshot to ...").
    system: str | None = None
    # Set by control tools (terminate) to stop the loop.
    stop: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None

    def for_model(self, max_chars: int = 20_000) -> str:
        text = f"Error: {self.error}" if self.error else (self.output or "(no output)")
        if len(text) > max_chars:
            head = text[: max_chars // 2]
            tail = text[-max_chars // 2 :]
            text = f"{head}\n\n... [truncated {len(text) - max_chars} chars] ...\n\n{tail}"
        return text

    @classmethod
    def fail(cls, error: str) -> ToolResult:
        return cls(error=error)


__all__ = [
    "AgentState",
    "Function",
    "LLMResponse",
    "Message",
    "RiskLevel",
    "Role",
    "ToolCall",
    "ToolResult",
    "new_id",
]
