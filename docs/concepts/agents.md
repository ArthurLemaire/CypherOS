# Agents

A **dot** is one agent: a goal plus the machinery to pursue it.

## Lifecycle

```
created ──▶ (running) ──▶ paused ──▶ running ──▶ ...
                │
                └── awaiting_approval ──▶ (approve) ──▶ running
```

- **created** — the dot registers its tools and writes a `system: created` log entry.
- **running** — each `step()` advances one observe→plan→act→learn cycle.
- **awaiting_approval** — an action marked `needs_approval` halts the step until
  `approve()` is called.
- **paused / resumed** — `pause()` short-circuits `step()`; `resume()` re-enables it.

## Goals vs prompts

A **prompt** is a one-shot instruction. A **goal** persists: the planner consults
it on every step to decide whether more work is warranted. A goal can carry
`success_criteria`, `constraints`, and a `max_actions` cap.

```python
Goal(
    "Keep the team's on-call runbook current",
    success_criteria=["runbook reflects the latest incident"],
    constraints=["never page anyone", "open a PR, don't push to main"],
    max_actions=3,
)
```

## The diary

`dot.diary()` renders the event log as human-readable lines — a running account
of what the dot did and why. It's the first thing to check when a dot misbehaves.

## Composing dots

Dots are cheap and isolated. Run several, each with its own goal and memory, and
coordinate them through connectors or a shared event bus (roadmap).
