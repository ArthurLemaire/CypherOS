"""Reminders and routines: things the user asked to hear about, or have done, at a time.

"Remind me at six to call mum" is a *reminder*: at 18:00 the agent says so, and does nothing
else. "Every Monday morning, pull my week's calendar into a page" is a *routine*: at that time
the agent does the work and reports the result. Both live here; the service fires them from
its scheduler loop, and each one becomes a normal message from the agent in the chat it was
set from — with the notice that started it, so the Feed can tell what happened while you
were away.

One-off items fire once and are kept as ``done`` for a while so the list shows what
happened; repeating ones use the same cadence grammar as goal check-ins
(``daily 08:00``, ``weekdays 07:30``, ``weekly mon 09:00``, ``monthly 1 09:00``).
"""

from __future__ import annotations

import builtins  # ``list`` is a method name below; the class body needs the type
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openmuse.goals.store import next_check_in, parse_check_in

KINDS = ("remind", "task")
STATUSES = ("active", "done", "cancelled")
# how long finished one-offs stay in the list
_KEEP_DONE = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def parse_when(value: str) -> datetime | None:
    """A point in time as the model or the app writes it: ``2026-09-23 18:00``,
    ``2026-09-23T18:00``, with or without seconds or an offset. Naive values are local
    time. ``None`` when it does not parse."""
    text = (value or "").strip().replace("T", " ")
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()  # local
        return parsed
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


@dataclass
class Reminder:
    id: str
    text: str
    kind: str  # remind | task
    thread: str
    status: str
    next_at: str  # ISO UTC; "" once a one-off has fired
    repeat: str  # "" or a cadence spec
    created_at: str
    last_fired_at: str
    fired: int

    @property
    def repeating(self) -> bool:
        return bool(self.repeat)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "thread": self.thread,
            "status": self.status,
            "next_at": self.next_at or None,
            "repeat": self.repeat,
            "created_at": self.created_at,
            "last_fired_at": self.last_fired_at or None,
            "fired": self.fired,
        }

    def render(self) -> str:
        when = self.repeat or (self.next_at and _local(self.next_at)) or "—"
        what = "remind" if self.kind == "remind" else "do"
        return f"[{self.id}] {when} · {what}: {self.text} ({self.status})"


def _local(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


class ReminderStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'remind',
                thread TEXT NOT NULL DEFAULT 'main',
                status TEXT NOT NULL DEFAULT 'active',
                next_at TEXT NOT NULL DEFAULT '',
                repeat TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                last_fired_at TEXT NOT NULL DEFAULT '',
                fired INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ write
    def create(
        self,
        text: str,
        at: str = "",
        repeat: str = "",
        kind: str = "remind",
        thread: str = "main",
    ) -> Reminder:
        """``at`` for a one-off (any time in the future), ``repeat`` for a routine (the first
        occurrence is computed; ``at`` is ignored). One of the two is required."""
        text = text.strip()
        if not text:
            raise ValueError("what should the reminder say?")
        kind = kind if kind in KINDS else "remind"
        repeat = (repeat or "").strip().lower()
        if repeat:
            if parse_check_in(repeat) is None:
                raise ValueError(
                    f"unknown cadence {repeat!r}; use 'daily 08:00', 'weekdays 07:30', "
                    "'weekly mon 09:00' or 'monthly 1 09:00'"
                )
            first = next_check_in(repeat)
            if first is None:  # pragma: no cover - the grammar always yields a next time
                raise ValueError("could not compute the first occurrence")
        else:
            parsed = parse_when(at)
            if parsed is None:
                raise ValueError(f"could not read the time {at!r}; use 'YYYY-MM-DD HH:MM'")
            if parsed <= _now() - timedelta(minutes=1):
                # the model often works from a time quoted earlier in the conversation
                now_local = _now().astimezone().strftime("%Y-%m-%d %H:%M")
                raise ValueError(f"{at} is in the past — it is now {now_local}")
            first = parsed
        rid = "r_" + uuid.uuid4().hex[:6]
        self._conn.execute(
            "INSERT INTO reminders (id,text,kind,thread,status,next_at,repeat,created_at,"
            "last_fired_at,fired) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, text, kind, thread or "main", "active", _iso(first), repeat, _iso(_now()), "", 0),
        )
        self._conn.commit()
        return self.get(rid)  # type: ignore[return-value]

    def cancel(self, reminder_id: str) -> Reminder | None:
        cur = self._conn.execute(
            "UPDATE reminders SET status = 'cancelled', next_at = '' WHERE id = ? AND status = 'active'",
            (reminder_id,),
        )
        self._conn.commit()
        return self.get(reminder_id) if cur.rowcount else None

    def delete(self, reminder_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def mark_fired(self, reminder_id: str, now: datetime | None = None) -> Reminder | None:
        """Called when the item was handed to the agent: a routine moves to its next
        occurrence, a one-off is done."""
        item = self.get(reminder_id)
        if item is None or item.status != "active":
            return None
        now = now or _now()
        nxt = next_check_in(item.repeat, now.astimezone()) if item.repeat else None
        self._conn.execute(
            "UPDATE reminders SET next_at = ?, status = ?, last_fired_at = ?, fired = fired + 1 "
            "WHERE id = ?",
            (_iso(nxt) if nxt else "", "active" if nxt else "done", _iso(now), reminder_id),
        )
        self._conn.commit()
        return self.get(reminder_id)

    # ------------------------------------------------------------------ read
    def get(self, reminder_id: str) -> Reminder | None:
        row = self._conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, status: str | None = "active") -> builtins.list[Reminder]:
        """Active items soonest first; ``None`` for everything (recent finished ones
        included, older finished ones pruned)."""
        if status is None:
            self._prune()
            rows = self._conn.execute(
                "SELECT * FROM reminders ORDER BY status = 'active' DESC, "
                "CASE WHEN next_at = '' THEN last_fired_at ELSE next_at END"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM reminders WHERE status = ? ORDER BY next_at", (status,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def due(self, now: datetime | None = None) -> builtins.list[Reminder]:
        cutoff = _iso(now or _now())
        rows = self._conn.execute(
            "SELECT * FROM reminders WHERE status = 'active' AND next_at != '' AND next_at <= ? "
            "ORDER BY next_at",
            (cutoff,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def _prune(self) -> None:
        self._conn.execute(
            "DELETE FROM reminders WHERE status != 'active' AND last_fired_at != '' "
            "AND last_fired_at < ?",
            (_iso(_now() - _KEEP_DONE),),
        )
        self._conn.execute(
            "DELETE FROM reminders WHERE status = 'cancelled' AND last_fired_at = '' "
            "AND created_at < ?",
            (_iso(_now() - _KEEP_DONE),),
        )
        self._conn.commit()

    @staticmethod
    def _row(row: sqlite3.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            text=row["text"],
            kind=row["kind"],
            thread=row["thread"],
            status=row["status"],
            next_at=row["next_at"],
            repeat=row["repeat"],
            created_at=row["created_at"],
            last_fired_at=row["last_fired_at"],
            fired=int(row["fired"]),
        )
