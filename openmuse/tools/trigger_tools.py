"""Triggers (create / list / cancel): work that starts when something happens."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment
from openmuse.triggers.store import TriggerStore


class Triggers(BaseTool):
    name: str = "triggers"
    description: str = (
        "Do something whenever an event happens, on the user's behalf — the other half of "
        "`reminders`, which fire at a time. Kinds: kind=`mail` — a new mail whose sender or "
        "subject contains every word of `match` arrives (empty match: any mail); kind=`event` — "
        "a calendar event whose title or place contains every word of `match` is `lead_minutes` "
        "(default 30) from starting; kind=`hook` — a program calls the trigger's webhook URL "
        "(`match` is just a name for it; the URL with its key is in the result and in the app). "
        "`text` is the standing instruction: what to do each time, in the user's words; when it "
        "fires you get the mail, event or request as context and you do that work. Actions: "
        "`create` (kind, text, match, lead_minutes), `list`, `cancel` (trigger_id). Mail triggers "
        "need the email connector, event triggers the calendar connector. Shows in the app under "
        "Upcoming."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "list", "cancel"]},
            "kind": {"type": "string", "enum": ["mail", "event", "hook"]},
            "match": {
                "type": "string",
                "description": (
                    "Words that must all appear in the sender/subject (mail) or title/place "
                    "(event); a name for a hook. Empty matches everything."
                ),
            },
            "text": {"type": "string", "description": "What to do when it fires."},
            "lead_minutes": {
                "type": "integer",
                "minimum": 0,
                "maximum": 1440,
                "description": "event: how long before the start (default 30).",
            },
            "trigger_id": {"type": "string"},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    store: TriggerStore
    # which chat a new trigger reports to (the server sets this; the CLI has one chat)
    thread_of: Callable[[], str] = lambda: "main"
    # the server hooks this to tell the app and to start watching the inbox right away
    on_change: Callable[[], None] | None = None
    # the app's URL, so a new hook can be shown with its address ("" in the CLI)
    base_url: str = ""
    # which kinds have their connector: {"mail": bool, "event": bool}
    available: Callable[[], dict[str, bool]] = lambda: {"mail": True, "event": True}

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        action = str(args.get("action") or "?")
        if action == "create":
            detail = f"{args.get('kind') or '?'} “{args.get('match') or '*'}” — {str(args.get('text') or '')[:60]}"
        elif action == "cancel":
            detail = str(args.get("trigger_id") or "")
        else:
            detail = ""
        a.summary = f"triggers {action}" + (f": {detail}" if detail else "")
        return a

    async def execute(
        self,
        action: str = "",
        kind: str | None = None,
        match: str | None = None,
        text: str | None = None,
        lead_minutes: int | None = None,
        trigger_id: str | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            if action == "create":
                if not text:
                    return ToolResult.fail("`text` is required")
                if not kind:
                    return ToolResult.fail("`kind` is required: mail, event or hook")
                have = self.available()
                if kind == "mail" and not have.get("mail", False):
                    return ToolResult.fail(
                        "the email connector is not set up — the user connects a mailbox under Connections first"
                    )
                if kind == "event" and not have.get("event", False):
                    return ToolResult.fail(
                        "the calendar connector is not set up — the user adds a calendar under Connections first"
                    )
                item = self.store.create(
                    kind,
                    text,
                    match=match or "",
                    lead_minutes=30 if lead_minutes is None else lead_minutes,
                    thread=self.thread_of(),
                )
                self._changed()
                out = f"Trigger set.\n{item.render()}"
                if item.kind == "hook":
                    url = f"{self.base_url}/api/hooks/{item.id}?key={item.secret}"
                    out += (
                        f"\nWebhook URL (POST, any body; keep the key private): {url}\n"
                        "The user can copy it from the app under Upcoming."
                    )
                elif item.kind == "event":
                    out += (
                        "\nChecked every half minute; a matching event that is already inside "
                        "the lead window fires on the next check, so do not do that work here."
                    )
                else:
                    out += (
                        "\nThe inbox is looked at every few minutes from now on; mail that "
                        "arrived before now is not replayed."
                    )
                return ToolResult(output=out)
            if action == "list":
                items = self.store.list("active")
                if not items:
                    return ToolResult(output="No triggers.")
                return ToolResult(output="\n".join(i.render() for i in items))
            if action == "cancel":
                if not trigger_id:
                    return ToolResult.fail("`trigger_id` is required")
                cancelled = self.store.cancel(trigger_id)
                if cancelled is None:
                    return ToolResult.fail(f"no active trigger {trigger_id}")
                self._changed()
                return ToolResult(output=f"Cancelled.\n{cancelled.render()}")
            return ToolResult.fail(f"unknown action {action!r}")
        except ValueError as exc:
            return ToolResult.fail(str(exc))

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()
