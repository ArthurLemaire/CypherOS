"""Rich-based terminal UI."""

from __future__ import annotations

import asyncio
import json

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from openmuse.schema import ToolCall, ToolResult
from openmuse.ui import ApprovalDecision, ApprovalRequest

RISK_STYLE = {"safe": "green", "moderate": "yellow", "sensitive": "bold red"}


class ConsoleUI:
    def __init__(
        self,
        console: Console | None = None,
        show_thinking: bool = False,
        quiet: bool = False,
        name: str = "OpenMuse",
    ):
        self.console = console or Console()
        self.show_thinking = show_thinking
        self.quiet = quiet
        self.name = name
        self._streaming = False
        self._streamed_chars = 0

    # ------------------------------------------------------------------ output
    def on_text_delta(self, text: str) -> None:
        if not text:
            return
        if not self._streaming:
            self.console.print(Text(f"{self.name} › ", style="bold blue"), end="")
            self._streaming = True
        self.console.print(text, end="", markup=False, highlight=False, soft_wrap=True)
        self._streamed_chars += len(text)

    def _end_stream(self) -> None:
        if self._streaming:
            self.console.print()
            self._streaming = False
            self._streamed_chars = 0

    def on_assistant_message(self, content: str | None, reasoning: str | None) -> None:
        streamed = self._streaming
        self._end_stream()
        if reasoning and self.show_thinking:
            self.console.print(
                Panel(
                    Text(reasoning.strip()[:4000], style="dim"),
                    title="thinking",
                    border_style="dim",
                )
            )
        if content and not streamed:
            self.console.print(Text(f"{self.name} › ", style="bold blue"), end="")
            self.console.print(Markdown(content))

    def on_tool_call(self, call: ToolCall, summary: str) -> None:
        self._end_stream()
        if self.quiet:
            return
        self.console.print(Text(f"  ⚙ {summary}", style="cyan"), soft_wrap=True)

    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        if self.quiet:
            return
        preview = (result.error or result.output or "").strip().replace("\n", " ⏎ ")
        if len(preview) > 220:
            preview = preview[:220] + "…"
        style = "red" if result.error else "dim"
        self.console.print(Text(f"    ↳ {preview}", style=style), soft_wrap=True)
        if result.system:
            self.console.print(Text(f"    ℹ {result.system}", style="dim italic"))

    def on_sentinel(self, decision: str, summary: str, reasons: list[str]) -> None:
        if decision == "deny":
            self.console.print(Text(f"  ⛔ Sentinel blocked: {summary}", style="bold red"))
            for r in reasons:
                self.console.print(Text(f"     · {r}", style="red"))

    def info(self, message: str) -> None:
        self.console.print(Text(message, style="dim"))

    def warn(self, message: str) -> None:
        self.console.print(Text(message, style="yellow"))

    # ------------------------------------------------------------------ input
    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self._end_stream()
        body = Text()
        body.append(f"{request.summary}\n", style="bold")
        if request.purpose:
            body.append(f"for: {request.purpose}\n", style="italic dim")
        body.append(f"risk: {request.risk.value}", style=RISK_STYLE.get(request.risk.value, ""))
        if request.egress_target:
            body.append(f"   → {request.egress_target}")
        body.append("\n")
        for r in request.reasons:
            body.append(f"· {r}\n", style="yellow")
        for w in request.warnings:
            body.append(f"⚠ {w}\n", style="bold red")
        args = json.dumps(request.args, ensure_ascii=False, indent=2, default=str)
        if len(args) > 1500:
            args = args[:1500] + "\n…"
        body.append(args, style="dim")
        self.console.print(
            Panel(body, title="🛡  Sentinel approval required", border_style="yellow")
        )
        what = request.grant_key
        labels = {
            "once": "[y]es, once",
            "task": "this [t]ask",
            "session": "this [s]ession",
            "24h": "24 hours ([d])",
            "always": f"[a]lways for {what}",
        }
        keys = {"once": "y", "task": "t", "session": "s", "24h": "d", "always": "a"}
        offered = [s for s in request.grant_options if s in labels]
        prompt = "[bold]Allow?[/bold] " + " / ".join(labels[s] for s in offered) + " / [n]o"
        answer = await asyncio.to_thread(
            Prompt.ask,
            prompt,
            choices=[keys[s] for s in offered] + ["n"],
            default="n",
            console=self.console,
        )
        for scope, key in keys.items():
            if answer == key and scope in offered:
                return ApprovalDecision(approved=True, scope=scope)  # type: ignore[arg-type]
        reason = await asyncio.to_thread(
            Prompt.ask, "Reason for the agent (optional)", default="", console=self.console
        )
        return ApprovalDecision(approved=False, reason=reason)

    async def ask_user(self, question: str) -> str:
        self._end_stream()
        self.console.print(
            Panel(Markdown(question), title=f"{self.name} asks", border_style="blue")
        )
        return await asyncio.to_thread(
            Prompt.ask, "[bold green]You[/bold green]", console=self.console
        )


__all__ = ["ConsoleUI"]
