"""OpenAI Chat Completions–compatible provider.

Works with: DeepSeek (``https://api.deepseek.com``), OpenAI, OpenRouter, Ollama,
vLLM, LM Studio, Anthropic/Gemini OpenAI-compatible endpoints, and any internal
gateway that speaks ``/chat/completions`` (extra headers/body supported).
"""

from __future__ import annotations

from typing import Any

import openai
from openai import NOT_GIVEN, AsyncOpenAI
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from openmuse.config import LLMSettings
from openmuse.llm.base import BaseLLM, DeltaCallback, ThinkStreamFilter, split_think
from openmuse.logger import logger
from openmuse.schema import Function, LLMResponse, Message, ToolCall, new_id

_RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class OpenAIChatLLM(BaseLLM):
    name = "openai"
    supports_native_tools = True

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.api_key or "EMPTY",
            base_url=settings.base_url or None,
            timeout=settings.timeout,
            max_retries=0,  # we retry ourselves so streaming failures are covered too
            default_headers=settings.extra_headers or None,
        )

    # ------------------------------------------------------------------ public
    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        params: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                m.to_openai(include_reasoning=self.settings.pass_reasoning) for m in messages
            ],
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice
        if self.settings.extra_body:
            params["extra_body"] = self.settings.extra_body

        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(_RETRYABLE),
            stop=stop_after_attempt(max(1, self.settings.max_retries + 1)),
            wait=wait_exponential(multiplier=2, min=2, max=60),
            reraise=True,
        ):
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    logger.warning(
                        "LLM retry {}/{}",
                        attempt.retry_state.attempt_number - 1,
                        self.settings.max_retries,
                    )
                if self.settings.stream:
                    return await self._ask_stream(params, on_delta)
                return await self._ask_once(params)
        raise RuntimeError("unreachable")  # pragma: no cover

    async def close(self) -> None:
        await self.client.close()

    # ------------------------------------------------------------------ internals
    async def _ask_once(self, params: dict[str, Any]) -> LLMResponse:
        completion = await self.client.chat.completions.create(**params, stream=False)
        choice = completion.choices[0]
        msg = choice.message
        content, think_reasoning = split_think(msg.content)
        reasoning = getattr(msg, "reasoning_content", None) or think_reasoning
        tool_calls = [
            ToolCall(
                id=tc.id or new_id(),
                function=Function(name=tc.function.name, arguments=tc.function.arguments or "{}"),
            )
            for tc in (msg.tool_calls or [])
            if getattr(tc, "function", None) is not None
        ]
        usage = completion.usage.model_dump(exclude_none=True) if completion.usage else {}
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            reasoning=reasoning,
            finish_reason=choice.finish_reason,
            usage=usage,
            model=completion.model,
        )

    async def _ask_stream(
        self, params: dict[str, Any], on_delta: DeltaCallback | None
    ) -> LLMResponse:
        stream = await self.client.chat.completions.create(
            **params, stream=True, stream_options={"include_usage": True}
        )
        think = ThinkStreamFilter()
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_acc: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: dict[str, Any] = {}
        model: str | None = None

        async for chunk in stream:
            if chunk.usage:
                usage = chunk.usage.model_dump(exclude_none=True)
            model = model or getattr(chunk, "model", None)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            if delta is None:
                continue
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                reasoning_parts.append(rc)
            if delta.content:
                visible = think.feed(delta.content)
                if visible:
                    content_parts.append(visible)
                    if on_delta:
                        on_delta(visible)
            for tc in delta.tool_calls or []:
                idx = tc.index if tc.index is not None else 0
                acc = tool_acc.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                if tc.id:
                    acc["id"] = tc.id
                if tc.function is not None:
                    if tc.function.name:
                        acc["name"] += tc.function.name
                    if tc.function.arguments:
                        acc["arguments"] += tc.function.arguments

        tail = think.flush()
        if tail:
            content_parts.append(tail)
            if on_delta:
                on_delta(tail)

        tool_calls = [
            ToolCall(
                id=acc["id"] or new_id(),
                function=Function(name=acc["name"], arguments=acc["arguments"] or "{}"),
            )
            for _, acc in sorted(tool_acc.items())
            if acc["name"]
        ]
        content = "".join(content_parts).strip() or None
        reasoning = "".join(reasoning_parts).strip() or think.reasoning
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            reasoning=reasoning,
            finish_reason=finish_reason,
            usage=usage,
            model=model,
        )


__all__ = ["OpenAIChatLLM", "NOT_GIVEN"]
