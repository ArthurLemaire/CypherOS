"""The calendar connector: .ics parsing and recurrence, feeds and cache, the tool."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from openmuse.calendar import CalendarFeeds, expand, make_ics, parse_ics
from openmuse.calendar.ics import parse_duration, unescape, unfold
from openmuse.config import CalendarFeedSettings, CalendarSettings
from openmuse.tools import Calendar

TZ = ZoneInfo("Asia/Shanghai")

FEED = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
BEGIN:VEVENT\r
UID:standup\r
DTSTART;TZID=Asia/Shanghai:20260921T093000\r
DTEND;TZID=Asia/Shanghai:20260921T100000\r
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20261231T000000Z\r
EXDATE;TZID=Asia/Shanghai:20260925T093000\r
SUMMARY:Standup\r
LOCATION:Zoom\r
BEGIN:VALARM\r
TRIGGER:-PT10M\r
ACTION:DISPLAY\r
DESCRIPTION:Reminder\r
END:VALARM\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:standup\r
RECURRENCE-ID;TZID=Asia/Shanghai:20260923T093000\r
DTSTART;TZID=Asia/Shanghai:20260923T110000\r
DTEND;TZID=Asia/Shanghai:20260923T113000\r
SUMMARY:Standup (moved)\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:holiday\r
DTSTART;VALUE=DATE:20260924\r
DTEND;VALUE=DATE:20260926\r
SUMMARY:公司团建\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:lunch\r
DTSTART:20260922T040000Z\r
DURATION:PT1H30M\r
SUMMARY:Lunch with Li\\, Wei\r
DESCRIPTION:Line one\\nLine two; with a semicolon\\; kept\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:gone\r
DTSTART:20260922T080000Z\r
DTEND:20260922T090000Z\r
SUMMARY:Cancelled thing\r
STATUS:CANCELLED\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:long\r
DTSTART;TZID=China Standard Time:20260923T150000\r
DTEND;TZID=China Standard Time:20260923T160000\r
SUMMARY:A meeting with a title that is long enough to be folded onto a second line by t\r
 he server\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_unfold_unescape_duration():
    assert unfold("A:1\r\n b\r\nB:2\r\n\tc") == ["A:1b", "B:2c"]
    assert unescape("a\\, b\\; c\\nd\\\\e") == "a, b; c\nd\\e"
    assert parse_duration("PT1H30M") == timedelta(hours=1, minutes=30)
    assert parse_duration("P1DT2H") == timedelta(days=1, hours=2)
    assert parse_duration("-P1W") == -timedelta(weeks=1)


def test_parse_and_expand_a_real_looking_feed():
    events = parse_ics(FEED, TZ, calendar="Work")
    assert [e.uid for e in events] == ["standup", "standup", "holiday", "lunch", "gone", "long"]
    lunch = next(e for e in events if e.uid == "lunch")
    assert lunch.summary == "Lunch with Li, Wei"
    assert lunch.description == "Line one\nLine two; with a semicolon; kept"
    assert lunch.start.astimezone(TZ).hour == 12 and lunch.duration == timedelta(minutes=90)
    long = next(e for e in events if e.uid == "long")
    assert long.summary.endswith("by the server") and long.start.tzinfo == TZ

    week = expand(events, datetime(2026, 9, 21, tzinfo=TZ), datetime(2026, 9, 28, tzinfo=TZ))
    rows = [(o.start.astimezone(TZ).strftime("%a %H:%M"), o.summary) for o in week]
    assert ("Mon 09:30", "Standup") in rows
    assert ("Wed 11:00", "Standup (moved)") in rows, "RECURRENCE-ID replaces that occurrence"
    assert ("Wed 09:30", "Standup") not in rows
    assert not any(r[0].startswith("Fri") and r[1] == "Standup" for r in rows), "EXDATE"
    assert not any(o.summary == "Cancelled thing" for o in week)
    holiday = next(o for o in week if o.summary == "公司团建")
    assert holiday.all_day and (holiday.end - holiday.start) == timedelta(days=2)
    # sorted by start; the two-day holiday still overlaps a window that starts on its 2nd day
    assert [o.start for o in week] == sorted(o.start for o in week)
    day2 = expand(events, datetime(2026, 9, 25, tzinfo=TZ), datetime(2026, 9, 26, tzinfo=TZ))
    assert [o.summary for o in day2] == ["公司团建"]


def test_expand_handles_until_dates_and_monthly_rules():
    ics = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:rent\nDTSTART;VALUE=DATE:20260101\n"
        "RRULE:FREQ=MONTHLY;BYMONTHDAY=1;UNTIL=20260401\nSUMMARY:Rent\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    events = parse_ics(ics, TZ)
    year = expand(events, datetime(2026, 1, 1, tzinfo=TZ), datetime(2027, 1, 1, tzinfo=TZ))
    assert [o.start.date() for o in year] == [date(2026, m, 1) for m in (1, 2, 3, 4)]


def test_broken_events_are_skipped_not_fatal():
    ics = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART:not-a-date\nSUMMARY:Bad\nEND:VEVENT\nBEGIN:VEVENT\nUID:y\nDTSTART:20260922T080000Z\nSUMMARY:Good\nEND:VEVENT\nEND:VCALENDAR\n"
    events = parse_ics(ics, TZ)
    assert [e.uid for e in events] == ["y"]
    assert events[0].end == events[0].start, "no DTEND, no DURATION: a zero-length event"


def test_make_ics_round_trips():
    start = datetime(2026, 10, 3, 14, 0, tzinfo=TZ)
    text = make_ics(
        "Dentist, then coffee",
        start,
        start + timedelta(minutes=45),
        location="12 Nanjing Rd; 3F",
        description="Bring the x-ray\nand the card",
    )
    assert "SUMMARY:Dentist\\, then coffee" in text and "LOCATION:12 Nanjing Rd\\; 3F" in text
    assert "DTSTART:20261003T060000Z" in text
    [ev] = parse_ics(text, TZ)
    assert (
        ev.summary == "Dentist, then coffee"
        and ev.start == start
        and ev.duration == timedelta(minutes=45)
    )
    assert ev.description == "Bring the x-ray\nand the card"
    all_day = make_ics(
        "Holiday", datetime(2026, 10, 1, tzinfo=TZ), datetime(2026, 10, 2, tzinfo=TZ), all_day=True
    )
    [ev] = parse_ics(all_day, TZ)
    assert ev.all_day and ev.start.date() == date(2026, 10, 1)
    assert all(len(line.encode()) <= 75 for line in make_ics("x" * 200, start, start).split("\r\n"))


def settings_for(*urls: str, enabled: bool = True) -> CalendarSettings:
    return CalendarSettings(
        enabled=enabled,
        feeds=[CalendarFeedSettings(name=f"cal{i}", url=u) for i, u in enumerate(urls)],
        refresh_minutes=30,
    )


async def test_feeds_read_files_cache_and_answer_from_the_cache(tmp_path: Path):
    ics_file = tmp_path / "work.ics"
    ics_file.write_text(FEED, encoding="utf-8")
    cache = tmp_path / "cache.json"
    feeds = CalendarFeeds(settings_for(str(ics_file)), cache_file=cache, tz=TZ)
    assert feeds.configured and feeds.stale()
    status = await feeds.refresh()
    assert status["feeds"][0]["events"] == 6 and not status["feeds"][0]["error"]
    assert not feeds.stale()

    agenda = feeds.agenda(date(2026, 9, 23))
    assert [o.summary for o in agenda] == [
        "Standup (moved)",
        "A meeting with a title that is long enough to be folded onto a second line by the server",
    ]
    text = feeds.render(agenda, today=date(2026, 9, 23))
    assert (
        text.startswith("Wed 2026-09-23 (today)") and "11:00–11:30" in text and "@ Zoom" not in text
    )

    assert [o.summary for o in feeds.search("li, wei", date(2026, 9, 22))] == ["Lunch with Li, Wei"]
    slots = feeds.free_slots(date(2026, 9, 23), 30, "09:00", "18:00")
    assert [(s.start.strftime("%H:%M"), s.end.strftime("%H:%M")) for s in slots] == [
        ("09:00", "11:00"),
        ("11:30", "15:00"),
        ("16:00", "18:00"),
    ]
    # a fresh object with the same cache file answers without fetching
    again = CalendarFeeds(settings_for(str(ics_file)), cache_file=cache, tz=TZ)
    assert not again.stale() and len(again.agenda(date(2026, 9, 23))) == 2


async def test_feeds_fetch_over_http_and_report_a_broken_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/good.ics":
            return httpx.Response(200, text=FEED)
        return httpx.Response(404, text="gone")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client(**kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", client)
    feeds = CalendarFeeds(
        settings_for("https://cal.example/good.ics", "https://cal.example/missing.ics"), tz=TZ
    )
    status = await feeds.refresh()
    good, bad = status["feeds"]
    assert good["events"] == 6 and not good["error"]
    assert bad["events"] == 0 and "404" in bad["error"]
    assert len(feeds.agenda(date(2026, 9, 21))) == 1, "the good feed still answers"


async def test_calendar_tool(tmp_path: Path):
    ics_file = tmp_path / "work.ics"
    ics_file.write_text(FEED, encoding="utf-8")
    feeds = CalendarFeeds(settings_for(str(ics_file)), tz=TZ)
    ws = tmp_path / "ws"
    ws.mkdir()
    tool = Calendar(feeds=feeds, workspace=ws)

    assert tool.assess({"action": "agenda", "day": "2026-09-23"}).reads_private_data
    assert (
        tool.assess({"action": "draft", "title": "x", "start": "2026-10-01 09:00"}).risk.value
        == "moderate"
    )

    out = (await tool.execute(action="agenda", day="2026-09-21", days=3)).output
    assert (
        "Mon 2026-09-21" in out
        and "Standup" in out
        and "Lunch with Li, Wei" in out
        and "Standup (moved)" in out
    )
    assert "Cancelled thing" not in out

    out = (await tool.execute(action="free", day="2026-09-23", minutes=60)).output
    assert "09:00–11:00" in out and "11:30–15:00" in out and "16:00–18:00" in out
    assert "All-day" not in out
    # an all-day event does not block hours, but the model is told the user may be away
    out = (await tool.execute(action="free", day="2026-09-25", minutes=60)).output
    assert "All-day that day: 公司团建" in out

    out = (await tool.execute(action="search", query="团建")).output
    assert "公司团建" in out and "all day" in out

    result = await tool.execute(
        action="draft",
        title="Dentist",
        start="2026-10-03 14:00",
        duration_minutes=45,
        location="Nanjing Rd",
        notes="bring the card",
    )
    assert result.ok and "calendar/2026-10-03-dentist.ics" in result.output
    [ev] = parse_ics((ws / "calendar" / "2026-10-03-dentist.ics").read_text(), TZ)
    assert (
        ev.summary == "Dentist"
        and ev.duration == timedelta(minutes=45)
        and ev.location == "Nanjing Rd"
    )

    result = await tool.execute(action="draft", title="Trip", start="2026-10-01", end="2026-10-03")
    assert result.ok
    [ev] = parse_ics((ws / "calendar" / "2026-10-01-trip.ics").read_text(), TZ)
    assert ev.all_day and ev.duration == timedelta(days=3), "an all-day range is inclusive"

    # a model that HTML-escapes its arguments does not put "&amp;" on the calendar
    result = await tool.execute(
        action="draft", title="1:1 — Alex &amp; Alice", start="2026-10-04 14:00", location="3&#39;F"
    )
    assert result.ok and "Alex & Alice" in result.output
    [ev] = parse_ics((ws / "calendar" / "2026-10-04-1-1-alex-alice.ics").read_text(), TZ)
    assert ev.summary == "1:1 — Alex & Alice" and ev.location == "3'F"

    assert (await tool.execute(action="draft", title="", start="2026-10-01")).error
    assert (await tool.execute(action="agenda", day="not a day")).error

    off = Calendar(feeds=CalendarFeeds(settings_for(enabled=False), tz=TZ), workspace=ws)
    assert "no calendar is connected" in (await off.execute(action="agenda")).error
