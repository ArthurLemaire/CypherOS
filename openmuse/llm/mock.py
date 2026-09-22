"""A scripted LLM for tests and offline demos."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openmuse.llm.base import BaseLLM, DeltaCallback
from openmuse.schema import LLMResponse, Message

Script = LLMResponse | Callable[[list[Message]], LLMResponse]


class MockLLM(BaseLLM):
    name = "mock"

    def __init__(self, script: list[Script] | None = None):
        self.script: list[Script] = list(script or [])
        self.calls: list[dict[str, Any]] = []

    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": list(messages), "tools": tools, "max_tokens": max_tokens})
        if not self.script:
            resp = LLMResponse(content="(mock) I have nothing more to say.", finish_reason="stop")
        else:
            item = self.script.pop(0)
            resp = item(messages) if callable(item) else item
        if on_delta and resp.content:
            on_delta(resp.content)
        return resp


__all__ = ["MockLLM"]
