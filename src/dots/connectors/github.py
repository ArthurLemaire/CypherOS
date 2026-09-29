"""GitHub connector: watch notifications / issues, comment back."""

from __future__ import annotations

import os
from typing import Any

from dots.connectors.base import ConnectorEvent

_API = "https://api.github.com"


class GitHubConnector:
    """Poll notifications for a repo and post issue comments.

    Uses a personal access token. The HTTP client is injectable so tests can run
    without hitting the network.
    """

    name = "github"

    def __init__(
        self,
        *,
        repo: str,
        token: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._repo = repo  # "owner/name"
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "dots-connector",
        }

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import httpx

        self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def poll(self) -> list[ConnectorEvent]:
        client = await self._get_client()
        resp = await client.get(
            f"{_API}/repos/{self._repo}/notifications", headers=self._headers()
        )
        items = resp.json() if resp.status_code == 200 else []
        return [
            ConnectorEvent(
                connector=self.name,
                kind=n.get("subject", {}).get("type", "unknown").lower(),
                data={
                    "title": n.get("subject", {}).get("title", ""),
                    "url": n.get("subject", {}).get("url", ""),
                    "reason": n.get("reason", ""),
                },
            )
            for n in items
        ]

    async def send(self, action: str, **kwargs: Any) -> dict[str, Any]:
        if action != "comment":
            raise ValueError(f"unsupported github action: {action!r}")
        client = await self._get_client()
        issue = kwargs["issue"]
        resp = await client.post(
            f"{_API}/repos/{self._repo}/issues/{issue}/comments",
            json={"body": kwargs["body"]},
            headers=self._headers(),
        )
        return resp.json()
