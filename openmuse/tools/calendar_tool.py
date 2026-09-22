"""The ``calendar`` tool: agenda, search, free time, and events drafted as ``.ics`` files."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from openmuse.calendar import CalendarFeeds, make_ics
from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment


def _parse_day(value: str | None, today: date) -> date:
    v = (value or "").strip().lower()
    if not v or v == "today":
        return today
    if v == "tomorrow":
        return today + timedelta(days=1)
    if v == "yesterday":
        return today - timedelta(days=1)
    return date.fromisoformat(v[:10])


def _parse_when(value: str, tz: Any) -> tuple[datetime, bool]:
    """'YYYY-MM-DD HH:MM' → aware local datetime; 'YYYY-MM-DD' → midnight, all-day."""
    v = value.strip().replace("T", " ")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return datetime.combine(date.fromisoformat(v), datetime.min.time(), tzinfo=tz), True
    dt = datetime.strptime(v[:16], "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=tz), False


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\u3400-\u9fff-]+", "-", text.strip().lower()).strip("-")
    return (s or "event")[:60]


class Calendar(BaseTool):
    name: str = "calendar"
    description: str = (
        "The user's calendar (read from their calendar feeds). Actions: `agenda` — the events "
        "on a `day` ('today', 'tomorrow' or 'YYYY-MM-DD') and the `days` after it (default 1, "
        "max 31); `search` — events whose title, place or notes contain `query` (past 90 and "
        "next 180 days); `free` — gaps of at least `minutes` in the working hours of `day`; "
        "`draft` — write an event as an .ics file the user can add to their calendar with a "
        "tap (`title`, `start` 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD' for all-day, `end` likewise "
        "or `duration_minutes`, optional `location`, `notes`). You cannot change the user's "
        "calendar directly; `draft` is how you propose an event. Times are the user's local time."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["agenda", "search", "free", "draft", "refresh"]},
            "day": {"type": "string", "description": "'today', 'tomorrow' or 'YYYY-MM-DD'"},
            "days": {"type": "integer", "minimum": 1, "maximum": 31},
            "query": {"type": "string"},
            "minutes": {"type": "integer", "minimum": 5, "description": "free: shortest gap"},
            "title": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "duration_minutes": {"type": "integer", "minimum": 5},
            "location": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    reads_private_data: bool = True
    feeds: CalendarFeeds
    workspace: Path

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        a = super().assess(args)
        action = str(args.get("action") or "?")
        if action == "draft":
            a.risk = RiskLevel.MODERATE
            a.reads_private_data = False
            a.summary = f"calendar: draft “{args.get('title', '')}” {args.get('start', '')}"
        elif action == "search":
            a.summary = f"calendar: search “{args.get('query', '')}”"
        elif action == "free":
            a.summary = f"calendar: free time {args.get('day') or 'today'}"
        elif action == "refresh":
            a.reads_private_data = False
            a.summary = "calendar: refresh feeds"
        else:
            span = f" +{args['days']}d" if args.get("days") else ""
            a.summary = f"calendar: agenda {args.get('day') or 'today'}{span}"
        return a

    async def execute(self, action: str = "agenda", **args: Any) -> ToolResult:
        feeds = self.feeds
        if not feeds.configured and action != "draft":
            return ToolResult.fail(
                "no calendar is connected. The user can add one under Connections → Calendar "
                "(a private .ics link from Google, Outlook, iCloud, Fastmail or Nextcloud)."
            )
        today = datetime.now(feeds.tz).date()
        try:
            if action == "refresh":
                status = await feeds.refresh(force=True)
                lines = [
                    f"{f['name']}: {f['events']} events"
                    + (f" — {f['error']}" if f["error"] else "")
                    for f in status["feeds"]
                ]
                return ToolResult(output="Refreshed.\n" + "\n".join(lines))
            if action == "draft":
                return self._draft(args)
            await feeds.refresh()  # only if stale
            if action == "search":
                query = str(args.get("query") or "").strip()
                if not query:
                    return ToolResult.fail("search needs a query")
                hits = feeds.search(query, today)[:30]
                head = (
                    f"{len(hits)} event(s) matching “{query}”:"
                    if hits
                    else f"No events match “{query}”."
                )
                return ToolResult(output=head + ("\n" + feeds.render(hits, today) if hits else ""))
            day = _parse_day(args.get("day"), today)
            if action == "free":
                minutes = int(args.get("minutes") or 30)
                s = feeds.settings
                slots = feeds.free_slots(day, minutes, s.day_start, s.day_end)
                if not slots:
                    return ToolResult(
                        output=f"No free gap of {minutes}+ minutes on {day:%a %Y-%m-%d} between {s.day_start} and {s.day_end}."
                    )
                lines = [f"  {sl.start:%H:%M}–{sl.end:%H:%M}  ({sl.minutes} min)" for sl in slots]
                return ToolResult(
                    output=f"Free on {day:%a %Y-%m-%d} ({s.day_start}–{s.day_end}), gaps of {minutes}+ min:\n"
                    + "\n".join(lines)
                )
            days = max(1, min(31, int(args.get("days") or 1)))
            items = feeds.agenda(day, days)
            note = self._errors_note()
            return ToolResult(output=feeds.render(items, today) + note)
        except ValueError as exc:
            return ToolResult.fail(str(exc))

    def _errors_note(self) -> str:
        broken = [s for s in self.feeds.states.values() if s.error]
        if not broken:
            return ""
        return "\n(feed problems: " + "; ".join(f"{s.name}: {s.error}" for s in broken) + ")"

    def _draft(self, args: dict[str, Any]) -> ToolResult:
        # Some models HTML-escape their arguments ("Alex &amp; Alice"); nothing on a calendar
        # is meant to carry entities, so they are undone here.
        title = html.unescape(str(args.get("title") or "")).strip()
        if not title or not args.get("start"):
            return ToolResult.fail("draft needs a title and a start")
        tz = self.feeds.tz
        start, all_day = _parse_when(str(args["start"]), tz)
        if args.get("end"):
            end, _ = _parse_when(str(args["end"]), tz)
            if all_day:
                end = end + timedelta(days=1)  # DTEND is exclusive for all-day events
        elif all_day:
            end = start + timedelta(days=1)
        else:
            end = start + timedelta(minutes=int(args.get("duration_minutes") or 60))
        if end <= start:
            return ToolResult.fail("the end must be after the start")
        ics = make_ics(
            title,
            start,
            end,
            all_day=all_day,
            location=html.unescape(str(args.get("location") or "")),
            description=html.unescape(str(args.get("notes") or "")),
        )
        folder = self.workspace / "calendar"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{start:%Y-%m-%d}-{_slug(title)}.ics"
        path.write_text(ics, encoding="utf-8")
        rel = path.relative_to(self.workspace)
        when = f"{start:%a %Y-%m-%d}" if all_day else f"{start:%a %Y-%m-%d %H:%M}–{end:%H:%M}"
        return ToolResult(
            output=f"Drafted “{title}” ({when}) as {rel}. The user adds it to their calendar by "
            "opening the file; tell them where it is."
        )


__all__ = ["Calendar"]
