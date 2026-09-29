"""The Dot: a goal, a memory, a set of tools, and a runtime to drive them."""

from __future__ import annotations

from dots.core.event import Event
from dots.core.eventlog import EventLog
from dots.core.runtime import Runtime, StepResult
from dots.core.state import State
from dots.memory.base import Memory
from dots.memory.inmemory import InMemoryMemory
from dots.planner.goal import Goal
from dots.planner.planner import HeuristicPlanner, Planner
from dots.tools.base import Tool, ToolRegistry
from dots.tools.builtin import NoteTool


class Dot:
    """A single always-on agent.

    A dot is cheap: it's a goal plus the machinery to pursue it. Construct one,
    feed it events (or let a scheduler tick it), and read its ``diary``.
    """

    def __init__(
        self,
        *,
        name: str,
        goal: Goal | str,
        tools: list[Tool] | None = None,
        memory: Memory | None = None,
        planner: Planner | None = None,
        log_path: str | None = None,
    ) -> None:
        self.name = name
        self.goal = goal if isinstance(goal, Goal) else Goal(goal)
        self.state = State()
        self._memory = memory or InMemoryMemory()

        registry = ToolRegistry([NoteTool()])
        for tool in tools or []:
            registry.register(tool)

        self._runtime = Runtime(
            planner=planner or HeuristicPlanner(),
            memory=self._memory,
            tools=registry,
            log=EventLog(log_path),
        )
        self._runtime.log.append("system", {"event": "created", "dot": name})

    async def step(self, *events: Event) -> StepResult:
        """Advance the dot by one step.

        With no events, a synthetic manual event is used so an ad-hoc
        ``await dot.step()`` still does something useful.
        """
        if self.state.paused:
            return StepResult(step=self.state.step, plan=_empty_plan())
        incoming = list(events) or [Event.manual("adhoc step")]
        return await self._runtime.step(self.goal, self.state, incoming)

    async def approve(self) -> StepResult:
        """Clear a pending approval gate and continue."""
        self.state.awaiting_approval = None
        return await self.step(Event.manual("approved"))

    def pause(self) -> None:
        self.state.paused = True
        self._runtime.log.append("system", {"event": "paused", "dot": self.name})

    def resume(self) -> None:
        self.state.paused = False
        self._runtime.log.append("system", {"event": "resumed", "dot": self.name})

    def diary(self) -> list[str]:
        """A human-readable trace of what the dot did, newest last."""
        lines: list[str] = []
        for entry in self._runtime.log.entries():
            data = entry["data"]
            if entry["type"] == "action":
                mark = "✓" if data.get("ok") else "✗"
                lines.append(f"{mark} {data['action']}")
            elif entry["type"] == "approval_required":
                lines.append(f"⏸ awaiting approval: {data['action']}")
            elif entry["type"] == "system":
                lines.append(f"· {data['event']}")
        return lines

    @property
    def memory(self) -> Memory:
        return self._memory

    @property
    def runtime(self) -> Runtime:
        return self._runtime


def _empty_plan():  # small local import-free helper
    from dots.planner.planner import Plan

    return Plan(reasoning="dot is paused")
