from __future__ import annotations

import pytest

from dots.core.event import Event, EventKind
from dots.planner.goal import Goal
from dots.planner.planner import HeuristicPlanner


def test_goal_positional_and_validation() -> None:
    g = Goal("watch the market", max_actions=3)
    assert g.objective == "watch the market"
    assert g.max_actions == 3
    with pytest.raises(ValueError):
        Goal("   ")
    with pytest.raises(ValueError):
        Goal("x", max_actions=0)


async def test_heuristic_plans_on_actionable_events() -> None:
    planner = HeuristicPlanner()
    events = [Event.manual("go"), Event.tick()]
    plan = await planner.plan(Goal("do stuff"), events, recall=[])
    assert plan.actions
    assert all(a.tool == "note" for a in plan.actions)


async def test_heuristic_ignores_system_only() -> None:
    planner = HeuristicPlanner()
    events = [Event(kind=EventKind.SYSTEM, source="lifecycle")]
    plan = await planner.plan(Goal("do stuff"), events, recall=[])
    assert plan.is_noop()


async def test_heuristic_respects_max_actions() -> None:
    planner = HeuristicPlanner()
    events = [Event.manual(str(i)) for i in range(10)]
    plan = await planner.plan(Goal("do stuff", max_actions=2), events, recall=[])
    assert len(plan.actions) == 2
