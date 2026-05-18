"""Triggers: standing instructions that start work when something happens.

A reminder fires at a time; a trigger fires on an event in the world — a mail that arrives,
a calendar event about to start, a request to a webhook URL. "When the landlord writes,
summarise it and draft a reply", "half an hour before any meeting with 'review' in the
title, put together a one-page brief", "when the deploy hook is called, check the site".

Three kinds:

- ``mail`` — a new message in the inbox whose sender or subject contains every word of
  ``match`` (empty: any mail). The server polls IMAP while at least one is active.
- ``event`` — a calendar event whose title or place contains every word of ``match``
  is ``lead_minutes`` from starting.
- ``hook`` — ``POST /api/hooks/<id>?key=<secret>``; the request body is the context.

Each firing becomes a background run in the chat the trigger was set from, like a routine,
and shows in the Feed. A firing is recorded by a key (the mail's UID, the event's uid and
start, the hook's delivery id) so the same thing never fires twice.
"""

from __future__ import annotations

import builtins
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

KINDS = ("mail", "event", "hook")
STATUSES = ("active", "cancelled")
MAX_LEAD_MINUTES = 24 * 60


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def words(match: str) -> list[str]:
    return [w for w in (match or "").lower().split() if w]


def matches(match: str, *haystacks: str) -> bool:
    """Every word of ``match`` appears somewhere in the haystacks (case-insensitive).
    An empty ``match`` matches anything."""
    text = " ".join(h for h in haystacks if h).lower()
    return all(w in text for w in words(match))


@dataclass
class Trigger:
    id: str
    kind: str  # mail | event | hook
    match: str  # words to look for; for a hook, the name shown next to its URL
    text: str  # what to do when it fires
    thread: str
    status: str
    lead_minutes: int  # event: how long before the start
    secret: str  # hook: the key in the URL
    created_at: str
    last_fired_at: str
    fired: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "match": self.match,
            "text": self.text,
            "thread": self.thread,
            "status": self.status,
            "lead_minutes": self.lead_minutes,
            "secret": self.secret if self.kind == "hook" else "",
            "created_at": self.created_at,
            "last_fired_at": self.last_fired_at or None,
            "fired": self.fired,
        }

    def describe(self) -> str:
        """The condition, in words: what has to happen for this to fire."""
        if self.kind == "mail":
            return f"mail matching “{self.match}”" if self.match else "any new mail"
        if self.kind == "event":
            what = f"events matching “{self.match}”" if self.match else "any event"
            return f"{self.lead_minutes} min before {what}"
        return f"webhook “{self.match}”" if self.match else "webhook"

    def render(self) -> str:
        return (
            f"[{self.id}] when {self.describe()} → {self.text} ({self.status}, fired {self.fired}×)"
        )


class TriggerStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS triggers (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                match TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                thread TEXT NOT NULL DEFAULT 'main',
                status TEXT NOT NULL DEFAULT 'active',
                lead_minutes INTEGER NOT NULL DEFAULT 30,
                secret TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                last_fired_at TEXT NOT NULL DEFAULT '',
                fired INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS fired (
                trigger_id TEXT NOT NULL,
                key TEXT NOT NULL,
                at TEXT NOT NULL,
                PRIMARY KEY (trigger_id, key)
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ write
    def create(
        self,
        kind: str,
        text: str,
        match: str = "",
        lead_minutes: int = 30,
        thread: str = "main",
    ) -> Trigger:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        text = (text or "").strip()
        if not text:
            raise ValueError("what should happen when it fires?")
        match = " ".join((match or "").split())
        try:
            lead = int(lead_minutes)
        except (TypeError, ValueError):
            raise ValueError("lead_minutes must be a number") from None
        if kind == "event" and not 0 <= lead <= MAX_LEAD_MINUTES:
            raise ValueError("lead_minutes must be between 0 and 1440")
        trigger = Trigger(
            id=f"t_{uuid.uuid4().hex[:6]}",
            kind=kind,
            match=match,
            text=text,
            thread=thread or "main",
            status="active",
            lead_minutes=lead if kind == "event" else 0,
            secret=secrets.token_urlsafe(18) if kind == "hook" else "",
            created_at=_now(),
            last_fired_at="",
            fired=0,
        )
        self._conn.execute(
            "INSERT INTO triggers (id, kind, match, text, thread, status, lead_minutes, secret,"
            " created_at, last_fired_at, fired) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                trigger.id,
                trigger.kind,
                trigger.match,
                trigger.text,
                trigger.thread,
                trigger.status,
                trigger.lead_minutes,
                trigger.secret,
                trigger.created_at,
                "",
                0,
            ),
        )
        self._conn.commit()
        return trigger

    def cancel(self, trigger_id: str) -> Trigger | None:
        item = self.get(trigger_id)
        if item is None or item.status != "active":
            return None
        self._conn.execute("UPDATE triggers SET status='cancelled' WHERE id=?", (trigger_id,))
        self._conn.commit()
        return self.get(trigger_id)

    def delete(self, trigger_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM triggers WHERE id=?", (trigger_id,))
        self._conn.execute("DELETE FROM fired WHERE trigger_id=?", (trigger_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def mark_fired(self, trigger_id: str, key: str) -> bool:
        """Record one firing for ``key``; False when this key already fired (nothing changes)."""
        try:
            self._conn.execute(
                "INSERT INTO fired (trigger_id, key, at) VALUES (?,?,?)", (trigger_id, key, _now())
            )
        except sqlite3.IntegrityError:
            return False
        self._conn.execute(
            "UPDATE triggers SET fired = fired + 1, last_fired_at = ? WHERE id = ?",
            (_now(), trigger_id),
        )
        self._conn.commit()
        return True

    def has_fired(self, trigger_id: str, key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM fired WHERE trigger_id=? AND key=?", (trigger_id, key)
        ).fetchone()
        return row is not None

    def forget_fired_before(self, iso: str) -> int:
        """Drop firing records older than ``iso`` (keys of past mails and events pile up)."""
        cur = self._conn.execute("DELETE FROM fired WHERE at < ?", (iso,))
        self._conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------ read
    def get(self, trigger_id: str) -> Trigger | None:
        row = self._conn.execute("SELECT * FROM triggers WHERE id=?", (trigger_id,)).fetchone()
        return _from_row(row) if row else None

    def list(
        self, status: str | None = "active", kind: str | None = None
    ) -> builtins.list[Trigger]:
        sql, params = "SELECT * FROM triggers", []
        where = []
        if status:
            where.append("status=?")
            params.append(status)
        if kind:
            where.append("kind=?")
            params.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at"
        return [_from_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def active(self, kind: str) -> builtins.list[Trigger]:
        return self.list("active", kind)

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()


def _from_row(row: sqlite3.Row) -> Trigger:
    return Trigger(
        id=row["id"],
        kind=row["kind"],
        match=row["match"],
        text=row["text"],
        thread=row["thread"],
        status=row["status"],
        lead_minutes=int(row["lead_minutes"]),
        secret=row["secret"],
        created_at=row["created_at"],
        last_fired_at=row["last_fired_at"],
        fired=int(row["fired"]),
    )


__all__ = ["KINDS", "MAX_LEAD_MINUTES", "STATUSES", "Trigger", "TriggerStore", "matches", "words"]
