# Quickstart

## Install

```bash
pip install -e ".[dev]"
```

## Your first dot

```python
import asyncio
from dots import Dot, Event, Goal

async def main() -> None:
    dot = Dot(name="hello", goal=Goal("Say hello whenever woken"))
    await dot.step(Event.tick())
    print(dot.diary())

asyncio.run(main())
```

Run one of the bundled examples:

```bash
python examples/hello_dot.py
python examples/scheduler_dot.py
python examples/research_dot.py https://example.com
```

## From the CLI

```bash
dots version
dots demo "Watch the news and note what matters" --ticks 3
dots run --name market --goal "Summarize lithium news" --interval 30s --ticks 2
```

## Giving a dot tools

```python
from dots import Dot, Goal
from dots.tools import BrowserTool, ShellTool

dot = Dot(
    name="researcher",
    goal=Goal("Collect sources on solid-state batteries"),
    tools=[BrowserTool(), ShellTool(allow={"echo"})],
)
```

Every dot always has the built-in `note` tool. Anything you pass in `tools=`
is added on top.

## Persisting memory

```python
from dots import Dot, Goal
from dots.memory import SqliteMemory

dot = Dot(
    name="durable",
    goal=Goal("Remember across restarts"),
    memory=SqliteMemory(".dots/durable.db"),
)
```

## Next

- [Architecture](architecture.md)
- [Writing a connector](connectors.md)
