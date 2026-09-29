"""Gmail connector: poll unread threads, send replies.

This is a deliberately small illustration. Real Gmail access needs OAuth; the
connector accepts an injected, already-authorized transport so the dots-facing
surface stays the same regardless of how credentials are obtained.
"""

from __future__ import annotations

from typing import Any, Protocol

from dots.connectors.base import ConnectorEvent


class GmailTransport(Protocol):
    """The minimal surface a Gmail transport must expose."""

    async def list_unread(self, *, max_results: int = 10) -> list[dict[str, Any]]: ...
    async def send(self, *, to: str, subject: str, body: str) -> dict[str, Any]: ...


class GmailConnector:
    name = "gmail"

    def __init__(self, transport: GmailTransport) -> None:
        self._transport = transport

    async def poll(self) -> list[ConnectorEvent]:
        messages = await self._transport.list_unread()
        return [
            ConnectorEvent(
                connector=self.name,
                kind="email",
                data={
                    "from": m.get("from", ""),
                    "subject": m.get("subject", ""),
                    "snippet": m.get("snippet", ""),
                },
            )
            for m in messages
        ]

    async def send(self, action: str, **kwargs: Any) -> dict[str, Any]:
        if action != "reply":
            raise ValueError(f"unsupported gmail action: {action!r}")
        return await self._transport.send(
            to=kwargs["to"], subject=kwargs["subject"], body=kwargs["body"]
        )
