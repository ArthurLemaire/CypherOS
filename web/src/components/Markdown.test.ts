import { describe, expect, it } from "vitest";
import { matchFile } from "./Markdown";

const files = ["kyoto-notes/packing-list.html", "notes/plan.md", "reports/plan.md", "budget.csv"];

describe("matchFile", () => {
  it("accepts the workspace path, with or without a leading ./", () => {
    expect(matchFile("kyoto-notes/packing-list.html", files)).toBe("kyoto-notes/packing-list.html");
    expect(matchFile("./budget.csv", files)).toBe("budget.csv");
    expect(matchFile("/budget.csv", files)).toBe("budget.csv");
  });

  it("accepts a bare file name only when it names one file", () => {
    expect(matchFile("packing-list.html", files)).toBe("kyoto-notes/packing-list.html");
    expect(matchFile("plan.md", files)).toBeNull(); // notes/plan.md or reports/plan.md?
    expect(matchFile("reports/plan.md", files)).toBe("reports/plan.md");
  });

  it("leaves ordinary code alone", () => {
    expect(matchFile("git status", files)).toBeNull();
    expect(matchFile("list.html", files)).toBeNull(); // not a suffix at a path boundary
    expect(matchFile("", files)).toBeNull();
    expect(matchFile("budget.csv", [])).toBeNull();
  });
});
