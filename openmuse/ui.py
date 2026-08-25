"""User-interface abstraction.

The agent core never prints. It talks to a :class:`UI` implementation which the
CLI (rich console), tests (headless) or future web/chat front-ends provide.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from openmuse.schema import RiskLevel, ToolCall, ToolResult

ApprovalScope = Literal["once", "session", "always"]


class ApprovalRequest(BaseModel):
    tool: str
    args: dict[str, Any]
    summary: str
    risk: RiskLevel
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    egress_target: str | None = None


class ApprovalDecision(BaseModel):
    approved: bool
    scope: ApprovalScope = "once"
    reason: str = ""


class UI(Protocol):
    def on_text_delta(self, text: str) -> None: ...
    def on_assistant_message(self, content: str | None, reasoning: str | None) -> None: ...
    def on_tool_call(self, call: ToolCall, summary: str) -> None: ...
    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None: ...
    def on_sentinel(self, decision: str, summary: str, reasons: list[str]) -> None: ...
    def info(self, message: str) -> None: ...
    def warn(self, message: str) -> None: ...
    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision: ...
    async def ask_user(self, question: str) -> str: ...


class HeadlessUI:
    """No-interaction UI for tests, scripts and unattended runs."""

    def __init__(self, approve: bool = True, user_answer: str = "", verbose: bool = False):
        self.approve = approve
        self.user_answer = user_answer
        self.verbose = verbose
        self.events: list[tuple[str, Any]] = []

    def _log(self, kind: str, payload: Any) -> None:
        self.events.append((kind, payload))
        if self.verbose:
            print(f"[{kind}] {payload}")

    def on_text_delta(self, text: str) -> None:
        pass

    def on_assistant_message(self, content: str | None, reasoning: str | None) -> None:
        self._log("assistant", content)

    def on_tool_call(self, call: ToolCall, summary: str) -> None:
        self._log("tool_call", summary)

    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        self._log("tool_result", result.for_model(500))

    def on_sentinel(self, decision: str, summary: str, reasons: list[str]) -> None:
        self._log("sentinel", f"{decision}: {summary} {reasons}")

    def info(self, message: str) -> None:
        self._log("info", message)

    def warn(self, message: str) -> None:
        self._log("warn", message)

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self._log("approval", request.summary)
        return ApprovalDecision(approved=self.approve, reason="headless")

    async def ask_user(self, question: str) -> str:
        self._log("ask_user", question)
        return self.user_answer


__all__ = ["UI", "HeadlessUI", "ApprovalRequest", "ApprovalDecision", "ApprovalScope"]
