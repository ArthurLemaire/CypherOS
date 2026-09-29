"""Planners turn (goal, observations, recall) into a bounded list of actions."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from dots.core.event import Event
from dots.planner.goal import Goal


class Action(BaseModel):
    """A single unit of work the runtime will dispatch to a tool/connector."""

    tool: str
    args: dict[str, object] = Field(default_factory=dict)
    rationale: str = ""
    needs_approval: bool = False

    def label(self) -> str:
        arg_preview = ", ".join(f"{k}={v!r}" for k, v in list(self.args.items())[:2])
        return f"{self.tool}({arg_preview})"


class Plan(BaseModel):
    """The planner's output for one step."""

    actions: list[Action] = Field(default_factory=list)
    reasoning: str = ""
    goal_satisfied: bool = False

    def is_noop(self) -> bool:
        return not self.actions and not self.goal_satisfied


@runtime_checkable
class Planner(Protocol):
    """Anything that can produce a :class:`Plan` for a step."""

    async def plan(
        self, goal: Goal, events: list[Event], recall: list[str]
    ) -> Plan: ...


class HeuristicPlanner:
    """A deterministic, dependency-free planner used as the default and in tests.

    Real deployments swap this for an LLM-backed planner (see ``dots.llm``).
    This one implements a simple but honest policy:

    * If there are no fresh events and we have acted before, do nothing.
    * Otherwise emit a single ``note`` action recording the observation, capped
      by ``goal.max_actions``.
    """

    def __init__(self, *, act_on_tick: bool = True) -> None:
        self._act_on_tick = act_on_tick

    async def plan(self, goal: Goal, events: list[Event], recall: list[str]) -> Plan:
        actionable = [e for e in events if self._is_actionable(e)]
        if not actionable:
            return Plan(reasoning="no actionable events", goal_satisfied=False)

        actions = [
            Action(
                tool="note",
                args={"text": e.summary()},
                rationale=f"record {e.kind.value} toward goal",
            )
            for e in actionable[: goal.max_actions]
        ]
        return Plan(
            actions=actions,
            reasoning=f"{len(actions)} observation(s) worth recording",
        )

    def _is_actionable(self, event: Event) -> bool:
        from dots.core.event import EventKind

        if event.kind is EventKind.TICK:
            return self._act_on_tick
        return event.kind is not EventKind.SYSTEM
