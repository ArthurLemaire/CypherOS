import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cx, fileKind, relativeTime, timeShort, truncate } from "./util";

describe("relativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-22T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("reads the past", () => {
    expect(relativeTime("2026-09-22T11:59:50Z")).toBe("just now");
    expect(relativeTime("2026-09-22T11:57:00Z")).toBe("3 min ago");
    expect(relativeTime("2026-09-22T09:00:00Z")).toBe("3 h ago");
    expect(relativeTime("2026-09-13T12:00:00Z")).toBe("9 d ago");
  });

  it("reads the future", () => {
    expect(relativeTime("2026-09-22T12:00:20Z")).toBe("any moment");
    expect(relativeTime("2026-09-22T14:00:00Z")).toBe("in 2 h");
    expect(relativeTime("2026-10-01T12:00:00Z")).toBe("in 9 d");
  });

  it("is empty for nothing and for garbage", () => {
    expect(relativeTime(null)).toBe("");
    expect(relativeTime(undefined)).toBe("");
    expect(relativeTime("not a date")).toBe("");
  });
});

describe("timeShort", () => {
  it("shows only the time for today and adds the day otherwise", () => {
    const today = new Date();
    today.setHours(9, 5, 0, 0);
    const clock = today.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    expect(timeShort(today.toISOString())).toBe(clock);
    // locale-agnostic: an older date carries a day part in front of the clock
    const old = timeShort("2020-01-15T09:05:00Z");
    expect(old.length).toBeGreaterThan(clock.length);
    expect(old).toMatch(/15|14/);
    expect(timeShort(undefined)).toBe("");
    expect(timeShort("nope")).toBe("");
  });
});

describe("cx and truncate", () => {
  it("joins the truthy classes", () => {
    expect(cx("a", false, null, undefined, "b")).toBe("a b");
  });
  it("truncates with an ellipsis inside the budget", () => {
    expect(truncate("hello", 10)).toBe("hello");
    expect(truncate("hello world", 6)).toBe("hello…");
    expect(truncate("hello world", 6)).toHaveLength(6);
  });
});

describe("fileKind", () => {
  it("classifies by extension, case-insensitively", () => {
    expect(fileKind("notes.md")).toBe("text");
    expect(fileKind("script.PY")).toBe("code");
    expect(fileKind("itinerary.html")).toBe("html");
    expect(fileKind("photo.JPEG")).toBe("image");
    expect(fileKind("report.pdf")).toBe("pdf");
    expect(fileKind("budget.csv")).toBe("data");
    expect(fileKind("archive.zip")).toBe("other");
    expect(fileKind("Makefile")).toBe("other");
  });
});
