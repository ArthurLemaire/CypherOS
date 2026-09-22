"""Chat timeline + real-time event bus for the OpenMuse app.

The mobile app is a messaging surface (think WhatsApp): everything the agent does
shows up as *events* in a thread's timeline — user bubbles, assistant bubbles,
tool activity chips, approval cards, questions, artifacts and notices. Events
are persisted per thread as JSON so the conversation survives restarts, and
broadcast live to every connected WebSocket client.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openmuse.logger import logger

MAIN_THREAD = "main"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id(prefix: str = "e") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Timeline:
    """Ordered list of events for one thread, persisted as a JSON file."""

    def __init__(self, thread_id: str, path: Path, max_events: int = 2000):
        self.thread_id = thread_id
        self.path = path
        self.max_events = max_events
        self.events: list[dict[str, Any]] = []
        self._index: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("could not load timeline {}: {}", self.path, exc)
            return
        for ev in data.get("events", []):
            if isinstance(ev, dict) and "id" in ev:
                self.events.append(ev)
                self._index[ev["id"]] = ev

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {"thread": self.thread_id, "events": self.events[-self.max_events :]},
                    ensure_ascii=False,
                ),
                "utf-8",
            )
            tmp.replace(self.path)
        except OSError as exc:  # pragma: no cover
            logger.warning("could not save timeline {}: {}", self.path, exc)

    def add(self, event: dict[str, Any]) -> dict[str, Any]:
        event.setdefault("id", new_id())
        event.setdefault("ts", now_iso())
        event["thread"] = self.thread_id
        self.events.append(event)
        self._index[event["id"]] = event
        if len(self.events) > self.max_events:
            for old in self.events[: len(self.events) - self.max_events]:
                self._index.pop(old["id"], None)
            self.events = self.events[-self.max_events :]
        self.save()
        return event

    def update(self, event_id: str, **fields: Any) -> dict[str, Any] | None:
        ev = self._index.get(event_id)
        if ev is None:
            return None
        ev.update(fields)
        ev["updated_ts"] = now_iso()
        self.save()
        return ev

    def get(self, event_id: str) -> dict[str, Any] | None:
        return self._index.get(event_id)

    def remove(self, event_id: str) -> None:
        ev = self._index.pop(event_id, None)
        if ev is not None:
            self.events = [e for e in self.events if e["id"] != event_id]
            self.save()

    def tail(self, limit: int = 200, before: str | None = None) -> list[dict[str, Any]]:
        events = self.events
        if before:
            idx = next((i for i, e in enumerate(events) if e["id"] == before), None)
            if idx is not None:
                events = events[:idx]
        return list(events[-limit:])

    def clear(self) -> None:
        self.events.clear()
        self._index.clear()
        self.save()


class EventBus:
    """Fan-out of JSON events to connected WebSocket clients (asyncio queues)."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    @property
    def connections(self) -> int:
        return len(self._subscribers)

    def publish(self, message: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:  # slow client: drop it
                self._subscribers.discard(q)


__all__ = ["MAIN_THREAD", "EventBus", "Timeline", "new_id", "now_iso"]
