# Architecture

```
            ┌──────────────────────── Dot ───────────────────────┐
            │                                                     │
  events ─▶ │  State ──▶ Runtime ──▶ Planner ──▶ Action list      │
            │             │                          │            │
            │             ▼                          ▼            │
            │          EventLog                   Tools /         │
            │        (append-only)               Connectors       │
            │             ▲                          │            │
            │             └────────── Memory ◀───────┘            │
            └─────────────────────────────────────────────────────┘
```

## Components

### Dot (`dots.core.agent`)
The façade. Holds a `Goal`, a `State`, a `Memory`, a `ToolRegistry`, and a
`Runtime`. You mostly interact with a dot: `step()`, `pause()`, `diary()`.

### Runtime (`dots.core.runtime`)
A pure engine. Given `(goal, state, events)` it performs one observe→plan→act→learn
cycle and returns a `StepResult`. It holds no goal itself, so the same runtime can
drive any dot and be unit-tested in isolation.

### Planner (`dots.planner`)
Turns a goal plus observations plus recalled memory into a bounded `Plan`
(a list of `Action`s). The default `HeuristicPlanner` is deterministic and
dependency-free; production swaps in an LLM-backed planner via `dots.llm`.

### Memory (`dots.memory`)
A two-method protocol (`remember`, `recall`) with three backends:
in-memory (Jaccard overlap), SQLite (FTS5/LIKE), and vector (cosine).

### Tools & Connectors (`dots.tools`, `dots.connectors`)
Tools are local verbs (`note`, `browser`, `shell`). Connectors are two-way
bridges to external systems (`poll` inbound, `send` outbound).

### Event log (`dots.core.eventlog`)
Every event, plan, and action is appended as JSONL. Because a step is a pure
function of its inputs, `Runtime.replay(log)` reconstructs the plan sequence
exactly — the backbone of auditing and debugging.

## Determinism & replay

A step reads only: the goal, the current state, the incoming events, and recalled
memory. Given the same inputs it produces the same plan. This is why the default
planner avoids wall-clock and randomness, and why the event log is authoritative.

## Concurrency

Everything is `asyncio`. Tools must not block the event loop — use async I/O or
offload CPU-bound work to an executor. The `Scheduler` uses absolute monotonic
wake targets to avoid drift when a step overruns its interval.
