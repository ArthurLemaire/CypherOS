"""Slack connector: poll a channel's messages, post replies."""

from __future__ import annotations

import os
from typing import Any

from dots.connectors.base import ConnectorEvent

_API = "https://slack.com/api"


class SlackConnector:
    """Thin wrapper over Slack Web API using a bot token.

    Only the two methods a dot needs are implemented: reading new messages from
    a channel and posting a message. The HTTP client is injected for testability.
    """

    name = "slack"

    def __init__(
        self,
        *,
        channel: str,
        token: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._channel = channel
        self._token = token or os.environ.get("SLACK_BOT_TOKEN", "")
        self._client = client
        self._cursor: str | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import httpx

        self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def poll(self) -> list[ConnectorEvent]:
        client = await self._get_client()
        params = {"channel": self._channel, "limit": 20}
        if self._cursor:
            params["oldest"] = self._cursor
        resp = await client.get(
            f"{_API}/conversations.history", params=params, headers=self._headers()
        )
        body = resp.json()
        messages = body.get("messages", [])
        if messages:
            self._cursor = messages[0].get("ts")
        return [
            ConnectorEvent(
                connector=self.name,
                kind="message",
                data={"text": m.get("text", ""), "user": m.get("user", ""), "ts": m.get("ts")},
            )
            for m in messages
        ]

    async def send(self, action: str, **kwargs: Any) -> dict[str, Any]:
        if action != "post":
            raise ValueError(f"unsupported slack action: {action!r}")
        client = await self._get_client()
        resp = await client.post(
            f"{_API}/chat.postMessage",
            json={"channel": self._channel, "text": kwargs["text"]},
            headers=self._headers(),
        )
        return resp.json()
