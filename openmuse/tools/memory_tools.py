"""Memory tools: remember / recall / forget."""

from __future__ import annotations

from typing import Any

from openmuse.memory import MemoryStore
from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool


class Remember(BaseTool):
    name: str = "remember"
    description: str = (
        "Save a durable fact about the user or their preferences for future sessions "
        "(e.g. 'prefers window seats', 'partner is vegetarian', 'works at Acme, timezone UTC+8'). "
        "Keep it short and factual. Never store passwords or payment details here."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "category": {
                "type": "string",
                "description": "profile | preference | contact | project | routine | other",
            },
        },
        "required": ["content"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    store: MemoryStore

    async def execute(self, content: str = "", category: str = "general", **_: Any) -> ToolResult:
        try:
            item = self.store.add(content, category=category or "general")
        except ValueError as exc:
            return ToolResult.fail(str(exc))
        return ToolResult(output=f"Remembered {item.id}: {item.content}")


class Recall(BaseTool):
    name: str = "recall"
    description: str = "Search long-term memory for facts about the user relevant to `query`."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = True
    store: MemoryStore

    async def execute(self, query: str = "", limit: int = 10, **_: Any) -> ToolResult:
        items = self.store.search(query, limit=max(1, min(int(limit or 10), 50)))
        if not items:
            return ToolResult(output="No matching memories.")
        return ToolResult(output="\n".join(i.render() for i in items))


class Forget(BaseTool):
    name: str = "forget"
    description: str = (
        "Delete memories. Provide `memory_id` (e.g. m_1a2b3c4d) to delete one, or `query` to delete "
        "every memory containing that text. Use when the user asks you to forget something."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"memory_id": {"type": "string"}, "query": {"type": "string"}},
    }
    risk: RiskLevel = RiskLevel.MODERATE
    store: MemoryStore

    async def execute(
        self, memory_id: str | None = None, query: str | None = None, **_: Any
    ) -> ToolResult:
        if memory_id:
            ok = self.store.forget(memory_id)
            return ToolResult(
                output=f"Forgot {memory_id}." if ok else f"No memory with id {memory_id}."
            )
        if query:
            n = self.store.forget_matching(query)
            return ToolResult(
                output=f"Forgot {n} memor{'y' if n == 1 else 'ies'} matching '{query}'."
            )
        return ToolResult.fail("provide memory_id or query")


__all__ = ["Forget", "Recall", "Remember"]
