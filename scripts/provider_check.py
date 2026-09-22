"""Run the agent through a few real tasks against the configured model and report.

    python scripts/provider_check.py                      # the model from your config
    python scripts/provider_check.py --model gemma3:4b --base-url http://localhost:11434/v1
    python scripts/provider_check.py --tool-mode prompt --only compute,artifact

Every scenario is a task a first-time user would give the agent: plain chat, a
calculation through python_execute, writing a file, remembering a preference and a
multi-step job. It prints one line per scenario (pass/fail, tool calls, seconds)
and exits non-zero if any failed. Results for the models we ran are in
docs/configuration.md ("Local models"); run it before adding a preset.

Everything happens in a temporary data dir and workspace; your own memory, goals
and vault are untouched. Sentinel runs in auto mode.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from openmuse.app import OpenMuseApp
from openmuse.config import Settings, load_settings
from openmuse.ui import HeadlessUI


@dataclass
class Scenario:
    name: str
    task: str
    check: Callable[[str, OpenMuseApp, HeadlessUI, Path], Awaitable[str | None]]
    """Returns None when the run passed, otherwise what went wrong."""


async def _plain(answer: str, muse: OpenMuseApp, ui: HeadlessUI, ws: Path) -> str | None:
    if "ready" not in answer.lower():
        return f"expected 'ready', got {answer!r}"
    if any(k == "tool_call" and "terminate" not in str(p) for k, p in ui.events):
        return "used a tool for a one-word answer"
    return None


async def _compute(answer: str, muse: OpenMuseApp, ui: HeadlessUI, ws: Path) -> str | None:
    if "75025" not in answer.replace(",", "").replace(" ", "").replace("\u202f", ""):
        return f"expected 75025 in {answer!r}"
    if not any(k == "tool_call" and "python_execute" in str(p) for k, p in ui.events):
        return "did not use python_execute"
    return None


async def _artifact(answer: str, muse: OpenMuseApp, ui: HeadlessUI, ws: Path) -> str | None:
    files = list(ws.glob("*.md"))
    if not files:
        return "no .md file in the workspace"
    text = files[0].read_text(encoding="utf-8", errors="replace")
    if text.count("\n") < 2:
        return f"{files[0].name} has fewer than three lines: {text[:120]!r}"
    return None


async def _memory(answer: str, muse: OpenMuseApp, ui: HeadlessUI, ws: Path) -> str | None:
    if muse.memory is None:
        return "memory disabled in this config"
    items = muse.memory.all()
    if not any("window" in m.content.lower() for m in items):
        return f"nothing about window seats remembered ({len(items)} memories)"
    return None


async def _multistep(answer: str, muse: OpenMuseApp, ui: HeadlessUI, ws: Path) -> str | None:
    missing = [n for n in ("a.txt", "b.txt", "c.txt") if not (ws / n).is_file()]
    if missing:
        return f"missing {missing}"
    if "6" not in answer:
        return f"expected the sum 6 in {answer!r}"
    return None


SCENARIOS = [
    Scenario("plain", "Reply with exactly one word: ready", _plain),
    Scenario(
        "compute",
        "Use python_execute to compute the 25th Fibonacci number (F(1)=F(2)=1) and tell me the "
        "number.",
        _compute,
    ),
    Scenario(
        "artifact",
        "Write a Markdown file named kyoto.md in the workspace with a three-day Kyoto itinerary, "
        "one line per day. Then tell me the file name.",
        _artifact,
    ),
    Scenario("memory", "Remember that I prefer window seats when flying.", _memory),
    Scenario(
        "multistep",
        "Create three files a.txt, b.txt and c.txt in the workspace containing the numbers 1, 2 "
        "and 3. Then read them back and tell me their sum.",
        _multistep,
    ),
]


def _settings(args: argparse.Namespace, root: Path) -> Settings:
    settings = load_settings(args.config)
    if args.model:
        settings.llm.model = args.model
    if args.base_url:
        settings.llm.base_url = args.base_url
    if args.api_key is not None:
        settings.llm.api_key = args.api_key
    if args.tool_mode:
        settings.llm.tool_mode = args.tool_mode
    if args.no_stream:
        settings.llm.stream = False
    settings.data_dir = root / "data"
    settings.agent.workspace = root / "ws"
    settings.sentinel.mode = "auto"
    settings.agent.max_steps = args.max_steps
    settings.mcp.servers = []
    settings.connectors.email.enabled = False
    settings.browser.enabled = False
    return settings


async def run_one(args: argparse.Namespace, sc: Scenario) -> tuple[bool, int, float, str, str]:
    with tempfile.TemporaryDirectory(prefix="openmuse-check-") as tmp:
        root = Path(tmp)
        settings = _settings(args, root)
        settings.agent.workspace.mkdir(parents=True)
        ui = HeadlessUI(verbose=args.verbose)
        started = time.monotonic()
        try:
            async with OpenMuseApp(settings, ui) as muse:
                answer = await muse.run(sc.task)
                problem = await sc.check(answer or "", muse, ui, settings.agent.workspace)
                mode = "native" if muse.llm.supports_native_tools else "prompt"
        except Exception as e:  # noqa: BLE001 - report, do not crash the matrix
            problem, mode = f"{type(e).__name__}: {str(e)[:160]}", "?"
        seconds = time.monotonic() - started
        calls = sum(1 for k, _ in ui.events if k == "tool_call")
        return problem is None, calls, seconds, mode, problem or ""


async def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", "-c", help="config file (default: the usual lookup)")
    p.add_argument("--model")
    p.add_argument("--base-url")
    p.add_argument("--api-key")
    p.add_argument("--tool-mode", choices=["auto", "native", "prompt"])
    p.add_argument("--no-stream", action="store_true")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--only", help="comma-separated scenario names")
    p.add_argument("--verbose", "-v", action="store_true", help="print every event")
    args = p.parse_args()

    wanted = set(args.only.split(",")) if args.only else {s.name for s in SCENARIOS}
    settings = _settings(args, Path(tempfile.gettempdir()))
    print(
        f"model {settings.llm.model} at {settings.llm.base_url or 'default'} "
        f"(provider {settings.llm.provider}, tool_mode {settings.llm.tool_mode}, "
        f"stream {settings.llm.stream})\n"
    )
    print(f"{'scenario':<10} {'result':<6} {'tools':>5} {'secs':>6}  mode    note")
    failed = 0
    for sc in SCENARIOS:
        if sc.name not in wanted:
            continue
        ok, calls, seconds, mode, note = await run_one(args, sc)
        failed += not ok
        print(
            f"{sc.name:<10} {'pass' if ok else 'FAIL':<6} {calls:>5} {seconds:>6.1f}  {mode:<7} {note}"
        )
    print(f"\n{len(wanted) - failed}/{len(wanted)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
