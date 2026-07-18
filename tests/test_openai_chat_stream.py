"""Streaming accumulation in OpenAIChatLLM, using fake SSE chunks (no network)."""

from __future__ import annotations

from types import SimpleNamespace as NS

from openmuse.config import LLMSettings
from openmuse.llm.openai_chat import OpenAIChatLLM


def _chunk(content=None, tool_calls=None, finish=None, reasoning=None, usage=None):
    delta = NS(content=content, tool_calls=tool_calls, reasoning_content=reasoning)
    return NS(choices=[NS(delta=delta, finish_reason=finish)], usage=usage, model="m")


def _tc(index, id=None, name=None, arguments=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=arguments))


class _FakeStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)


def _llm(chunks) -> OpenAIChatLLM:
    llm = OpenAIChatLLM(LLMSettings(api_key="x", base_url="http://localhost"))

    async def fake_create(**_):
        return _FakeStream(chunks)

    llm.client.chat.completions.create = fake_create  # type: ignore[method-assign]
    return llm


async def test_inline_think_then_text_in_same_chunk():
    chunks = [
        _chunk(""),
        _chunk("<think>The"),
        _chunk(" user wants"),
        _chunk("</think>你好！我能"),
        _chunk("帮你写作"),
        _chunk(None, finish="stop", usage=NS(model_dump=lambda exclude_none: {"total_tokens": 3})),
    ]
    deltas: list[str] = []
    resp = await _llm(chunks)._ask_stream({"model": "m", "messages": []}, deltas.append)
    assert "".join(deltas) == "你好！我能帮你写作"
    assert resp.content == "你好！我能帮你写作"
    assert resp.reasoning == "The user wants"
    assert resp.finish_reason == "stop"
    assert resp.usage == {"total_tokens": 3}


async def test_reasoning_content_field_and_tool_call_deltas():
    chunks = [
        _chunk(reasoning="thinking..."),
        _chunk("", tool_calls=[_tc(0, id="call_1", name="get_weather", arguments="")]),
        _chunk("", tool_calls=[_tc(0, arguments='{"city":')]),
        _chunk("", tool_calls=[_tc(0, arguments=' "北京"}')]),
        _chunk("", tool_calls=[_tc(1, id="call_2", name="terminate", arguments="{}")]),
        _chunk(None, finish="tool_calls"),
    ]
    resp = await _llm(chunks)._ask_stream({"model": "m", "messages": []}, None)
    assert resp.content is None
    assert resp.reasoning == "thinking..."
    assert [tc.id for tc in resp.tool_calls] == ["call_1", "call_2"]
    assert resp.tool_calls[0].arguments == {"city": "北京"}
    assert resp.finish_reason == "tool_calls"


async def test_tools_rejection_becomes_tools_unsupported():
    import httpx
    import openai
    import pytest

    from openmuse.llm.base import ToolsUnsupported
    from openmuse.schema import Message

    def bad_request(message: str):
        req = httpx.Request("POST", "http://localhost/chat/completions")
        resp = httpx.Response(400, request=req, json={"error": {"message": message}})
        return openai.BadRequestError(
            f"Error code: 400 - {{'error': {{'message': '{message}'}}}}",
            response=resp,
            body={"error": {"message": message}},
        )

    def llm_raising(message: str) -> OpenAIChatLLM:
        llm = OpenAIChatLLM(LLMSettings(api_key="x", base_url="http://localhost", stream=False))

        async def fake_create(**_):
            raise bad_request(message)

        llm.client.chat.completions.create = fake_create  # type: ignore[method-assign]
        return llm

    tools = [{"type": "function", "function": {"name": "echo", "parameters": {}}}]
    # Ollama's wording for a model without a tool template
    with pytest.raises(ToolsUnsupported):
        await llm_raising("registry.ollama.ai/library/gemma3:4b does not support tools").ask(
            [Message.user("hi")], tools
        )
    # the same error without tools in the request is not about tools
    with pytest.raises(openai.BadRequestError):
        await llm_raising("model does not support tools").ask([Message.user("hi")], None)
    # an unrelated 400 stays what it is
    with pytest.raises(openai.BadRequestError):
        await llm_raising("maximum context length is 8192 tokens").ask([Message.user("hi")], tools)
