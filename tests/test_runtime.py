from __future__ import annotations

from dots.core.event import Event
from dots.core.eventlog import EventLog
from dots.core.runtime import Runtime
from dots.core.state import State
from dots.memory.inmemory import InMemoryMemory
from dots.planner.goal import Goal
from dots.planner.planner import Action, Plan
from dots.tools.base import ToolRegistry
from dots.tools.builtin import NoteTool


class ApprovalPlanner:
    async def plan(self, goal, events, recall):
        return Plan(
            actions=[Action(tool="note", args={"text": "sensitive"}, needs_approval=True)],
            reasoning="needs a human",
        )


def _runtime(planner) -> Runtime:
    return Runtime(
        planner=planner,
        memory=InMemoryMemory(),
        tools=ToolRegistry([NoteTool()]),
        log=EventLog(),
    )


async def test_step_acts_and_learns() -> None:
    from dots.planner.planner import HeuristicPlanner

    rt = _runtime(HeuristicPlanner())
    result = await rt.step(Goal("go"), State(), [Event.manual("hi")])
    assert result.acted
    assert result.learned


async def test_step_pauses_for_approval() -> None:
    rt = _runtime(ApprovalPlanner())
    state = State()
    result = await rt.step(Goal("go"), state, [Event.manual("hi")])
    assert result.paused_for_approval is not None
    assert state.awaiting_approval is not None
    assert not result.acted


async def test_replay_reconstructs_plans() -> None:
    from dots.planner.planner import HeuristicPlanner

    rt = _runtime(HeuristicPlanner())
    await rt.step(Goal("go"), State(), [Event.manual("a")])
    await rt.step(Goal("go"), State(), [Event.manual("b")])
    plans = await rt.replay(rt.log)
    assert len(plans) == 2
    assert all(isinstance(p, Plan) for p in plans)


async def test_unknown_tool_is_isolated() -> None:
    class BadPlanner:
        async def plan(self, goal, events, recall):
            return Plan(actions=[Action(tool="does-not-exist")])

    rt = _runtime(BadPlanner())
    result = await rt.step(Goal("go"), State(), [Event.manual("x")])
    assert result.results
    assert not result.results[0].ok
