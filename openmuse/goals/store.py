"""Goals: long-horizon objectives broken into steps that survive across sessions.

The agent creates a goal, drafts a plan, and advances one step at a time; the
``openmuse goals run`` command (or the daemon) keeps advancing goals in the
background – the "keeps working after you close the app" part of Muse.

A goal has a category (health, finance, career, …), an optional target date, an
optional check-in cadence (the agent sends a short reminder and asks how it is
going) and, when the agent thinks the plan no longer fits, a *proposal*: a revised
list of remaining steps the user accepts or dismisses. The plan itself is never
rewritten behind the user's back.
"""

from __future__ import annotations

import builtins  # ``list`` is a method name below; the class body needs the type
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

GOAL_STATUSES = ("active", "paused", "done", "cancelled")
STEP_STATUSES = ("pending", "in_progress", "done", "blocked", "skipped")
# Muse's life areas. "" means uncategorised.
CATEGORIES = (
    "health",
    "finance",
    "career",
    "learning",
    "relationships",
    "family",
    "home",
    "travel",
    "creative",
    "other",
)
CHECK_IN_CADENCES = ("daily", "weekdays", "weekly", "monthly")
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# "daily 08:00" · "weekdays 07:30" · "weekly mon 09:00" · "monthly 1 09:00"
_CHECK_IN_RE = re.compile(
    r"^(daily|weekdays|weekly(?: (mon|tue|wed|thu|fri|sat|sun))?|monthly(?: ([1-9]|[12]\d|3[01]))?)"
    r"(?: ([01]?\d|2[0-3]):([0-5]\d))?$"
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_check_in(spec: str) -> tuple[str, int | None, int, int] | None:
    """``"weekly mon 09:00"`` → ``("weekly", 0, 9, 0)``; ``("monthly", 15, h, m)`` for a day of
    the month; ``None`` when the spec is not one we understand. The time defaults to 09:00."""
    m = _CHECK_IN_RE.match((spec or "").strip().lower())
    if not m:
        return None
    head = m.group(1).split()
    cadence = head[0]
    anchor: int | None = None
    if cadence == "weekly":
        anchor = _WEEKDAYS.index(m.group(2)) if m.group(2) else None
    elif cadence == "monthly":
        anchor = int(m.group(3)) if m.group(3) else None
    hour = int(m.group(4)) if m.group(4) else 9
    minute = int(m.group(5)) if m.group(5) else 0
    return cadence, anchor, hour, minute


def next_check_in(spec: str, after: datetime | None = None) -> datetime | None:
    """The first check-in strictly after ``after`` (local time; default now)."""
    parsed = parse_check_in(spec)
    if parsed is None:
        return None
    cadence, anchor, hour, minute = parsed
    now = (after or datetime.now()).astimezone()
    if cadence == "weekly" and anchor is None:
        anchor = now.weekday()  # "weekly" alone: same weekday as today
    day = now.date()
    for _ in range(62):  # two months is enough to hit any monthly anchor
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=now.tzinfo)
        fits = (
            cadence == "daily"
            or (cadence == "weekdays" and day.weekday() < 5)
            or (cadence == "weekly" and day.weekday() == anchor)
            or (cadence == "monthly" and day.day == (anchor or 1))
        )
        if fits and candidate > now:
            return candidate
        day += timedelta(days=1)
    return None


def parse_due(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


@dataclass
class Step:
    id: str
    goal_id: str
    idx: int
    title: str
    status: str = "pending"
    note: str = ""
    updated_at: str = field(default_factory=_now)


@dataclass
class Goal:
    id: str
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str
    steps: list[Step] = field(default_factory=list)
    notes: str = ""
    category: str = ""
    # ISO date the user wants this done by; "" for none
    due: str = ""
    # reminder cadence, see parse_check_in; "" for none
    check_in: str = ""
    # when the next reminder is due (ISO, UTC); "" when there is no cadence
    next_check_in: str = ""
    # a plan change the agent suggested and the user has not answered yet
    proposal: dict | None = None

    @property
    def next_step(self) -> Step | None:
        for s in self.steps:
            if s.status in ("in_progress", "pending"):
                return s
        return None

    @property
    def progress(self) -> str:
        done = sum(1 for s in self.steps if s.status in ("done", "skipped"))
        return f"{done}/{len(self.steps)}"

    @property
    def overdue(self) -> bool:
        d = parse_due(self.due)
        return bool(d and d < date.today() and self.status == "active")

    def render(self, with_notes: bool = True) -> str:
        icons = {
            "pending": "[ ]",
            "in_progress": "[~]",
            "done": "[x]",
            "blocked": "[!]",
            "skipped": "[-]",
        }
        meta = [f"status={self.status}", f"progress={self.progress}"]
        if self.category:
            meta.append(f"category={self.category}")
        if self.due:
            meta.append(f"due={self.due}" + (" OVERDUE" if self.overdue else ""))
        if self.check_in:
            meta.append(f"check_in={self.check_in!r}")
        lines = [f"Goal {self.id}: {self.title}  ({', '.join(meta)})"]
        if self.description:
            lines.append(f"  {self.description}")
        for s in self.steps:
            extra = f"  — {s.note}" if s.note else ""
            lines.append(f"  {icons.get(s.status, '[ ]')} {s.idx}. {s.title}{extra}")
        if self.proposal:
            lines.append(
                f"  proposal awaiting the user's answer: {self.proposal.get('reason', '')} → "
                + "; ".join(self.proposal.get("steps") or [])
            )
        if with_notes and self.notes:
            lines.append(f"  notes: {self.notes}")
        return "\n".join(lines)


class GoalStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS steps (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                idx INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            """
        )
        # columns added after the first release; ALTER is idempotent enough with the check
        have = {r["name"] for r in self._conn.execute("PRAGMA table_info(goals)")}
        for column, decl in (
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("due", "TEXT NOT NULL DEFAULT ''"),
            ("check_in", "TEXT NOT NULL DEFAULT ''"),
            ("next_check_in", "TEXT NOT NULL DEFAULT ''"),
            ("proposal", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in have:
                self._conn.execute(f"ALTER TABLE goals ADD COLUMN {column} {decl}")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ goals
    def create(
        self,
        title: str,
        description: str = "",
        steps: list[str] | None = None,
        category: str = "",
        due: str = "",
        check_in: str = "",
    ) -> Goal:
        title = title.strip()
        if not title:
            raise ValueError("goal title is empty")
        category = _clean_category(category)
        due = _clean_due(due)
        check_in = _clean_check_in(check_in)
        gid = "g_" + uuid.uuid4().hex[:6]
        now = _now()
        nxt = next_check_in(check_in) if check_in else None
        self._conn.execute(
            "INSERT INTO goals (id,title,description,status,notes,created_at,updated_at,"
            "category,due,check_in,next_check_in,proposal) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                gid,
                title,
                description.strip(),
                "active",
                "",
                now,
                now,
                category,
                due,
                check_in,
                nxt.astimezone(UTC).isoformat(timespec="seconds") if nxt else "",
                "",
            ),
        )
        for i, step in enumerate(steps or [], start=1):
            self._conn.execute(
                "INSERT INTO steps (id,goal_id,idx,title,status,note,updated_at) VALUES (?,?,?,?,?,?,?)",
                ("s_" + uuid.uuid4().hex[:6], gid, i, step.strip(), "pending", "", now),
            )
        self._conn.commit()
        return self.get(gid)  # type: ignore[return-value]

    def get(self, goal_id: str) -> Goal | None:
        row = self._conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if not row:
            return None
        steps = [
            Step(
                id=r["id"],
                goal_id=r["goal_id"],
                idx=r["idx"],
                title=r["title"],
                status=r["status"],
                note=r["note"],
                updated_at=r["updated_at"],
            )
            for r in self._conn.execute(
                "SELECT * FROM steps WHERE goal_id = ? ORDER BY idx", (goal_id,)
            ).fetchall()
        ]
        proposal = None
        if row["proposal"]:
            try:
                proposal = json.loads(row["proposal"])
            except ValueError:
                proposal = None
        return Goal(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            steps=steps,
            category=row["category"],
            due=row["due"],
            check_in=row["check_in"],
            next_check_in=row["next_check_in"],
            proposal=proposal,
        )

    def list(self, status: str | None = None, category: str | None = None) -> list[Goal]:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if category:
            where.append("category = ?")
            params.append(category)
        sql = "SELECT id FROM goals" + (" WHERE " + " AND ".join(where) if where else "")
        rows = self._conn.execute(sql + " ORDER BY created_at", params).fetchall()
        return [g for g in (self.get(r["id"]) for r in rows) if g]

    def update(
        self,
        goal_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        due: str | None = None,
        check_in: str | None = None,
    ) -> Goal | None:
        """Change the goal's own fields (not its steps). ``""`` clears due / check_in."""
        goal = self.get(goal_id)
        if not goal:
            return None
        fields: dict[str, str] = {}
        if title is not None and title.strip():
            fields["title"] = title.strip()
        if description is not None:
            fields["description"] = description.strip()
        if category is not None:
            fields["category"] = _clean_category(category)
        if due is not None:
            fields["due"] = _clean_due(due)
        if check_in is not None:
            fields["check_in"] = _clean_check_in(check_in)
            nxt = next_check_in(fields["check_in"]) if fields["check_in"] else None
            fields["next_check_in"] = (
                nxt.astimezone(UTC).isoformat(timespec="seconds") if nxt else ""
            )
        if not fields:
            return goal
        fields["updated_at"] = _now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(f"UPDATE goals SET {sets} WHERE id = ?", (*fields.values(), goal_id))
        self._conn.commit()
        return self.get(goal_id)

    def set_status(self, goal_id: str, status: str) -> Goal | None:
        if status not in GOAL_STATUSES:
            raise ValueError(f"status must be one of {GOAL_STATUSES}")
        self._conn.execute(
            "UPDATE goals SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), goal_id)
        )
        self._conn.commit()
        return self.get(goal_id)

    def append_note(self, goal_id: str, note: str) -> Goal | None:
        goal = self.get(goal_id)
        if not goal:
            return None
        notes = (goal.notes + "\n" if goal.notes else "") + f"[{_now()}] {note.strip()}"
        self._conn.execute(
            "UPDATE goals SET notes = ?, updated_at = ? WHERE id = ?", (notes, _now(), goal_id)
        )
        self._conn.commit()
        return self.get(goal_id)

    def delete(self, goal_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        self._conn.execute("DELETE FROM steps WHERE goal_id = ?", (goal_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ check-ins
    def due_check_ins(self, now: datetime | None = None) -> builtins.list[Goal]:
        """Active goals whose reminder time has come."""
        now_iso = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")
        rows = self._conn.execute(
            "SELECT id FROM goals WHERE status = 'active' AND next_check_in != '' "
            "AND next_check_in <= ? ORDER BY next_check_in",
            (now_iso,),
        ).fetchall()
        return [g for g in (self.get(r["id"]) for r in rows) if g]

    def mark_checked_in(self, goal_id: str, now: datetime | None = None) -> Goal | None:
        """Move the reminder to the occurrence after the one that was due (or, for a check-in
        sent early by hand, after the one that is scheduled)."""
        goal = self.get(goal_id)
        if not goal:
            return None
        after = (now or datetime.now(UTC)).astimezone()
        if goal.next_check_in:
            scheduled = datetime.fromisoformat(goal.next_check_in).astimezone()
            after = max(after, scheduled)
        nxt = next_check_in(goal.check_in, after=after) if goal.check_in else None
        self._conn.execute(
            "UPDATE goals SET next_check_in = ? WHERE id = ?",
            (nxt.astimezone(UTC).isoformat(timespec="seconds") if nxt else "", goal_id),
        )
        self._conn.commit()
        return self.get(goal_id)

    # ------------------------------------------------------------------ proposals
    def propose(self, goal_id: str, reason: str, steps: builtins.list[str]) -> Goal | None:
        """Suggest a revised plan: the remaining steps to replace the current pending ones."""
        goal = self.get(goal_id)
        if not goal:
            return None
        steps = [s.strip() for s in steps if s and s.strip()]
        if not reason.strip() or not steps:
            raise ValueError("a proposal needs a reason and at least one step")
        proposal = {"reason": reason.strip()[:500], "steps": steps[:20], "created_at": _now()}
        self._conn.execute(
            "UPDATE goals SET proposal = ?, updated_at = ? WHERE id = ?",
            (json.dumps(proposal, ensure_ascii=False), _now(), goal_id),
        )
        self._conn.commit()
        return self.get(goal_id)

    def accept_proposal(self, goal_id: str) -> Goal | None:
        """Keep the finished steps, replace everything still open with the proposed ones."""
        goal = self.get(goal_id)
        if not goal or not goal.proposal:
            return goal
        keep = [s for s in goal.steps if s.status in ("done", "skipped")]
        self._conn.execute(
            "DELETE FROM steps WHERE goal_id = ? AND status NOT IN ('done', 'skipped')",
            (goal_id,),
        )
        now = _now()
        idx = max((s.idx for s in keep), default=0)
        for title in goal.proposal.get("steps") or []:
            idx += 1
            self._conn.execute(
                "INSERT INTO steps (id,goal_id,idx,title,status,note,updated_at) VALUES (?,?,?,?,?,?,?)",
                ("s_" + uuid.uuid4().hex[:6], goal_id, idx, title, "pending", "", now),
            )
        self._conn.execute(
            "UPDATE goals SET proposal = '', status = 'active', updated_at = ? WHERE id = ?",
            (now, goal_id),
        )
        self._conn.commit()
        return self.append_note(goal_id, f"plan adjusted: {goal.proposal.get('reason', '')}")

    def dismiss_proposal(self, goal_id: str) -> Goal | None:
        goal = self.get(goal_id)
        if not goal or not goal.proposal:
            return goal
        self._conn.execute(
            "UPDATE goals SET proposal = '', updated_at = ? WHERE id = ?", (_now(), goal_id)
        )
        self._conn.commit()
        return self.append_note(
            goal_id, f"the user kept the plan (declined: {goal.proposal.get('reason', '')})"
        )

    # ------------------------------------------------------------------ steps
    def add_step(self, goal_id: str, title: str) -> Goal | None:
        goal = self.get(goal_id)
        if not goal:
            return None
        idx = (max((s.idx for s in goal.steps), default=0)) + 1
        self._conn.execute(
            "INSERT INTO steps (id,goal_id,idx,title,status,note,updated_at) VALUES (?,?,?,?,?,?,?)",
            ("s_" + uuid.uuid4().hex[:6], goal_id, idx, title.strip(), "pending", "", _now()),
        )
        self._conn.commit()
        return self.get(goal_id)

    def update_step(
        self, goal_id: str, step_index: int, status: str | None = None, note: str | None = None
    ) -> Goal | None:
        if status is not None and status not in STEP_STATUSES:
            raise ValueError(f"step status must be one of {STEP_STATUSES}")
        goal = self.get(goal_id)
        if not goal:
            return None
        step = next((s for s in goal.steps if s.idx == step_index), None)
        if step is None:
            raise ValueError(f"goal {goal_id} has no step {step_index}")
        self._conn.execute(
            "UPDATE steps SET status = ?, note = ?, updated_at = ? WHERE id = ?",
            (status or step.status, note if note is not None else step.note, _now(), step.id),
        )
        self._conn.execute("UPDATE goals SET updated_at = ? WHERE id = ?", (_now(), goal_id))
        self._conn.commit()
        updated = self.get(goal_id)
        # Auto-complete the goal when every step is done/skipped.
        if (
            updated
            and updated.steps
            and all(s.status in ("done", "skipped") for s in updated.steps)
        ):
            updated = self.set_status(goal_id, "done")
        return updated


def _clean_category(value: str) -> str:
    value = (value or "").strip().lower()
    return value if value in CATEGORIES else ""


def _clean_due(value: str) -> str:
    d = parse_due(value or "")
    return d.isoformat() if d else ""


def _clean_check_in(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    if parse_check_in(value) is None:
        raise ValueError(
            "check_in must look like 'daily 08:00', 'weekdays 07:30', 'weekly mon 09:00' or "
            "'monthly 1 09:00'"
        )
    return value


__all__ = [
    "CATEGORIES",
    "CHECK_IN_CADENCES",
    "GOAL_STATUSES",
    "STEP_STATUSES",
    "Goal",
    "GoalStore",
    "Step",
    "next_check_in",
    "parse_check_in",
    "parse_due",
]
