from __future__ import annotations

import json
from typing import Any

from openmuse.agent import MuseAgent
from openmuse.config import Settings
from openmuse.goals import GoalStore
from openmuse.llm import MockLLM
from openmuse.memory import MemoryStore
from openmuse.schema import Function, LLMResponse, Message, Role, ToolCall, ToolResult
from openmuse.sentinel import AuditLog, Sentinel
from openmuse.tools import Goals, Remember, Terminate, ToolCollection
from openmuse.tools.base import BaseTool
from openmuse.ui import HeadlessUI


class Adder(BaseTool):
    name: str = "add"
    description: str = "add two numbers"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
    }

    async def execute(self, a: float = 0, b: float = 0, **_: Any) -> ToolResult:
        return ToolResult(output=str(a + b))


def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


def make_agent(
    settings: Settings, script: list, ui: HeadlessUI | None = None, extra_tools: list | None = None
):
    ui = ui or HeadlessUI()
    memory = MemoryStore(settings.memory_db)
    goals = GoalStore(settings.goals_db)
    tools = ToolCollection(
        Terminate(), Adder(), Remember(store=memory), Goals(store=goals), *(extra_tools or [])
    )
    audit = AuditLog(settings.audit_file)
    sentinel = Sentinel(settings.sentinel, audit, ui)
    llm = MockLLM(script)
    agent = MuseAgent(settings, llm, tools, sentinel, ui, audit, memory=memory, goals=goals)
    return agent, llm, ui, memory, goals


async def test_tool_loop_then_terminate(settings: Settings):
    script = [
        LLMResponse(content="Let me add.", tool_calls=[tc("add", a=2, b=3)]),
        LLMResponse(tool_calls=[tc("terminate", status="success", summary="2+3=5")]),
    ]
    agent, llm, ui, *_ = make_agent(settings, script)
    final = await agent.run("what is 2+3?")
    assert final == "2+3=5"
    # tool result was fed back to the model
    second_call_msgs = llm.calls[1]["messages"]
    tool_msgs = [m for m in second_call_msgs if m.role == Role.TOOL]
    assert tool_msgs and tool_msgs[0].content == "5"
    assert llm.calls[0]["messages"][0].role == Role.SYSTEM
    assert "add" in llm.calls[0]["messages"][0].content  # tool names listed in system prompt


async def test_plain_answer_ends_turn(settings: Settings):
    agent, llm, *_ = make_agent(settings, [LLMResponse(content="Just an answer")])
    assert await agent.run("hi") == "Just an answer"
    assert len(llm.calls) == 1


async def test_unknown_tool_reports_error(settings: Settings):
    script = [
        LLMResponse(tool_calls=[tc("does_not_exist", x=1)]),
        LLMResponse(content="ok, I'll stop"),
    ]
    agent, llm, *_ = make_agent(settings, script)
    await agent.run("go")
    tool_msg = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL][0]
    assert "unknown tool" in tool_msg.content


async def test_sentinel_denial_reaches_model(settings: Settings):
    settings.sentinel.always_ask_tools = ["add"]
    script = [
        LLMResponse(tool_calls=[tc("add", a=1, b=1)]),
        LLMResponse(content="Understood, blocked."),
    ]
    agent, llm, ui, *_ = make_agent(settings, script, ui=HeadlessUI(approve=False))
    final = await agent.run("add")
    assert final == "Understood, blocked."
    tool_msg = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL][0]
    assert "Sentinel blocked" in tool_msg.content


async def test_memory_and_goals_injected_into_prompt(settings: Settings):
    script = [
        LLMResponse(
            tool_calls=[
                tc("remember", content="User loves jazz", category="preference"),
                tc(
                    "goals",
                    action="create",
                    title="Learn piano",
                    steps=["Find teacher", "Practice daily"],
                ),
            ]
        ),
        LLMResponse(content="Noted."),
        LLMResponse(content="Second turn."),
    ]
    agent, llm, *_ = make_agent(settings, script)
    await agent.run("I love jazz and want to learn piano")
    await agent.run("what do you know about me?")
    system = llm.calls[2]["messages"][0].content
    assert "User loves jazz" in system
    assert "Learn piano" in system and "next: 1. Find teacher" in system


async def test_max_steps_wraps_up(settings: Settings):
    settings.agent.max_steps = 2
    script = [
        LLMResponse(tool_calls=[tc("add", a=1, b=1)]),
        LLMResponse(tool_calls=[tc("add", a=1, b=2)]),
        LLMResponse(content="Summary: I added numbers."),
    ]
    agent, llm, *_ = make_agent(settings, script)
    final = await agent.run("keep adding")
    assert final == "Summary: I added numbers."
    assert llm.calls[2]["tools"] is None  # wrap-up call is made without tools


async def test_stuck_detection_nudges(settings: Settings):
    same = lambda: LLMResponse(tool_calls=[tc("add", a=1, b=1)])  # noqa: E731
    script = [same(), same(), same(), LLMResponse(content="changing strategy")]
    agent, llm, *_ = make_agent(settings, script)
    await agent.run("loop")
    nudges = [m for m in agent.messages if m.role == Role.USER and "repeating" in (m.content or "")]
    assert len(nudges) == 1


async def test_context_window_trims_at_user_boundary(settings: Settings):
    settings.agent.max_context_messages = 4
    agent, *_ = make_agent(settings, [])
    from openmuse.schema import Message

    agent.messages = [
        Message.user("u1"),
        Message.assistant(tool_calls=[tc("add")]),
        Message.tool("2", "x", "add"),
        Message.assistant("a1"),
        Message.user("u2"),
        Message.assistant("a2"),
    ]
    ctx = agent.context_messages()
    assert [m.content for m in ctx] == ["u2", "a2"]


async def test_session_roundtrip(settings: Settings, tmp_path):
    agent, *_ = make_agent(settings, [LLMResponse(content="hello")])
    agent.session_file = tmp_path / "s.json"
    await agent.run("hi")
    agent2, *_ = make_agent(settings, [])
    assert agent2.load_session(tmp_path / "s.json") == 2
    assert agent2.messages[-1].content == "hello"


async def test_session_restore_repairs_unanswered_tool_calls(settings: Settings, tmp_path):
    """A restart while a tool call waited for approval leaves an assistant message whose
    tool calls have no results; the next request would be rejected by the provider."""
    agent, *_ = make_agent(settings, [])
    call = tc("add", a=1, b=2)
    agent.messages = [Message.user("add"), LLMResponse(content="", tool_calls=[call]).to_message()]
    agent.session_file = tmp_path / "s.json"
    agent._save_session()
    agent2, llm, *_ = make_agent(settings, [LLMResponse(content="ok")])
    agent2.load_session(tmp_path / "s.json")
    assert agent2.messages[-1].role == Role.TOOL
    assert agent2.messages[-1].tool_call_id == call.id
    assert "restarted" in (agent2.messages[-1].content or "")
    await agent2.run("continue")
    roles = [m.role for m in llm.calls[0]["messages"]]
    assert roles.count(Role.TOOL) == 1, "history sent to the model is well-formed"
