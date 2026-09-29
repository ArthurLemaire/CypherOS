"""The mutable working state a dot carries between steps."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class State(BaseModel):
    """Small, serializable scratchpad for a running dot.

    This is intentionally tiny — long-lived knowledge belongs in ``Memory``.
    State is the equivalent of a few local variables that survive between steps.
    """

    step: int = 0
    paused: bool = False
    awaiting_approval: str | None = None
    scratch: dict[str, Any] = Field(default_factory=dict)
    last_step_at: datetime | None = None

    def begin_step(self) -> int:
        self.step += 1
        self.last_step_at = datetime.now(timezone.utc)
        return self.step

    def set(self, key: str, value: Any) -> None:
        self.scratch[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.scratch.get(key, default)
