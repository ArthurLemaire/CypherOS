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
from openmuse.llm.base import (
    BaseLLM,
    DeltaCallback,
    ThinkStreamFilter,
    ToolsUnsupported,
    says_no_tools,
    split_think,
)
from openmuse.llm.vision import content_parts, has_images, without_images
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
        max_tokens: int | None = None,
    ) -> LLMResponse:
        pictures = has_images(messages)
        with_images = (
            pictures and self.settings.vision != "off" and self.vision_available is not False
        )
        params: dict[str, Any] = {
            "model": self.settings.model,
            "messages": self._wire_messages(messages, with_images),
            "temperature": self.settings.temperature,
            "max_tokens": max_tokens or self.settings.max_tokens,
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice
        if self.settings.extra_body:
            params["extra_body"] = self.settings.extra_body
        try:
            resp = await self._send(params, on_delta)
        except openai.BadRequestError as e:
            if tools and says_no_tools(str(e)):
                raise ToolsUnsupported(str(e)) from e
            if with_images and self.settings.vision == "auto":
                # the endpoint refused the request with pictures in it: the same request
                # with the text only, and no pictures for the rest of this run
                logger.warning(
                    "the endpoint rejected a message with images ({}); sending text only "
                    'from now on — set llm.vision = "off" to skip the attempt',
                    str(e).splitlines()[0][:200],
                )
                self.vision_available = False
                params["messages"] = self._wire_messages(messages, False)
                return await self._send(params, on_delta)
            raise
        if with_images and self.vision_available is None:
            self.vision_available = True
        return resp

    def _wire_messages(self, messages: list[Message], with_images: bool) -> list[dict[str, Any]]:
        wire = messages if with_images or not has_images(messages) else without_images(messages)
        out = []
        for m in wire:
            d = m.to_openai(include_reasoning=self.settings.pass_reasoning)
            if with_images and m.images:
                d["content"] = content_parts(m)
            out.append(d)
        return out

    async def _send(self, params: dict[str, Any], on_delta: DeltaCallback | None) -> LLMResponse:
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
