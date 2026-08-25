"""Goals: long-horizon objectives broken into steps that survive across sessions.

The agent creates a goal, drafts a plan, and advances one step at a time; the
``openmuse goals run`` command (or the daemon) keeps advancing goals in the
background – the "keeps working after you close the app" part of Muse.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

GOAL_STATUSES = ("active", "paused", "done", "cancelled")
STEP_STATUSES = ("pending", "in_progress", "done", "blocked", "skipped")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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

    def render(self, with_notes: bool = True) -> str:
        icons = {
            "pending": "[ ]",
            "in_progress": "[~]",
            "done": "[x]",
            "blocked": "[!]",
            "skipped": "[-]",
        }
        lines = [f"Goal {self.id}: {self.title}  (status={self.status}, progress={self.progress})"]
        if self.description:
            lines.append(f"  {self.description}")
        for s in self.steps:
            extra = f"  — {s.note}" if s.note else ""
            lines.append(f"  {icons.get(s.status, '[ ]')} {s.idx}. {s.title}{extra}")
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
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ goals
    def create(self, title: str, description: str = "", steps: list[str] | None = None) -> Goal:
        title = title.strip()
        if not title:
            raise ValueError("goal title is empty")
        gid = "g_" + uuid.uuid4().hex[:6]
        now = _now()
        self._conn.execute(
            "INSERT INTO goals (id,title,description,status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (gid, title, description.strip(), "active", "", now, now),
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
        return Goal(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            steps=steps,
        )

    def list(self, status: str | None = None) -> list[Goal]:
        if status:
            rows = self._conn.execute(
                "SELECT id FROM goals WHERE status = ? ORDER BY created_at", (status,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT id FROM goals ORDER BY created_at").fetchall()
        return [g for g in (self.get(r["id"]) for r in rows) if g]

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


__all__ = ["GOAL_STATUSES", "STEP_STATUSES", "Goal", "GoalStore", "Step"]
