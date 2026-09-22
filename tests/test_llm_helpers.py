from __future__ import annotations

import json

from openmuse.llm.base import ThinkStreamFilter, ToolsUnsupported, says_no_tools, split_think
from openmuse.llm.prompt_tools import convert_messages, parse_tool_calls
from openmuse.schema import Function, Message, ToolCall


def test_think_filter_handles_split_tags():
    f = ThinkStreamFilter()
    visible = ""
    for chunk in ["Hello <thi", "nk>secret reasoning</th", "ink> world", "!"]:
        visible += f.feed(chunk)
    visible += f.flush()
    assert visible == "Hello  world!"
    assert f.reasoning == "secret reasoning"


def test_think_filter_text_in_same_chunk_as_close_tag():
    # DeepSeek-style streams often deliver "</think>" glued to the first visible tokens.
    f = ThinkStreamFilter()
    out = (
        f.feed("<think>The")
        + f.feed(" user")
        + f.feed("</think>你好！我能")
        + f.feed("帮你写作")
        + f.flush()
    )
    assert out == "你好！我能帮你写作"
    assert f.reasoning == "The user"


def test_think_filter_random_splits_never_lose_text():
    import random

    full = "<think>plan things</think>你好！我能帮你写作、翻译。"
    rng = random.Random(7)
    for _ in range(300):
        f = ThinkStreamFilter()
        out, i = "", 0
        while i < len(full):
            n = rng.randint(1, 9)
            out += f.feed(full[i : i + n])
            i += n
        out += f.flush()
        assert out == "你好！我能帮你写作、翻译。"
        assert f.reasoning == "plan things"


def test_think_filter_unterminated_goes_to_reasoning():
    f = ThinkStreamFilter()
    out = f.feed("<think>still thinking")
    out += f.flush()
    assert out == ""
    assert f.reasoning == "still thinking"


def test_split_think_non_streaming():
    content, reasoning = split_think("<think>plan</think>Answer")
    assert content == "Answer"
    assert reasoning == "plan"
    assert split_think("plain") == ("plain", None)


def test_parse_tool_calls():
    text = (
        'Let me check.\n<tool_call>\n{"name": "web_search", "arguments": {"query": "北京 天气"}}\n</tool_call>'
        '\n<tool_call>{"name":"terminate","arguments":{"status":"success","summary":"done"}}</tool_call>'
    )
    visible, calls = parse_tool_calls(text)
    assert visible == "Let me check."
    assert [c.name for c in calls] == ["web_search", "terminate"]
    assert calls[0].arguments == {"query": "北京 天气"}


def test_parse_tool_calls_ignores_garbage():
    visible, calls = parse_tool_calls("<tool_call>{not json}</tool_call> ok")
    assert calls == []
    assert visible == "ok"


def test_parse_tool_calls_accepts_fenced_calls_from_small_models():
    known = {"python_execute", "files"}
    # Gemma: a ```tool_call fence instead of the tags
    gemma = (
        "Let me compute that.\n```tool_call\n"
        '{"name": "python_execute", "arguments": {"code": "print(1)"}}\n```'
    )
    visible, calls = parse_tool_calls(gemma, known)
    assert [c.function.name for c in calls] == ["python_execute"]
    assert calls[0].arguments["code"] == "print(1)"
    assert visible == "Let me compute that."
    # a ```json fence with "parameters" for the arguments
    fenced_json = '```json\n{"name": "files", "parameters": {"action": "list"}}\n```'
    _, calls = parse_tool_calls(fenced_json, known)
    assert [c.function.name for c in calls] == ["files"]
    assert calls[0].arguments == {"action": "list"}
    # JSON the model is merely quoting stays text: not a known tool / no arguments
    quoted = 'The config is:\n```json\n{"name": "openmuse", "version": "0.1.0"}\n```'
    visible, calls = parse_tool_calls(quoted, known)
    assert calls == [] and visible == quoted
    _, calls = parse_tool_calls('```json\n{"name": "rm", "arguments": {}}\n```', known)
    assert calls == []
    # without a known set, a fenced call still needs an arguments object
    _, calls = parse_tool_calls('```json\n{"name": "rm", "arguments": {}}\n```')
    assert [c.function.name for c in calls] == ["rm"]
    # the tags win when both are present
    both = '<tool_call>{"name": "files", "arguments": {}}</tool_call>\n```json\n{"a": 1}\n```'
    visible, calls = parse_tool_calls(both, known)
    assert [c.function.name for c in calls] == ["files"] and visible == '```json\n{"a": 1}\n```'
    # Llama 3.x: the whole reply is a bare JSON object, real newlines inside the code string
    bare = (
        "Let me run that.\n"
        '{"name": "python_execute", "parameters": {"code": "for i in range(3):\n    print(i)"}}'
    )
    visible, calls = parse_tool_calls(bare, known)
    assert [c.function.name for c in calls] == ["python_execute"]
    assert calls[0].arguments["code"] == "for i in range(3):\n    print(i)"
    assert visible == "Let me run that."
    # ...but a JSON object that is not one of our tools, or has no arguments, is an answer
    for text in ('{"name": "Kyoto", "arguments": {}}', '{"name": "files"}', '{"a": 1}'):
        visible, calls = parse_tool_calls(text, known)
        assert calls == [] and visible == text


async def test_native_mode_rescues_a_call_written_as_text():
    from openmuse.llm.mock import MockLLM
    from openmuse.llm.prompt_tools import PromptToolAdapter
    from openmuse.schema import LLMResponse

    tools = [{"type": "function", "function": {"name": "files", "parameters": {}}}]
    inner = MockLLM(
        [
            LLMResponse(content='{"name": "files", "parameters": {"action": "list"}}'),
            LLMResponse(content="Here is the list."),
        ]
    )
    llm = PromptToolAdapter(inner, native_first=True)
    resp = await llm.ask([Message.user("list files")], tools)
    assert [c.function.name for c in resp.tool_calls] == ["files"]
    assert resp.content is None and resp.finish_reason == "tool_calls"
    assert inner.calls[0]["tools"] == tools, "still native: tools went to the provider"
    plain = await llm.ask([Message.user("thanks")], tools)
    assert plain.content == "Here is the list." and not plain.tool_calls


def test_convert_messages_flattens_tool_roles():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    tc = ToolCall(id="c1", function=Function(name="echo", arguments=json.dumps({"x": 1})))
    msgs = [
        Message.system("sys"),
        Message.user("hi"),
        Message.assistant(content=None, tool_calls=[tc]),
        Message.tool("result-1", "c1", "echo"),
        Message.tool("result-2", "c1", "echo"),
    ]
    out = convert_messages(msgs, tools)
    roles = [m.role.value for m in out]
    assert roles == ["system", "user", "assistant", "user"]
    assert "Tool calling protocol" in out[0].content
    assert "<tool_call>" in out[2].content
    assert out[3].content.count("<tool_result") == 2


def test_says_no_tools_matches_real_endpoint_errors():
    for msg in (
        "Error code: 400 - {'error': {'message': 'registry.ollama.ai/library/gemma3:4b does "
        "not support tools', 'type': 'api_error'}}",
        '"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set',
        "This model does not support function calling.",
        "tools are not supported by this endpoint",
        "Tool use is unsupported for model foo",
    ):
        assert says_no_tools(msg), msg
    for msg in (
        "Invalid parameter: 'tool_choice' must be one of 'none', 'auto'",
        "This model's maximum context length is 8192 tokens",
        "Unsupported value: 'temperature' does not support 2.5 with this model",
    ):
        assert not says_no_tools(msg), msg


async def test_auto_mode_switches_to_prompt_tools_when_the_endpoint_rejects_them():
    from openmuse.llm.mock import MockLLM
    from openmuse.llm.prompt_tools import PromptToolAdapter
    from openmuse.schema import LLMResponse

    tools = [{"type": "function", "function": {"name": "echo", "parameters": {}}}]

    class Rejecting(MockLLM):
        async def ask(
            self, messages, tools=None, tool_choice="auto", on_delta=None, max_tokens=None
        ):
            if tools:
                raise ToolsUnsupported("model x does not support tools")
            return await super().ask(messages, tools, tool_choice, on_delta, max_tokens)

    inner = Rejecting(
        [LLMResponse(content='<tool_call>{"name": "echo", "arguments": {"x": 1}}</tool_call>')]
    )
    llm = PromptToolAdapter(inner, native_first=True)
    assert llm.supports_native_tools
    resp = await llm.ask([Message.user("hi")], tools)
    # the native attempt failed, the prompt-mode retry parsed the call
    assert [c.function.name for c in resp.tool_calls] == ["echo"]
    assert not llm.supports_native_tools
    assert inner.calls[-1]["tools"] is None
    assert "Tool calling protocol" in inner.calls[-1]["messages"][0].content
    # sticky: later requests go straight to prompt mode (one native attempt in total)
    inner.script.append(LLMResponse(content="done"))
    await llm.ask([Message.user("again")], tools)
    assert all(c["tools"] is None for c in inner.calls)

    # a provider that supports tools natively is never touched
    fine = MockLLM([LLMResponse(content="ok")])
    plain = PromptToolAdapter(fine, native_first=True)
    await plain.ask([Message.user("hi")], tools)
    assert fine.calls[0]["tools"] == tools and plain.supports_native_tools


def test_cut_off_tool_arguments_go_to_the_provider_as_an_empty_object():
    """A gateway truncated the arguments mid-string; the history must still be accepted
    by a strict endpoint (Ollama answers 400 'invalid tool call arguments' otherwise)."""
    cut = ToolCall(id="c1", function=Function(name="files", arguments='{"action": "write", "con'))
    assert cut.arguments == {"__raw__": '{"action": "write", "con'}
    wire = Message.assistant(tool_calls=[cut]).to_openai()["tool_calls"][0]["function"]
    assert wire == {"name": "files", "arguments": "{}"}
    fine = ToolCall(function=Function(name="files", arguments='{"action": "list"}'))
    assert (
        Message.assistant(tool_calls=[fine]).to_openai()["tool_calls"][0]["function"]["arguments"]
        == '{"action": "list"}'
    )


async def test_ask_complete_tries_again_with_room_when_the_reply_was_cut_off():
    from openmuse.llm.mock import MockLLM
    from openmuse.schema import LLMResponse

    # a reasoning model that spent the whole budget thinking, then answered on the retry
    llm = MockLLM(
        [
            LLMResponse(content="", finish_reason="length"),
            LLMResponse(content="[]", finish_reason="stop"),
        ]
    )
    resp = await llm.ask_complete([Message.user("list")], tools=None)
    assert resp.content == "[]"
    assert llm.calls[0]["max_tokens"] is None and llm.calls[1]["max_tokens"] == 16384
    # a complete answer is not asked twice
    llm.script.append(LLMResponse(content="done", finish_reason="stop"))
    assert (await llm.ask_complete([Message.user("x")])).content == "done" and len(llm.calls) == 3
