"""Built-in tools every dot has available."""

from __future__ import annotations

from typing import Any

from dots.tools.base import ToolResult


class NoteTool:
    """Records a short observation. The default action a planner can always take.

    ``NoteTool`` is intentionally trivial: it turns an observation into a
    memory-worthy string. The runtime persists the returned observations.
    """

    name = "note"

    async def run(self, **kwargs: Any) -> ToolResult:
        text = str(kwargs.get("text", "")).strip()
        if not text:
            return ToolResult.failure("note requires 'text'")
        return ToolResult.success(output=text, observations=[text])
