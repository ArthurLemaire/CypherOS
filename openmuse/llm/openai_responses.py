"""OpenAI Responses API–compatible provider (``POST {base_url}/responses``).

Useful for OpenAI's Responses endpoint and for "agent app" gateways that expose
a Responses-shaped API. Some of those gateways silently ignore client-side
``tools`` (no error, the model just never calls one); pair this provider with
``tool_mode = "prompt"`` in that case — ``auto`` can only catch endpoints that
*reject* tools.
"""

from __future__ import annotations

from typing import Any

import openai
from openai import AsyncOpenAI
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
from openmuse.logger import logger
from openmuse.schema import Function, LLMResponse, Message, Role, ToolCall, new_id

_RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


def _to_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append(
            {
                "type": "function",
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return out


def _to_input_items(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for m in messages:
        if m.role == Role.SYSTEM:
            if m.content:
                instructions.append(m.content)
        elif m.role == Role.USER:
            items.append({"role": "user", "content": m.content or ""})
        elif m.role == Role.ASSISTANT:
            if m.content:
                items.append({"role": "assistant", "content": m.content})
            for tc in m.tool_calls or []:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.wire_arguments(),
                    }
                )
        elif m.role == Role.TOOL:
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": m.tool_call_id or "",
                    "output": m.content or "",
                }
            )
    return ("\n\n".join(instructions) or None), items


class OpenAIResponsesLLM(BaseLLM):
    name = "openai_responses"
    supports_native_tools = True

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.api_key or "EMPTY",
            base_url=settings.base_url or None,
            timeout=settings.timeout,
            max_retries=0,
            default_headers=settings.extra_headers or None,
        )

    async def ask(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        instructions, items = _to_input_items(messages)
        params: dict[str, Any] = {
            "model": self.settings.model,
            "input": items,
            "temperature": self.settings.temperature,
            "max_output_tokens": self.settings.max_tokens,
        }
        if instructions:
            params["instructions"] = instructions
        if tools:
            params["tools"] = _to_responses_tools(tools)
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
                try:
                    if self.settings.stream:
                        return await self._ask_stream(params, on_delta)
                    return await self._ask_once(params)
                except openai.BadRequestError as e:
                    if tools and says_no_tools(str(e)):
                        raise ToolsUnsupported(str(e)) from e
                    raise
        raise RuntimeError("unreachable")  # pragma: no cover

    async def close(self) -> None:
        await self.client.close()

    # ------------------------------------------------------------------ internals
    def _parse(self, resp: Any) -> LLMResponse:
        texts: list[str] = []
        reasoning: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in getattr(resp, "output", None) or []:
            itype = getattr(item, "type", None)
            if itype == "message":
                for part in getattr(item, "content", None) or []:
                    if getattr(part, "type", None) in ("output_text", "text"):
                        texts.append(getattr(part, "text", "") or "")
            elif itype == "function_call":
                tool_calls.append(
                    ToolCall(
                        id=getattr(item, "call_id", None) or getattr(item, "id", None) or new_id(),
                        function=Function(
                            name=getattr(item, "name", ""),
                            arguments=getattr(item, "arguments", "") or "{}",
                        ),
                    )
                )
            elif itype == "reasoning":
                for s in getattr(item, "summary", None) or []:
                    reasoning.append(getattr(s, "text", "") or "")
        content, think = split_think("".join(texts).strip() or None)
        usage = resp.usage.model_dump(exclude_none=True) if getattr(resp, "usage", None) else {}
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            reasoning="\n".join(r for r in reasoning if r) or think,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=usage,
            model=getattr(resp, "model", None),
        )

    async def _ask_once(self, params: dict[str, Any]) -> LLMResponse:
        resp = await self.client.responses.create(**params, stream=False)
        return self._parse(resp)

    async def _ask_stream(
        self, params: dict[str, Any], on_delta: DeltaCallback | None
    ) -> LLMResponse:
        stream = await self.client.responses.create(**params, stream=True)
        think = ThinkStreamFilter()
        final: Any = None
        streamed: list[str] = []
        async for event in stream:
            etype = getattr(event, "type", "")
            if etype == "response.output_text.delta":
                visible = think.feed(getattr(event, "delta", "") or "")
                if visible:
                    streamed.append(visible)
                    if on_delta:
                        on_delta(visible)
            elif etype in ("response.completed", "response.incomplete"):
                final = getattr(event, "response", None)
            elif etype == "response.failed":
                err = getattr(getattr(event, "response", None), "error", None)
                raise openai.APIError(str(err or "response failed"), request=None, body=None)  # type: ignore[arg-type]
        tail = think.flush()
        if tail:
            streamed.append(tail)
            if on_delta:
                on_delta(tail)
        if final is not None:
            parsed = self._parse(final)
            if parsed.content is None and streamed:
                parsed.content = "".join(streamed).strip() or None
            parsed.reasoning = parsed.reasoning or think.reasoning
            return parsed
        return LLMResponse(content="".join(streamed).strip() or None, reasoning=think.reasoning)


__all__ = ["OpenAIResponsesLLM"]
