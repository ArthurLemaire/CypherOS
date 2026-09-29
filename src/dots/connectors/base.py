"""The Connector protocol: poll for inbound events, push outbound actions."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from dots.core.event import Event, EventKind


class ConnectorEvent(BaseModel):
    """A normalized inbound item from an external system."""

    connector: str
    kind: str
    data: dict[str, Any] = Field(default_factory=dict)

    def to_event(self) -> Event:
        return Event(
            kind=EventKind.CONNECTOR,
            source=self.connector,
            payload={"kind": self.kind, **self.data},
        )


@runtime_checkable
class Connector(Protocol):
    """Two-way integration. ``poll`` brings news in; ``send`` pushes actions out."""

    name: str

    async def poll(self) -> list[ConnectorEvent]:
        """Return new inbound events since the last poll (may be empty)."""
        ...

    async def send(self, action: str, **kwargs: Any) -> dict[str, Any]:
        """Perform an outbound action and return the provider's response."""
        ...
