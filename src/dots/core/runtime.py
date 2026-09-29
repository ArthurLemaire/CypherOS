"""The runtime: observe → plan → act → learn, once per step."""

from __future__ import annotations

from pydantic import BaseModel, Field

from dots.core.event import Event
from dots.core.eventlog import EventLog
from dots.core.state import State
from dots.memory.base import Memory
from dots.planner.goal import Goal
from dots.planner.planner import Action, Plan, Planner
from dots.tools.base import ToolRegistry, ToolResult


class StepResult(BaseModel):
    """The outcome of a single step."""

    step: int
    plan: Plan
    results: list[ToolResult] = Field(default_factory=list)
    learned: list[str] = Field(default_factory=list)
    paused_for_approval: str | None = None

    @property
    def acted(self) -> bool:
        return bool(self.results)


class Runtime:
    """Drives one dot forward. Holds no goal of its own — it's a pure engine."""

    def __init__(
        self,
        *,
        planner: Planner,
        memory: Memory,
        tools: ToolRegistry,
        log: EventLog | None = None,
    ) -> None:
        self._planner = planner
        self._memory = memory
        self._tools = tools
        self._log = log or EventLog()

    @property
    def log(self) -> EventLog:
        return self._log

    async def step(self, goal: Goal, state: State, events: list[Event]) -> StepResult:
        """Run exactly one observe→plan→act→learn cycle."""
        n = state.begin_step()
        for event in events:
            self._log.append("event", event.model_dump(mode="json"))

        recall = [r.text for r in await self._memory.recall(goal.objective, k=5)]
        plan = await self._planner.plan(goal, events, recall)
        self._log.append("plan", plan.model_dump(mode="json"))

        results: list[ToolResult] = []
        learned: list[str] = []
        for action in plan.actions:
            if action.needs_approval and state.awaiting_approval is None:
                state.awaiting_approval = action.label()
                self._log.append("approval_required", {"action": action.label()})
                return StepResult(
                    step=n, plan=plan, results=results, learned=learned,
                    paused_for_approval=action.label(),
                )
            result = await self._dispatch(action)
            results.append(result)
            for obs in result.observations:
                record = await self._memory.remember(obs, tags=[action.tool])
                learned.append(record.text)
            self._log.append("action", {"action": action.label(), "ok": result.ok})

        return StepResult(step=n, plan=plan, results=results, learned=learned)

    async def _dispatch(self, action: Action) -> ToolResult:
        if action.tool not in self._tools:
            return ToolResult.failure(f"no such tool: {action.tool}")
        tool = self._tools.get(action.tool)
        try:
            return await tool.run(**action.args)
        except Exception as exc:  # noqa: BLE001 - isolate tool failures
            return ToolResult.failure(f"{action.tool} raised: {exc}")

    async def replay(self, log: EventLog) -> list[Plan]:
        """Reconstruct the sequence of plans from a recorded log."""
        return [Plan.model_validate(e["data"]) for e in log.entries(type_="plan")]
