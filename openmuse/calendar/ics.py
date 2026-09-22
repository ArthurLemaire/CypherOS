"""A small iCalendar (RFC 5545) reader: the events in a feed, expanded over a window.

Every calendar people use can hand out a private ``.ics`` link — Google, Outlook, iCloud,
Fastmail, Nextcloud — and reading one needs no OAuth dance, which is why this is the
connector. What is read: VEVENT summary, times (with TZID, UTC and all-day forms),
location, description, RRULE with EXDATE and RECURRENCE-ID overrides, CANCELLED status.
What is not: VTODO, VJOURNAL, alarms, attendees.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rruleset, rrulestr

_LINE_RE = re.compile(r"^(?P<name>[A-Za-z0-9-]+)(?P<params>(?:;[^:]*)?):(?P<value>.*)$", re.S)
_DURATION_RE = re.compile(
    r"^(?P<sign>[+-])?P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
# Windows / Outlook time zone names, the ones that show up in real feeds.
_TZ_ALIASES = {
    "china standard time": "Asia/Shanghai",
    "tokyo standard time": "Asia/Tokyo",
    "pacific standard time": "America/Los_Angeles",
    "eastern standard time": "America/New_York",
    "central standard time": "America/Chicago",
    "mountain standard time": "America/Denver",
    "gmt standard time": "Europe/London",
    "w. europe standard time": "Europe/Berlin",
    "central europe standard time": "Europe/Budapest",
    "romance standard time": "Europe/Paris",
    "india standard time": "Asia/Kolkata",
    "singapore standard time": "Asia/Singapore",
    "aus eastern standard time": "Australia/Sydney",
    "utc": "UTC",
    "z": "UTC",
}


@dataclass
class Event:
    """One event as written in the feed (a recurring one is one Event with a rule)."""

    uid: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str = ""
    description: str = ""
    rrule: str = ""
    exdates: list[datetime] = field(default_factory=list)
    recurrence_id: datetime | None = None  # this VEVENT replaces one occurrence of ``uid``
    calendar: str = ""
    cancelled: bool = False

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


@dataclass(order=True)
class Occurrence:
    """An event on a particular day: what the agenda is made of."""

    start: datetime
    end: datetime
    summary: str = field(compare=False)
    all_day: bool = field(default=False, compare=False)
    location: str = field(default="", compare=False)
    description: str = field(default="", compare=False)
    calendar: str = field(default="", compare=False)
    uid: str = field(default="", compare=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "uid": self.uid,
            "summary": self.summary,
            "start": self.start.isoformat(timespec="minutes"),
            "end": self.end.isoformat(timespec="minutes"),
            "all_day": self.all_day,
            "location": self.location,
            "description": self.description,
            "calendar": self.calendar,
        }


# ---------------------------------------------------------------------------- parsing
def unfold(text: str) -> list[str]:
    """Content lines: a line that starts with a space or tab continues the one before."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def unescape(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _params(raw: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for part in raw.lstrip(";").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.upper()] = v.strip('"')
    return params


def zone(name: str | None, default: tzinfo) -> tzinfo:
    """The tzinfo for a TZID, falling back to ``default`` for names we cannot place."""
    if not name:
        return default
    alias = _TZ_ALIASES.get(name.strip().lower())
    for candidate in (alias, name, name.split("/", 1)[-1] if "/" in name else None):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return default


def parse_dt(value: str, params: dict[str, str], default_tz: tzinfo) -> tuple[datetime, bool]:
    """An iCalendar DATE or DATE-TIME → (aware datetime, is_date).

    Floating times (no Z, no TZID) are read in ``default_tz`` — the user's zone — which is
    what every calendar app does with them too.
    """
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        d = datetime.strptime(value, "%Y%m%d")
        return d.replace(tzinfo=default_tz), True
    utc = value.endswith("Z")
    core = value[:-1] if utc else value
    dt = datetime.strptime(core[:15], "%Y%m%dT%H%M%S")
    if utc:
        return dt.replace(tzinfo=ZoneInfo("UTC")), False
    return dt.replace(tzinfo=zone(params.get("TZID"), default_tz)), False


def parse_duration(value: str) -> timedelta:
    m = _DURATION_RE.match(value.strip())
    if not m:
        raise ValueError(f"bad DURATION: {value!r}")
    g = {k: int(v) for k, v in m.groupdict().items() if v and k != "sign"}
    delta = timedelta(
        weeks=g.get("weeks", 0),
        days=g.get("days", 0),
        hours=g.get("hours", 0),
        minutes=g.get("minutes", 0),
        seconds=g.get("seconds", 0),
    )
    return -delta if m.group("sign") == "-" else delta


def parse_ics(text: str, default_tz: tzinfo, calendar: str = "") -> list[Event]:
    """The VEVENTs in ``text``. Malformed events are skipped, not fatal."""
    events: list[Event] = []
    props: list[tuple[str, dict[str, str], str]] | None = None
    depth = 0  # nesting inside a VEVENT (VALARM is a child component we ignore)
    for line in unfold(text):
        m = _LINE_RE.match(line)
        if not m:
            continue
        name, params, value = m.group("name").upper(), _params(m.group("params")), m.group("value")
        if name == "BEGIN":
            if value.upper() == "VEVENT" and props is None:
                props = []
            elif props is not None:
                depth += 1
            continue
        if name == "END":
            if props is not None and depth:
                depth -= 1
            elif value.upper() == "VEVENT" and props is not None:
                ev = _event(props, default_tz, calendar)
                if ev is not None:
                    events.append(ev)
                props = None
            continue
        if props is not None and not depth:
            props.append((name, params, value))
    return events


def _event(props: list[tuple[str, dict[str, str], str]], tz: tzinfo, calendar: str) -> Event | None:
    fields: dict[str, tuple[dict[str, str], str]] = {}
    exdates: list[datetime] = []
    for name, params, value in props:
        if name == "EXDATE":
            for part in value.split(","):
                try:
                    exdates.append(parse_dt(part, params, tz)[0])
                except ValueError:
                    continue
        else:
            fields.setdefault(name, (params, value))
    if "DTSTART" not in fields:
        return None
    try:
        start, all_day = parse_dt(fields["DTSTART"][1], fields["DTSTART"][0], tz)
        if "DTEND" in fields:
            end, _ = parse_dt(fields["DTEND"][1], fields["DTEND"][0], tz)
        elif "DURATION" in fields:
            end = start + parse_duration(fields["DURATION"][1])
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(0))
        if end < start:
            end = start
        rec_id = None
        if "RECURRENCE-ID" in fields:
            rec_id = parse_dt(fields["RECURRENCE-ID"][1], fields["RECURRENCE-ID"][0], tz)[0]
    except ValueError:
        return None
    text = lambda key: unescape(fields[key][1]).strip() if key in fields else ""  # noqa: E731
    return Event(
        uid=text("UID") or f"{start.isoformat()}-{text('SUMMARY')}",
        summary=text("SUMMARY") or "(untitled)",
        start=start,
        end=end,
        all_day=all_day,
        location=text("LOCATION"),
        description=text("DESCRIPTION"),
        rrule=fields["RRULE"][1].strip() if "RRULE" in fields else "",
        exdates=exdates,
        recurrence_id=rec_id,
        calendar=calendar,
        cancelled=text("STATUS").upper() == "CANCELLED",
    )


# ---------------------------------------------------------------------------- expansion
def _same_moment(a: datetime, b: datetime, all_day: bool) -> bool:
    if all_day:
        return a.date() == b.date()
    return abs((a - b).total_seconds()) < 60


def expand(events: list[Event], start: datetime, end: datetime) -> list[Occurrence]:
    """Every occurrence that overlaps [start, end), recurring rules unrolled, overrides
    applied, cancelled ones left out — sorted by start."""
    overrides: dict[str, list[Event]] = {}
    for ev in events:
        if ev.recurrence_id is not None:
            overrides.setdefault(ev.uid, []).append(ev)
    out: list[Occurrence] = []
    for ev in events:
        if ev.recurrence_id is not None:
            if not ev.cancelled and ev.start < end and ev.end > start:
                out.append(_occurrence(ev, ev.start, ev.end))
            continue
        if ev.cancelled:
            continue
        replaced = overrides.get(ev.uid, [])
        for occ_start in _starts(ev, start, end):
            if any(
                _same_moment(o.recurrence_id, occ_start, ev.all_day)
                for o in replaced
                if o.recurrence_id
            ):
                continue
            occ_end = occ_start + ev.duration
            if occ_start < end and occ_end > start:
                out.append(_occurrence(ev, occ_start, occ_end))
    out.sort()
    return out


def _occurrence(ev: Event, start: datetime, end: datetime) -> Occurrence:
    return Occurrence(
        start=start,
        end=end,
        summary=ev.summary,
        all_day=ev.all_day,
        location=ev.location,
        description=ev.description,
        calendar=ev.calendar,
        uid=ev.uid,
    )


def _starts(ev: Event, start: datetime, end: datetime) -> list[datetime]:
    if not ev.rrule:
        return [ev.start]
    # Occurrences that begin before the window but run into it still count.
    lookback = max(ev.duration, timedelta(0))
    try:
        rule = rrulestr(_rrule_for(ev), dtstart=ev.start)
    except (ValueError, TypeError):
        return [ev.start]
    rules = rruleset()
    rules.rrule(rule)  # type: ignore[arg-type]
    for ex in ev.exdates:
        rules.exdate(ex if not ev.all_day else ex.replace(tzinfo=ev.start.tzinfo))
    try:
        return list(rules.between(start - lookback, end, inc=True))
    except (ValueError, TypeError):
        return [ev.start]


def _rrule_for(ev: Event) -> str:
    """The RRULE with an UNTIL that dateutil accepts next to an aware dtstart."""
    rule = ev.rrule if ev.rrule.upper().startswith("RRULE:") else f"RRULE:{ev.rrule}"
    m = re.search(r"UNTIL=(\d{8}(?:T\d{6}Z?)?)", rule)
    if m:
        raw = m.group(1)
        if len(raw) == 8:
            # a date-only UNTIL: the end of that day in the event's zone
            until = datetime.combine(
                datetime.strptime(raw, "%Y%m%d").date(), time(23, 59, 59), tzinfo=ev.start.tzinfo
            )
        elif raw.endswith("Z"):
            until = datetime.strptime(raw[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo("UTC"))
        else:
            until = datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(tzinfo=ev.start.tzinfo)
        until = until.astimezone(ZoneInfo("UTC"))
        rule = rule.replace(m.group(0), "UNTIL=" + until.strftime("%Y%m%dT%H%M%SZ"))
    return rule


# ---------------------------------------------------------------------------- writing
def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Content lines are at most 75 octets; longer ones continue on the next line with a space."""
    out: list[str] = []
    data = line.encode("utf-8")
    while len(data) > 74:
        cut = 74
        while cut > 0 and (data[cut] & 0xC0) == 0x80:  # do not split a UTF-8 sequence
            cut -= 1
        out.append(data[:cut].decode("utf-8"))
        data = b" " + data[cut:]
    out.append(data.decode("utf-8"))
    return "\r\n".join(out)


def make_ics(
    summary: str,
    start: datetime,
    end: datetime,
    *,
    all_day: bool = False,
    location: str = "",
    description: str = "",
    uid: str = "",
) -> str:
    """One VEVENT as a file a phone or desktop calendar can import."""
    now = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    uid = uid or f"{now}-{abs(hash((summary, start.isoformat()))) % 10**8:08d}@openmuse"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//OpenMuse//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
    ]
    if all_day:
        lines.append(f"DTSTART;VALUE=DATE:{start:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{end:%Y%m%d}")
    else:
        for name, dt in (("DTSTART", start), ("DTEND", end)):
            if dt.tzinfo is None:
                lines.append(f"{name}:{dt:%Y%m%dT%H%M%S}")
            else:
                lines.append(f"{name}:{dt.astimezone(ZoneInfo('UTC')):%Y%m%dT%H%M%SZ}")
    lines.append(f"SUMMARY:{_escape(summary)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def day_bounds(day: date, tz: tzinfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


__all__ = [
    "Event",
    "Occurrence",
    "day_bounds",
    "expand",
    "make_ics",
    "parse_dt",
    "parse_duration",
    "parse_ics",
    "unescape",
    "unfold",
    "zone",
]
