"""Reminders and routines (create / list / cancel)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openmuse.reminders import ReminderStore
from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment


class Reminders(BaseTool):
    name: str = "reminders"
    description: str = (
        "Schedule something for later, on the user's behalf. Two kinds: kind=`remind` — at that "
        'time you simply tell the user the text ("call mum", "the parking runs out"); '
        'kind=`task` — at that time you do the work described and report the result ("summarise '
        'unread email", "check the weather for the ride"). Actions: `create` (text, kind, and '
        "either `at` = 'YYYY-MM-DD HH:MM' local time for a one-off, or `repeat` = 'daily 08:00' | "
        "'weekdays 07:30' | 'weekly mon 09:00' | 'monthly 1 09:00' for a routine), `list`, "
        "`cancel` (reminder_id). Work out the exact time from the current date/time in your "
        "context ('tomorrow morning' → tomorrow 09:00; 'in 20 minutes' → now + 20 min). Use this "
        "whenever the user says remind me / every morning / at 6pm / later today; it fires whether "
        "or not the app is open, and shows in the app under Upcoming."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "list", "cancel"]},
            "text": {
                "type": "string",
                "description": "What to remind about, or what to do — in the user's words.",
            },
            "kind": {"type": "string", "enum": ["remind", "task"]},
            "at": {
                "type": "string",
                "description": "One-off: 'YYYY-MM-DD HH:MM' in the user's local time.",
            },
            "repeat": {
                "type": "string",
                "description": (
                    "Routine: 'daily 08:00', 'weekdays 07:30', 'weekly mon 09:00', "
                    "'monthly 1 09:00' (local time)."
                ),
            },
            "reminder_id": {"type": "string"},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    store: ReminderStore
    # which chat a new item belongs to (the server sets this; the CLI has one chat)
    thread_of: Callable[[], str] = lambda: "main"
    # the server hooks this to reschedule its loop when something new is due soon
    on_change: Callable[[], None] | None = None

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        action = str(args.get("action") or "?")
        if action == "create":
            when = args.get("repeat") or args.get("at") or "?"
            detail = f"{when} — {str(args.get('text') or '')[:60]}"
        elif action == "cancel":
            detail = str(args.get("reminder_id") or "")
        else:
            detail = ""
        a.summary = f"reminders {action}" + (f": {detail}" if detail else "")
        return a

    async def execute(
        self,
        action: str = "",
        text: str | None = None,
        kind: str | None = None,
        at: str | None = None,
        repeat: str | None = None,
        reminder_id: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            if action == "create":
                if not text:
                    return ToolResult.fail("`text` is required")
                if not (at or repeat):
                    return ToolResult.fail("give `at` (one-off) or `repeat` (routine)")
                item = self.store.create(
                    text,
                    at=at or "",
                    repeat=repeat or "",
                    kind=kind or "remind",
                    thread=self.thread_of(),
                )
                self._changed()
                verb = "Routine set" if item.repeating else "Reminder set"
                return ToolResult(output=f"{verb}.\n{item.render()}")
            if action == "list":
                items = self.store.list("active")
                if not items:
                    return ToolResult(output="Nothing scheduled.")
                return ToolResult(output="\n".join(i.render() for i in items))
            if action == "cancel":
                if not reminder_id:
                    return ToolResult.fail("`reminder_id` is required")
                cancelled = self.store.cancel(reminder_id)
                if cancelled is None:
                    return ToolResult.fail(f"no active reminder {reminder_id}")
                self._changed()
                return ToolResult(output=f"Cancelled.\n{cancelled.render()}")
            return ToolResult.fail(f"unknown action {action!r}")
        except ValueError as exc:
            return ToolResult.fail(str(exc))

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()
