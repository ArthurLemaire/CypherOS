import { describe, expect, it } from "vitest";
import { parseIcs } from "./FileViewer";

const ICS = [
  "BEGIN:VCALENDAR",
  "VERSION:2.0",
  "BEGIN:VEVENT",
  "UID:1@openmuse",
  "DTSTART:20260924T060000Z",
  "DTEND:20260924T064500Z",
  "SUMMARY:1:1 — Alex & Alice",
  "LOCATION:3楼小会议室",
  "DESCRIPTION:Suggested agenda:\\n- 近期进展 / 卡点\\n- 目标与优先",
  " 级\\, 反馈",
  "END:VEVENT",
  "BEGIN:VEVENT",
  "UID:2@openmuse",
  "DTSTART;VALUE=DATE:20261001",
  "DTEND;VALUE=DATE:20261004",
  "SUMMARY:Trip",
  "END:VEVENT",
  "END:VCALENDAR",
].join("\r\n");

describe("parseIcs", () => {
  it("reads the events the agent drafts: folded lines, escapes, UTC and all-day", () => {
    const [meeting, trip] = parseIcs(ICS);
    expect(meeting.summary).toBe("1:1 — Alex & Alice");
    expect(meeting.location).toBe("3楼小会议室");
    expect(meeting.description).toBe("Suggested agenda:\n- 近期进展 / 卡点\n- 目标与优先级, 反馈");
    expect(meeting.allDay).toBe(false);
    expect(meeting.start?.toISOString()).toBe("2026-09-24T06:00:00.000Z");
    expect(meeting.end?.toISOString()).toBe("2026-09-24T06:45:00.000Z");
    expect(trip.allDay).toBe(true);
    expect(trip.start?.getDate()).toBe(1);
    expect(trip.end?.getDate()).toBe(4);
  });

  it("is empty for a file without events", () => {
    expect(parseIcs("BEGIN:VCALENDAR\nEND:VCALENDAR\n")).toEqual([]);
  });
});
