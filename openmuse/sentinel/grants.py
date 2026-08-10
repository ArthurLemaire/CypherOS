"""Approval grants: capabilities the user handed out, bound to a tool and a target.

Muse treats an approval as a strict capability, not a conversational "yes": it is bound to
the connector or destination it was given for, and it has a lifetime. Same here. A grant
key looks like ``web_fetch:example.com``, ``send_email:alice@example.com`` or ``shell:git``;
a bare tool name means the whole tool.

Scopes:

* ``once``     – this one call; nothing is stored
* ``task``     – until the current agent run finishes
* ``session``  – until the process exits
* ``24h``      – for a day (persisted)
* ``always``   – until revoked (persisted)
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from openmuse.logger import logger

GrantScope = Literal["once", "task", "session", "24h", "always"]
SCOPES: tuple[str, ...] = ("once", "task", "session", "24h", "always")
PERSISTED_SCOPES = ("24h", "always")
DAY = 24 * 3600.0


@dataclass
class Grant:
    key: str
    tool: str
    target: str | None
    scope: str
    granted_at: float
    expires_at: float | None = None
    task_id: str | None = None

    def active(self, now: float, task_id: str | None) -> bool:
        if self.scope == "task":
            return self.task_id is not None and self.task_id == task_id
        if self.expires_at is not None and now >= self.expires_at:
            return False
        return True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["granted_at"] = _iso(self.granted_at)
        d["expires_at"] = _iso(self.expires_at) if self.expires_at else None
        return d


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def grant_key(tool: str, target: str | None) -> str:
    return f"{tool}:{target}" if target else tool


class GrantStore:
    """In-memory grants plus a JSON file for the ones that outlive the process."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self._grants: list[Grant] = []
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        now = time.time()
        if isinstance(data, list):
            # v1 file: a list of tool names that were "always allowed"
            self._grants = [
                Grant(key=t, tool=t, target=None, scope="always", granted_at=now) for t in data
            ]
            return
        for item in data.get("grants", []):
            try:
                g = Grant(
                    key=str(item["key"]),
                    tool=str(item.get("tool") or str(item["key"]).split(":", 1)[0]),
                    target=item.get("target"),
                    scope=str(item.get("scope", "always")),
                    granted_at=float(item.get("granted_at") or now),
                    expires_at=(float(item["expires_at"]) if item.get("expires_at") else None),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if g.scope in PERSISTED_SCOPES and g.active(now, None):
                self._grants.append(g)

    def _save(self) -> None:
        if not self.path:
            return
        keep = [
            {
                "key": g.key,
                "tool": g.tool,
                "target": g.target,
                "scope": g.scope,
                "granted_at": g.granted_at,
                "expires_at": g.expires_at,
            }
            for g in self._grants
            if g.scope in PERSISTED_SCOPES
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 2, "grants": keep}, indent=1), "utf-8")

    # ------------------------------------------------------------------ queries
    def _exact(self, key: str, now: float, task_id: str | None) -> Grant | None:
        for g in self._grants:
            if g.key == key and g.active(now, task_id):
                return g
        return None

    def match(self, key: str, task_id: str | None = None) -> Grant | None:
        """The grant covering ``key``, if any.

        A grant for the whole tool covers every target. A call with several targets
        (``shell:git,head`` – a pipeline; ``send_email:a@x,b@y`` – two recipients) is covered
        only when every single target is.
        """
        now = time.time()
        found = self._exact(key, now, task_id)
        if found is not None:
            return found
        tool, _, target = key.partition(":")
        if target:
            toolwide = self._exact(tool, now, task_id)
            if toolwide is not None:
                return toolwide
            parts = [p for p in target.split(",") if p]
            if len(parts) > 1:
                grants = [self._exact(grant_key(tool, p), now, task_id) for p in parts]
                if all(grants):
                    return grants[0]
        return None

    def active(self, task_id: str | None = None) -> list[Grant]:
        now = time.time()
        return [g for g in self._grants if g.active(now, task_id) or g.scope == "task"]

    # ------------------------------------------------------------------ mutations
    def add(
        self, tool: str, target: str | None, scope: str, task_id: str | None = None
    ) -> Grant | None:
        """Store a grant. Several targets (``git,head``) become one grant each, so
        approving a pipeline also covers its programs on their own — and vice versa."""
        if scope not in SCOPES or scope == "once":
            return None
        if scope == "task" and not task_id:
            logger.debug("task-scoped grant requested outside a task; treating as once")
            return None
        now = time.time()
        targets: list[str | None] = [p for p in target.split(",") if p] if target else [None]
        first: Grant | None = None
        for t in targets:
            grant = Grant(
                key=grant_key(tool, t),
                tool=tool,
                target=t,
                scope=scope,
                granted_at=now,
                expires_at=now + DAY if scope == "24h" else None,
                task_id=task_id if scope == "task" else None,
            )
            # one grant per key: the new decision replaces the old one
            self._grants = [g for g in self._grants if g.key != grant.key]
            self._grants.append(grant)
            first = first or grant
        if scope in PERSISTED_SCOPES:
            self._save()
        return first

    def revoke(self, key: str) -> bool:
        before = len(self._grants)
        self._grants = [g for g in self._grants if g.key != key]
        if len(self._grants) != before:
            self._save()
            return True
        return False

    def end_task(self, task_id: str) -> None:
        self._grants = [g for g in self._grants if not (g.scope == "task" and g.task_id == task_id)]

    def clear(self) -> None:
        self._grants.clear()
        self._save()

    def purge_expired(self) -> None:
        now = time.time()
        self._grants = [
            g
            for g in self._grants
            if g.scope == "task" or g.expires_at is None or now < g.expires_at
        ]


__all__ = ["DAY", "PERSISTED_SCOPES", "SCOPES", "Grant", "GrantScope", "GrantStore", "grant_key"]
