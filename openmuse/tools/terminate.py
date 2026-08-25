"""Control tools: finish the task / ask the human."""

from __future__ import annotations

from typing import Any

from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool
from openmuse.ui import UI


class Terminate(BaseTool):
    name: str = "terminate"
    description: str = (
        "Finish the current task. Call this when the request is fully handled (status=success) "
        "or when you cannot make progress (status=failure). Put your final answer / summary for "
        "the user in `summary`."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "failure"]},
            "summary": {"type": "string", "description": "Final message for the user."},
        },
        "required": ["status", "summary"],
    }
    risk: RiskLevel = RiskLevel.SAFE

    async def execute(self, status: str = "success", summary: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=summary or f"Task finished with status: {status}", stop=True)


class AskUser(BaseTool):
    name: str = "ask_user"
    description: str = (
        "Ask the user a clarifying question and wait for the answer. Use it when the request is "
        "ambiguous, when you need a decision or missing information (never guess credentials, "
        "addresses, amounts or dates)."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    ui: Any = None  # UI protocol instance

    async def execute(self, question: str = "", **_: Any) -> ToolResult:
        if self.ui is None:
            return ToolResult.fail("no UI available to ask the user")
        ui: UI = self.ui
        answer = await ui.ask_user(question)
        if answer is None or not str(answer).strip():
            return ToolResult(output="(the user did not answer)")
        return ToolResult(output=f"User answered: {answer}")


__all__ = ["AskUser", "Terminate"]
