# Planning

A **planner** turns `(goal, events, recall)` into a bounded `Plan`:

```python
class Planner(Protocol):
    async def plan(self, goal: Goal, events: list[Event], recall: list[str]) -> Plan: ...
```

A `Plan` is a list of `Action`s plus reasoning and a `goal_satisfied` flag.

## The default: HeuristicPlanner

Deterministic and dependency-free. Its policy:

1. Drop non-actionable events (system lifecycle; optionally ticks).
2. For each remaining event, emit a `note` action recording it.
3. Cap the list at `goal.max_actions`.

This makes the whole stack runnable and testable with no model and no network.

## LLM-backed planning

Swap in a planner that calls a model through `dots.llm`:

```python
from dots.llm import Message
from dots.planner.planner import Action, Plan

class LLMPlanner:
    def __init__(self, llm):
        self._llm = llm

    async def plan(self, goal, events, recall) -> Plan:
        prompt = [
            Message.system("You plan the next actions for an autonomous agent."),
            Message.user(render(goal, events, recall)),
        ]
        completion = await self._llm.complete(prompt)
        return parse_actions(completion.text)   # your parser → list[Action]
```

## Design rules

- **Bounded.** Always respect `goal.max_actions`; unbounded plans are a footgun.
- **Deterministic where possible.** Avoid wall-clock/randomness so runs replay.
- **Smallest useful step.** Prefer one good action now over a big speculative batch.
- **Approval-aware.** Mark risky actions `needs_approval=True`; the runtime gates them.
