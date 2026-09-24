"""Call tokens: one per shell command, for as long as it runs."""

from __future__ import annotations

import contextvars
import secrets
import time
from dataclasses import dataclass, field

BRIDGE_URL_ENV = "NANOMUSE_BRIDGE"
BRIDGE_TOKEN_ENV = "NANOMUSE_BRIDGE_TOKEN"  # noqa: S105 — the variable's name, not a secret

#: A command may keep calling for this long after its own timeout, so a request that was
#: in flight when the command finished is still answered.
GRACE_SECONDS = 30.0


@dataclass
class BridgeGrant:
    token: str
    call_id: str  # the shell / python_execute call this belongs to
    tool: str  # "shell" or "python_execute"
    expires_at: float
    #: The agent run's context (its chat, its task, its purpose), copied when the command
    #: started: a request from the command runs in it, so approvals land in that chat.
    context: contextvars.Context = field(default_factory=contextvars.copy_context)
    calls: int = 0

    def expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.monotonic()) > self.expires_at


class BridgeTokens:
    """Mint, look up and revoke call tokens. In memory: a token dies with the server."""

    def __init__(self) -> None:
        self._grants: dict[str, BridgeGrant] = {}

    def mint(self, call_id: str, tool: str, ttl: float) -> BridgeGrant:
        self.sweep()
        grant = BridgeGrant(
            token=secrets.token_urlsafe(24),
            call_id=call_id,
            tool=tool,
            expires_at=time.monotonic() + max(1.0, ttl) + GRACE_SECONDS,
        )
        self._grants[grant.token] = grant
        return grant

    def get(self, token: str | None) -> BridgeGrant | None:
        if not token:
            return None
        grant = self._grants.get(token)
        if grant is None:
            return None
        if grant.expired():
            self._grants.pop(token, None)
            return None
        return grant

    def revoke(self, token: str) -> None:
        self._grants.pop(token, None)

    def sweep(self) -> None:
        now = time.monotonic()
        for token in [t for t, g in self._grants.items() if g.expired(now)]:
            self._grants.pop(token, None)

    def __len__(self) -> int:
        return len(self._grants)


__all__ = ["BRIDGE_TOKEN_ENV", "BRIDGE_URL_ENV", "GRACE_SECONDS", "BridgeGrant", "BridgeTokens"]
