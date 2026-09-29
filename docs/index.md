# dots documentation

**dots** is an always-on, goal-driven agent runtime. A *dot* is a small,
persistent process that pursues a goal by reacting to events, acting through
tools and connectors, and remembering what it learns.

> **Independent project.** dots is not affiliated with or endorsed by OpenAI or
> any other company.

## Start here

1. [Quickstart](quickstart.md) — build and run your first dot.
2. [Architecture](architecture.md) — how the pieces fit together.
3. Concepts:
   - [Agents](concepts/agents.md)
   - [Memory](concepts/memory.md)
   - [Planning](concepts/planning.md)
4. [Connectors](connectors.md) — integrate an external system.

## Mental model

A dot runs a loop, one **step** at a time:

```
observe  →  plan  →  act  →  learn
  ▲                            │
  └────────────────────────────┘
```

- **observe** — collect pending events + current state
- **plan** — the planner turns goal + observations into a short action list
- **act** — the runtime dispatches actions to tools/connectors (with approval gates)
- **learn** — results become memory and an append-only log entry

Because a step is deterministic given its inputs, a recorded run replays exactly.
