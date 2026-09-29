"""`dots` CLI — run a dot, tail its diary, or fire a quick demo."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dots.core.agent import Dot
from dots.core.duration import format_duration, parse_duration
from dots.core.scheduler import Scheduler
from dots.planner.goal import Goal
from dots.version import __version__

app = typer.Typer(help="dots — an always-on, goal-driven agent runtime.", no_args_is_help=True)
console = Console()


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"[bold]dots[/bold] {__version__}")


@app.command()
def demo(
    goal: str = typer.Argument("Keep an eye on the news and jot down what matters"),
    ticks: int = typer.Option(3, "--ticks", "-n", help="How many steps to run."),
) -> None:
    """Run a self-contained demo dot for a few ticks and print its diary."""

    async def _run() -> None:
        dot = Dot(name="demo", goal=Goal(goal))
        sched = Scheduler(dot, interval=0.01)
        count = 0
        async for _ in sched.run(max_ticks=ticks):
            count += 1
        _print_diary(dot.name, dot.diary())
        console.print(f"[dim]ran {count} tick(s)[/dim]")

    asyncio.run(_run())


@app.command()
def run(
    interval: str = typer.Option("15m", "--interval", "-i", help="e.g. 30s, 15m, 1h"),
    ticks: int = typer.Option(1, "--ticks", "-n", help="Cap ticks (0 = forever)."),
    name: str = typer.Option("dot", "--name"),
    goal: str = typer.Option(..., "--goal", "-g"),
) -> None:
    """Run a dot on an interval (bounded by --ticks unless 0)."""
    seconds = parse_duration(interval)
    console.print(
        Panel.fit(
            f"[bold]{name}[/bold]\n{goal}\nevery [cyan]{format_duration(seconds)}[/cyan]",
            title="starting dot",
        )
    )

    async def _run() -> None:
        dot = Dot(name=name, goal=Goal(goal))
        sched = Scheduler(dot, interval=max(seconds, 0.01))
        cap = None if ticks == 0 else ticks
        async for result in sched.run(max_ticks=cap):
            console.print(f"step {result.step}: {len(result.results)} action(s)")
        _print_diary(dot.name, dot.diary())

    asyncio.run(_run())


@app.command()
def diary(
    log: Path = typer.Argument(..., help="Path to a dot's JSONL event log."),
    tail: int = typer.Option(20, "--tail", "-t"),
) -> None:
    """Render a dot's diary from its event log."""
    if not log.exists():
        console.print(f"[red]no such log:[/red] {log}")
        raise typer.Exit(1)

    lines: list[str] = []
    for raw in log.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        entry = json.loads(raw)
        if entry["type"] == "action":
            mark = "[green]✓[/green]" if entry["data"].get("ok") else "[red]✗[/red]"
            lines.append(f"{mark} {entry['data']['action']}")
    _print_lines(f"diary · {log.name}", lines[-tail:])


def _print_diary(name: str, lines: list[str]) -> None:
    _print_lines(f"diary · {name}", lines)


def _print_lines(title: str, lines: list[str]) -> None:
    table = Table(title=title, show_header=False, expand=True)
    for line in lines or ["(empty)"]:
        table.add_row(line)
    console.print(table)


if __name__ == "__main__":
    app()
