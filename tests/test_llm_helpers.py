from __future__ import annotations

import json

from openmuse.llm.base import ThinkStreamFilter, split_think
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
