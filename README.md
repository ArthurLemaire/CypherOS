<div align="center">

# ● dots

**An always-on, goal-driven agent runtime.**

Give a dot a goal. It plans, acts across your tools, remembers what it learned,
and keeps working in the background — with you in the loop only when it matters.

[![CI](https://github.com/MuseTeaParty/Tea-Party/actions/workflows/ci.yml/badge.svg)](https://github.com/MuseTeaParty/Tea-Party/actions/workflows/ci.yml)
[![CodeQL](https://github.com/MuseTeaParty/Tea-Party/actions/workflows/codeql.yml/badge.svg)](https://github.com/MuseTeaParty/Tea-Party/actions/workflows/codeql.yml)
[![PyPI](https://img.shields.io/badge/pypi-v0.4.0-3b82f6)](https://pypi.org/project/dots-runtime/)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Discord](https://img.shields.io/badge/chat-discord-5865f2)](https://discord.gg/example)
[![Ruff](https://img.shields.io/badge/lint-ruff-000000)](https://github.com/astral-sh/ruff)

</div>

> [!NOTE]
> **dots** is an independent, open-source project exploring the always-on agent
> paradigm. It is **not affiliated with, endorsed by, or connected to OpenAI**
> or any other company. Names of similar commercial products are coincidental.

---

## Why dots

Most "agents" are request/response: you ask, they answer, they forget. A **dot**
is different — it's a small, persistent process with a goal, a memory, and a set
of connectors. It wakes on events (a new email, a cron tick, a webhook), decides
whether the goal needs work, takes the smallest useful action, and goes back to
sleep. You get a diary of everything it did.

```
        goal ──▶ ┌───────────┐  observe   ┌────────────┐
                 │  Planner  │ ─────────▶ │  Runtime   │
                 └───────────┘            └────────────┘
                       ▲                        │ act
                 recall│                        ▼
                 ┌───────────┐            ┌────────────┐
                 │  Memory   │ ◀───────── │ Connectors │
                 └───────────┘   learn    └────────────┘
```

## Highlights

- **Goal-driven loop** — a dot pursues a declared goal, not a single prompt.
- **Event-native** — cron, webhooks, file watches, and connector events all wake a dot.
- **Pluggable memory** — in-memory, SQLite, or vector-backed recall behind one interface.
- **4,000+ style connectors** — a tiny `Connector` protocol; batteries for Slack, Gmail, GitHub.
- **Deterministic replay** — every run is an append-only event log you can replay and audit.
- **Human-in-the-loop** — `require_approval()` pauses a dot until you say go.
- **Typed & async** — `asyncio` end to end, fully type-hinted, `mypy --strict` clean.

## Install

```bash
pip install dots-runtime          # from PyPI
# or, from source:
git clone https://github.com/MuseTeaParty/Tea-Party.git
cd Tea-Party && pip install -e ".[dev]"
```

## 60-second quickstart

```python
import asyncio
from dots import Dot, Goal
from dots.tools import BrowserTool

async def main() -> None:
    dot = Dot(
        name="market-watch",
        goal=Goal("Summarize overnight news on lithium supply and post to #research"),
        tools=[BrowserTool()],
    )
    # run one deliberate step (plan → act → learn), then print the diary
    await dot.step()
    for entry in dot.diary():
        print(entry)

asyncio.run(main())
```

Run it as a long-lived process instead:

```bash
dots run examples/research_dot.py --interval 15m
dots diary market-watch --tail 20
dots pause market-watch
```

## How a step works

1. **Observe** — the runtime gathers pending events and current state.
2. **Plan** — the planner turns the goal + observations into a short action list.
3. **Act** — the runtime executes actions through tools/connectors (with approval gates).
4. **Learn** — results are written to memory and the append-only event log.

Each step is pure with respect to its inputs, so a recorded run replays identically.

## Documentation

| Guide | What's inside |
|-------|---------------|
| [Quickstart](docs/quickstart.md) | Your first dot, end to end |
| [Architecture](docs/architecture.md) | Runtime, planner, memory, event log |
| [Agents](docs/concepts/agents.md) | The `Dot` lifecycle and goals |
| [Memory](docs/concepts/memory.md) | Backends and recall strategies |
| [Planning](docs/concepts/planning.md) | How goals become actions |
| [Connectors](docs/connectors.md) | Writing your own integration |

## Project layout

```
src/dots/
├── core/         # agent, runtime, scheduler, event log, state
├── planner/      # goal decomposition → actions
├── memory/       # base protocol + in-memory / sqlite / vector backends
├── connectors/   # slack, gmail, github + the Connector protocol
├── tools/        # browser, shell + the Tool protocol
├── llm/          # model-provider abstraction
└── cli/          # `dots` command-line entrypoint
```

## Roadmap

- [x] Goal-driven step loop + event log
- [x] SQLite & vector memory backends
- [x] Slack / Gmail / GitHub connectors
- [ ] Distributed runtime (multiple dots, shared bus)
- [ ] Web dashboard for the diary
- [ ] Policy engine for autonomous approval

See [CHANGELOG.md](CHANGELOG.md) for release history.

## Contributing

PRs welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) and our
[Code of Conduct](CODE_OF_CONDUCT.md). Security issues: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © the dots contributors.
