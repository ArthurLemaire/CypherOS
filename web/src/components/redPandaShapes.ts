/**
 * The red panda's geometry, in the 200×200 box of RedPanda.tsx. One list of shapes feeds the
 * live component, the flat logo (icon.svg, mark.svg, the Android launcher) and the site's
 * static copies, so none of them can drift from the others.
 *
 * v2 (September 2026): round ears, one cream mask with a widow's peak, larger and lower eyes
 * with a single highlight, a small nose and an ω mouth. The tear marks, brow spots and the
 * second highlight of v1 are gone; volume comes from four radial gradients and a crown sheen
 * rather than from more shapes.
 */

export const PALETTE = {
  fur: "#d8632e",
  furLight: "#ee8a4c",
  furDeep: "#bf4f23",
  furDark: "#9e3f18",
  cream: "#fff4e6",
  creamLight: "#fffaf2",
  creamDeep: "#f3dfc6",
  dark: "#2a1a14",
  eyeLight: "#4a302a",
  blush: "#f4a0a0",
  /** the circle behind it in the app */
  plate: "#dcebdc",
  /** the plate of the launcher icon */
  logoPlate: "#2f7a5a",
} as const;

export interface Ellipse {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}
export interface Circle {
  cx: number;
  cy: number;
  r: number;
}

export const HEAD: Ellipse = { cx: 100, cy: 104, rx: 70, ry: 62 };

/** Round ears; the head is drawn over their lower half. `inner` is the cream inside. */
export const EARS: { outer: Circle; inner: Circle }[] = [
  { outer: { cx: 50, cy: 52, r: 24 }, inner: { cx: 51, cy: 53, r: 14 } },
  { outer: { cx: 150, cy: 52, r: 24 }, inner: { cx: 149, cy: 53, r: 14 } },
];

/**
 * The cream face: two round cheeks and the muzzle as one shape. It rises over each eye and
 * dips between them to a peak below the eye line — the red panda's widow's peak — and its
 * lower half follows the jaw a few units inside the head so a rim of fur stays visible at
 * the sides and the chin.
 */
export const MASK_PATH =
  "M38 118C38 96 52 84 66 84C82 84 94 98 100 112C106 98 118 84 134 84C148 84 162 96 162 118" +
  "C162 142.3 134.2 162 100 162C65.8 162 38 142.3 38 118Z";

/** Eyes at 53 % of the head's height, one highlight each, top-right. */
export const EYES: { eye: Circle; highlight: Circle }[] = [
  { eye: { cx: 72, cy: 108, r: 13 }, highlight: { cx: 76.5, cy: 103, r: 4.2 } },
  { eye: { cx: 128, cy: 108, r: 13 }, highlight: { cx: 132.5, cy: 103, r: 4.2 } },
];

export const NOSE_PATH = "M93 128Q100 123 107 128Q104.5 137 100 139Q95.5 137 93 128Z";
/** A short line down from the nose, then the ω. */
export const MOUTH_PATH = "M100 139V142M91 142Q95.5 149 100 142Q104.5 149 109 142";

export const BLUSH: Ellipse[] = [
  { cx: 56, cy: 134, rx: 10, ry: 6 },
  { cx: 144, cy: 134, rx: 10, ry: 6 },
];

export const BODY: Ellipse = { cx: 100, cy: 196, rx: 58, ry: 48 };
export const PAWS: Ellipse[] = [
  { cx: 66, cy: 186, rx: 15, ry: 10 },
  { cx: 134, cy: 186, rx: 15, ry: 10 },
];
export const TAIL_PATH = "M142 198Q178 190 186 150Q190 132 180 122";
export const TAIL_WIDTH = 24;

/** Where the head, with its ears, sits: the box the logo crops to. */
export const HEAD_BOX = { x: 26, y: 28, width: 148, height: 138 };

/** An ellipse as a path (two arcs), for files that want paths only. */
export function ellipsePath({ cx, cy, rx, ry }: Ellipse, clockwise = true): string {
  const sweep = clockwise ? 1 : 0;
  return `M${cx - rx} ${cy}a${rx} ${ry} 0 1 ${sweep} ${rx * 2} 0a${rx} ${ry} 0 1 ${sweep} ${-rx * 2} 0z`;
}
export function circlePath({ cx, cy, r }: Circle, clockwise = true): string {
  return ellipsePath({ cx, cy, rx: r, ry: r }, clockwise);
}

export interface FlatShape {
  d: string;
  fill: string;
}

/**
 * The head alone in flat colour — the logo. Ears, head, mask, eyes, highlights, nose, mouth;
 * the mouth as a filled sliver so the list is fills only (vector drawables have no strokes worth
 * relying on at 48 dp).
 */
export function flatHead(): FlatShape[] {
  const { fur, furDeep, cream, dark } = PALETTE;
  const out: FlatShape[] = [];
  for (const ear of EARS) out.push({ d: circlePath(ear.outer), fill: furDeep });
  for (const ear of EARS) out.push({ d: circlePath({ ...ear.outer, r: ear.outer.r - 4 }), fill: fur });
  for (const ear of EARS) out.push({ d: circlePath(ear.inner), fill: cream });
  out.push({ d: ellipsePath(HEAD), fill: fur });
  out.push({ d: MASK_PATH, fill: cream });
  for (const e of EYES) out.push({ d: circlePath(e.eye), fill: dark });
  for (const e of EYES) out.push({ d: circlePath(e.highlight), fill: "#ffffff" });
  out.push({ d: NOSE_PATH, fill: dark });
  out.push({ d: MOUTH_FILLED_PATH, fill: dark });
  return out;
}

/**
 * The ω mouth as closed shapes (a band 3.2 wide, and the stub under the nose), for formats
 * that fill only. Wound clockwise, like every other shape here.
 */
export const MOUTH_FILLED_PATH =
  "M98.4 138.5h3.2v3.5h-3.2z" +
  "M91 140.4Q95.5 147.4 100 140.4Q104.5 147.4 109 140.4L109 143.6Q104.5 150.6 100 143.6Q95.5 150.6 91 143.6Z";

/**
 * The silhouette for Android's monochrome (themed) icon: head and ears as one filled shape,
 * eyes, nose and mouth punched out. Sub-paths wound the other way become holes under the
 * non-zero rule.
 */
export function monochromeHead(): string {
  const holes = [...EYES.map((e) => circlePath(e.eye, false)), NOSE_PATH_CCW, MOUTH_FILLED_PATH_CCW];
  return [...EARS.map((e) => circlePath(e.outer)), ellipsePath(HEAD), ...holes].join("");
}

/** The nose, traced counter-clockwise. */
const NOSE_PATH_CCW = "M93 128Q95.5 137 100 139Q104.5 137 107 128Q100 123 93 128Z";
/** The filled mouth, traced counter-clockwise. */
const MOUTH_FILLED_PATH_CCW =
  "M98.4 138.5v3.5h3.2v-3.5z" +
  "M91 143.6Q95.5 150.6 100 143.6Q104.5 150.6 109 143.6L109 140.4Q104.5 147.4 100 140.4Q95.5 147.4 91 140.4Z";
