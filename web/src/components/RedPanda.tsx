import { useId } from "react";
import { cx } from "../util";
import "./RedPanda.css";
import { BLUSH, BODY, EARS, EYES, HEAD, MASK_PATH, MOUTH_PATH, NOSE_PATH, PALETTE, PAWS, TAIL_PATH, TAIL_WIDTH } from "./redPandaShapes";

/**
 * The red panda: nanoMuse's own face. Meta's Muse gives its agent a plush doll that idles,
 * blinks and changes pose with what it is doing (at a laptop while it works); this is the
 * same idea drawn as an SVG, so it weighs nothing, scales to any size and can be posed.
 *
 * A mood sets the pose; the CSS in RedPanda.css sets the motion. Idle breathes, blinks and
 * glances about; working sits at a laptop and types; waiting raises a paw and holds up a
 * card; happy squints and bounces; sleepy shuts its eyes and floats z's; error droops its
 * ears and sweats. Nothing moves under prefers-reduced-motion, and `still` freezes the pose
 * for lists and pickers.
 *
 * The drawing has three levels of detail. `mark` is flat colour and the head's features
 * only, for 16–28 px where a gradient is noise; `avatar` adds the gradients, the sheen, the
 * blush and the tail; `hero` adds the finer touches for 160 px and up. Left unset, the size
 * picks it. The geometry lives in redPandaShapes.ts and is shared with the logo.
 */
export type Mood = "idle" | "working" | "waiting" | "happy" | "sleepy" | "error";
export type Detail = "mark" | "avatar" | "hero";

export function detailFor(size: number): Detail {
  return size <= 28 ? "mark" : size >= 160 ? "hero" : "avatar";
}

const { fur, furLight, furDeep, furDark, cream, creamLight, creamDeep, dark, eyeLight, blush } = PALETTE;

export function RedPanda({
  mood = "idle",
  size = 48,
  still = false,
  bg = PALETTE.plate,
  detail,
  className,
}: {
  mood?: Mood;
  size?: number;
  /** no motion at all (lists, pickers, the README) */
  still?: boolean;
  /** the circle behind it; "none" for transparent */
  bg?: string;
  /** level of detail; by default the size decides */
  detail?: Detail;
  className?: string;
}) {
  const lod = detail ?? detailFor(size);
  const flat = lod === "mark";
  const rich = lod === "hero";
  // Gradient ids must be unique per instance: several pandas share one document, and a
  // `url(#…)` finds the first match. useId may contain characters a fragment dislikes.
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const id = (name: string) => `rp${uid}-${name}`;
  const paint = (name: string, fallback: string) => (flat ? fallback : `url(#${id(name)})`);

  const eyeR = mood === "waiting" ? 14 : 13;

  return (
    <svg
      viewBox="0 0 200 200"
      width={size}
      height={size}
      className={cx("rp", `rp-${mood}`, `rp-${lod}`, still && "rp-still", className)}
      aria-hidden="true"
      focusable="false"
    >
      {!flat && (
        <defs>
          <radialGradient id={id("fur")} cx="40%" cy="32%" r="78%">
            <stop offset="0" stopColor={furLight} />
            <stop offset="0.45" stopColor={fur} />
            <stop offset="1" stopColor={furDeep} />
          </radialGradient>
          <radialGradient id={id("body")} cx="50%" cy="15%" r="85%">
            <stop offset="0" stopColor={furDeep} />
            <stop offset="1" stopColor={furDark} />
          </radialGradient>
          <radialGradient id={id("cream")} cx="50%" cy="38%" r="72%">
            <stop offset="0" stopColor={creamLight} />
            <stop offset="0.7" stopColor={cream} />
            <stop offset="1" stopColor={creamDeep} />
          </radialGradient>
          <radialGradient id={id("eye")} cx="50%" cy="62%" r="60%">
            <stop offset="0" stopColor={eyeLight} />
            <stop offset="1" stopColor={dark} />
          </radialGradient>
          <radialGradient id={id("shade")} cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor={dark} stopOpacity="0.32" />
            <stop offset="1" stopColor={dark} stopOpacity="0" />
          </radialGradient>
          <radialGradient id={id("sheen")} cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="#ffffff" stopOpacity="0.38" />
            <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
          </radialGradient>
          <clipPath id={id("plate")}>
            {bg !== "none" ? <circle cx="100" cy="100" r="100" /> : <rect x="0" y="0" width="200" height="200" />}
          </clipPath>
          <clipPath id={id("head")}>
            <ellipse cx={HEAD.cx} cy={HEAD.cy} rx={HEAD.rx} ry={HEAD.ry} />
          </clipPath>
        </defs>
      )}

      {bg !== "none" && <circle cx="100" cy="100" r="100" fill={bg} />}

      <g className="rp-all" clipPath={flat ? undefined : `url(#${id("plate")})`}>
        {/* tail, behind everything: fur with dark rings */}
        {!flat && (
          <g className="rp-tail">
            <path d={TAIL_PATH} fill="none" stroke={fur} strokeWidth={TAIL_WIDTH} strokeLinecap="round" />
            <path
              d={TAIL_PATH}
              fill="none"
              stroke={dark}
              strokeWidth={TAIL_WIDTH}
              strokeLinecap="butt"
              strokeDasharray={rich ? "10 14" : "12 16"}
              strokeDashoffset="6"
              opacity="0.6"
            />
          </g>
        )}

        {/* body, and the shadow the head throws on it */}
        {!flat && (
          <>
            <ellipse cx={BODY.cx} cy={BODY.cy} rx={BODY.rx} ry={BODY.ry} fill={paint("body", furDeep)} />
            <ellipse cx="100" cy="166" rx="56" ry="13" fill={paint("shade", dark)} opacity={flat ? 0.2 : 1} />
          </>
        )}

        {/* paws at rest */}
        {!flat && mood !== "working" && mood !== "waiting" && (
          <>
            <ellipse className="rp-paw-l" cx={PAWS[0].cx} cy={PAWS[0].cy} rx={PAWS[0].rx} ry={PAWS[0].ry} fill={dark} />
            <ellipse className="rp-paw-r" cx={PAWS[1].cx} cy={PAWS[1].cy} rx={PAWS[1].rx} ry={PAWS[1].ry} fill={dark} />
          </>
        )}
        {!flat && mood === "waiting" && (
          <ellipse className="rp-paw-l" cx={PAWS[0].cx} cy={PAWS[0].cy} rx={PAWS[0].rx} ry={PAWS[0].ry} fill={dark} />
        )}

        {/* the mark is the head alone, scaled up to fill the box */}
        <g transform={flat ? "translate(100 100) scale(1.24) translate(-100 -97)" : undefined}>
        <g className="rp-head">
          {/* round ears, cream inside */}
          {EARS.map((ear, i) => (
            <g key={i} className={cx("rp-ear", i === 0 ? "rp-ear-l" : "rp-ear-r")}>
              <circle cx={ear.outer.cx} cy={ear.outer.cy} r={ear.outer.r} fill={flat ? furDeep : paint("fur", fur)} />
              {flat && <circle cx={ear.outer.cx} cy={ear.outer.cy} r={ear.outer.r - 4} fill={fur} />}
              <circle cx={ear.inner.cx} cy={ear.inner.cy} r={ear.inner.r} fill={paint("cream", cream)} />
              {rich && <circle cx={ear.inner.cx} cy={ear.inner.cy + 3} r={ear.inner.r - 5} fill={blush} opacity="0.35" />}
            </g>
          ))}

          {/* head and the cream face */}
          <ellipse cx={HEAD.cx} cy={HEAD.cy} rx={HEAD.rx} ry={HEAD.ry} fill={paint("fur", fur)} />
          <path d={MASK_PATH} fill={paint("cream", cream)} />
          {!flat && (
            <ellipse
              className="rp-sheen"
              cx="72"
              cy="62"
              rx="36"
              ry="15"
              transform="rotate(-18 72 62)"
              fill={`url(#${id("sheen")})`}
              clipPath={`url(#${id("head")})`}
            />
          )}

          {/* blush */}
          {!flat &&
            BLUSH.map((b, i) => (
              <ellipse key={i} cx={b.cx} cy={b.cy} rx={b.rx} ry={b.ry} fill={blush} opacity={mood === "happy" ? 0.9 : 0.6} />
            ))}

          {/* eyes */}
          <g className="rp-eyes">
            {mood === "happy" ? (
              <>
                <path d="M60 110 Q72 96 84 110" fill="none" stroke={dark} strokeWidth="6" strokeLinecap="round" />
                <path d="M116 110 Q128 96 140 110" fill="none" stroke={dark} strokeWidth="6" strokeLinecap="round" />
              </>
            ) : mood === "sleepy" ? (
              <>
                <path d="M61 107 Q72 116 83 107" fill="none" stroke={dark} strokeWidth="5" strokeLinecap="round" />
                <path d="M117 107 Q128 116 139 107" fill="none" stroke={dark} strokeWidth="5" strokeLinecap="round" />
              </>
            ) : (
              EYES.map((e, i) => (
                <g key={i} className="rp-eye">
                  <g className="rp-blink">
                    <circle cx={e.eye.cx} cy={e.eye.cy} r={eyeR} fill={paint("eye", dark)} />
                    <circle cx={e.highlight.cx} cy={e.highlight.cy} r={flat ? 4.6 : e.highlight.r} fill="#ffffff" />
                  </g>
                </g>
              ))
            )}
          </g>
          {mood === "error" && (
            <>
              <path d="M58 90 L82 86" fill="none" stroke={dark} strokeWidth="4" strokeLinecap="round" />
              <path d="M142 90 L118 86" fill="none" stroke={dark} strokeWidth="4" strokeLinecap="round" />
            </>
          )}

          {/* nose and mouth */}
          <path d={NOSE_PATH} fill={dark} />
          {mood === "happy" ? (
            <>
              <path d="M88 141 Q100 158 112 141 Z" fill={dark} />
              <path d="M94 148 Q100 155 106 148 Z" fill="#f28c8c" />
            </>
          ) : mood === "waiting" ? (
            <path d="M100 139 V142 M96 147 a4 4 0 1 0 8 0 a4 4 0 1 0 -8 0" fill="none" stroke={dark} strokeWidth="3.2" strokeLinecap="round" />
          ) : mood === "error" ? (
            <path d="M100 139 V142 M91 147 Q95.5 141 100 147 T109 147" fill="none" stroke={dark} strokeWidth="3.2" strokeLinecap="round" />
          ) : mood === "sleepy" ? (
            <path d="M100 139 V142 M95 146 Q100 150 105 146" fill="none" stroke={dark} strokeWidth="3.2" strokeLinecap="round" />
          ) : (
            <path d={MOUTH_PATH} fill="none" stroke={dark} strokeWidth={flat ? 4 : 3.2} strokeLinecap="round" strokeLinejoin="round" />
          )}
        </g>
        </g>

        {/* the laptop it works at, and paws on the keys */}
        {!flat && mood === "working" && (
          <g className="rp-laptop">
            <rect x="50" y="156" width="100" height="60" rx="10" fill="#3b3f47" />
            <rect x="58" y="164" width="84" height="46" rx="6" fill="#2b2f36" />
            <circle cx="100" cy="186" r="5" fill={cream} opacity="0.35" />
            <ellipse className="rp-paw-l rp-typing" cx="70" cy="158" rx="14" ry="10" fill={dark} />
            <ellipse className="rp-paw-r rp-typing" cx="130" cy="158" rx="14" ry="10" fill={dark} />
          </g>
        )}

        {/* a raised paw, and the card it holds up */}
        {!flat && mood === "waiting" && (
          <g className="rp-raise">
            <path d="M148 180 Q158 152 156 134" fill="none" stroke={dark} strokeWidth="18" strokeLinecap="round" />
            <ellipse cx="156" cy="130" rx="14" ry="12" fill={dark} />
            <g className="rp-bang">
              <circle cx="166" cy="50" r="18" fill="#ffffff" stroke="#e5e7eb" strokeWidth="2" />
              <text x="166" y="59" textAnchor="middle" fontSize="26" fontWeight="800" fill="#0064d4" fontFamily="Figtree, system-ui, sans-serif">
                !
              </text>
            </g>
          </g>
        )}

        {!flat && mood === "happy" && (
          <g className="rp-sparkles">
            <path className="rp-spark" d="M36 44 Q37 56 48 58 Q37 60 36 72 Q35 60 24 58 Q35 56 36 44 Z" fill="#f5b400" />
            <path className="rp-spark rp-spark-2" d="M168 36 Q169 45 177 46 Q169 47 168 56 Q167 47 159 46 Q167 45 168 36 Z" fill="#f5b400" />
          </g>
        )}

        {!flat && mood === "sleepy" && (
          <g className="rp-zs" fill="#6b7280" fontFamily="Figtree, system-ui, sans-serif" fontWeight="700">
            <text className="rp-z" x="168" y="94" fontSize="18">
              z
            </text>
            <text className="rp-z rp-z-2" x="178" y="80" fontSize="14">
              z
            </text>
            <text className="rp-z rp-z-3" x="185" y="68" fontSize="11">
              z
            </text>
          </g>
        )}

        {!flat && mood === "error" && <path className="rp-drop" d="M160 62 Q170 76 160 86 Q150 76 160 62 Z" fill="#8ec5ff" />}
      </g>
    </svg>
  );
}
