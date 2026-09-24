import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { detailFor, RedPanda, type Detail, type Mood } from "./RedPanda";
import { EYES, flatHead, HEAD, monochromeHead, PALETTE } from "./redPandaShapes";

const moods: Mood[] = ["idle", "working", "waiting", "happy", "sleepy", "error"];
const details: Detail[] = ["mark", "avatar", "hero"];

const render = (props: Parameters<typeof RedPanda>[0]) => renderToStaticMarkup(createElement(RedPanda, props));

describe("RedPanda", () => {
  it("picks the level of detail from the size", () => {
    expect(detailFor(16)).toBe("mark");
    expect(detailFor(28)).toBe("mark");
    expect(detailFor(40)).toBe("avatar");
    expect(detailFor(159)).toBe("avatar");
    expect(detailFor(200)).toBe("hero");
  });

  it("draws every mood at every level, without filters", () => {
    for (const detail of details) {
      for (const mood of moods) {
        const svg = render({ mood, detail, size: 100 });
        expect(svg).toContain(`class="rp rp-${mood} rp-${detail}`);
        expect(svg).not.toContain("<filter");
      }
    }
  });

  it("is flat colour as a mark and shaded above it", () => {
    const mark = render({ mood: "idle", detail: "mark" });
    expect(mark).not.toContain("<radialGradient");
    expect(mark).not.toContain("url(#");
    const avatar = render({ mood: "idle", detail: "avatar" });
    expect(avatar).toContain("<radialGradient");
    expect(avatar).toMatch(/fill="url\(#rp[a-zA-Z0-9]*-fur\)"/);
  });

  it("gives each instance its own gradient ids", () => {
    const two = renderToStaticMarkup(
      createElement("div", null, createElement(RedPanda, { mood: "idle", size: 48 }), createElement(RedPanda, { mood: "working", size: 48 })),
    );
    const ids = [...two.matchAll(/<radialGradient id="([^"]+)"/g)].map((m) => m[1]);
    expect(ids.length).toBe(12);
    expect(new Set(ids).size).toBe(12);
    for (const id of ids) expect(id).toMatch(/^rp[a-zA-Z0-9]*-[a-z]+$/);
  });

  it("stays inside its plate, and has none when asked", () => {
    const withPlate = render({ mood: "idle", size: 200 });
    expect(withPlate).toContain(`fill="${PALETTE.plate}"`);
    expect(withPlate).toContain("<clipPath");
    const bare = render({ mood: "idle", size: 200, bg: "none" });
    expect(bare).not.toContain(`fill="${PALETTE.plate}"`);
  });

  it("freezes with still", () => {
    expect(render({ mood: "working", still: true })).toContain("rp-still");
    expect(render({ mood: "working" })).not.toContain("rp-still");
  });

  it("puts the eyes at 53 % of the head's height", () => {
    const top = HEAD.cy - HEAD.ry;
    for (const { eye } of EYES) expect((eye.cy - top) / (2 * HEAD.ry)).toBeCloseTo(0.53, 1);
  });
});

describe("the flat logo", () => {
  it("is the head's features in flat colour", () => {
    const shapes = flatHead();
    expect(shapes.length).toBe(14); // 3 rings × 2 ears, head, mask, 2 eyes, 2 highlights, nose, mouth
    for (const s of shapes) expect(s.fill).toMatch(/^#[0-9a-f]{6}$/);
    expect(shapes.some((s) => s.fill === PALETTE.cream)).toBe(true);
  });

  it("is a single silhouette with the face punched out", () => {
    const d = monochromeHead();
    expect(d.split("M").length - 1).toBe(8); // 2 ears + head, 2 eyes, nose, mouth stub + band
    expect(d).toMatchSnapshot();
  });

  it("matches the last approved drawing", () => {
    expect(flatHead()).toMatchSnapshot();
    expect(render({ mood: "idle", detail: "hero", size: 200, bg: "none" })).toMatchSnapshot();
  });
});
