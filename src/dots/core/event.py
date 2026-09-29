"""Events are the only way the outside world wakes a dot."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventKind(str, Enum):
    """What woke the dot."""

    TICK = "tick"          # scheduler fired
    WEBHOOK = "webhook"    # inbound HTTP
    CONNECTOR = "connector"  # a connector reported new data
    MANUAL = "manual"      # a human asked for a step
    SYSTEM = "system"      # lifecycle (started, paused, ...)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Event(BaseModel):
    """An immutable observation delivered to the runtime."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: EventKind
    source: str = "system"
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)

    model_config = {"frozen": True}

    @classmethod
    def tick(cls, source: str = "scheduler") -> Event:
        return cls(kind=EventKind.TICK, source=source)

    @classmethod
    def manual(cls, reason: str = "") -> Event:
        return cls(kind=EventKind.MANUAL, source="human", payload={"reason": reason})

    def summary(self) -> str:
        return f"[{self.kind.value}] from {self.source} at {self.created_at:%H:%M:%S}"
