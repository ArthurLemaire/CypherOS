# Contributing to dots

Thanks for helping build dots. This guide keeps contributions smooth.

## Development setup

```bash
git clone https://github.com/MuseTeaParty/Tea-Party.git
cd Tea-Party
python -m venv .venv && source .venv/bin/activate
make install        # editable install + pre-commit hooks
```

## The loop

```bash
make fmt     # format + autofix
make lint    # ruff
make type    # mypy --strict
make test    # pytest
```

All four must pass before you open a PR. CI runs the same commands.

## Conventions

- **Async first.** New I/O paths use `asyncio`; never block the event loop.
- **Typed.** Public functions are fully annotated and pass `mypy --strict`.
- **Small steps.** A `Dot` step should do the *smallest useful* unit of work.
- **Deterministic.** Given the same events + state, a step must produce the same actions.
- **Tests.** New behavior ships with tests. Aim to keep coverage above 90%.

## Commit messages

Use imperative mood and a short scope, e.g.:

```
memory: add TTL eviction to VectorMemory
planner: cap action list to max_actions
```

## Adding a connector

See [docs/connectors.md](docs/connectors.md). Implement the `Connector` protocol,
add a test with a fake transport, and document required env vars.

## Reporting bugs

Open an issue with a minimal repro. If it's a security issue, follow
[SECURITY.md](SECURITY.md) instead of filing publicly.
