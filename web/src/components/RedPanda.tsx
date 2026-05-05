import { cx } from "../util";
import "./RedPanda.css";

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
 */
export type Mood = "idle" | "working" | "waiting" | "happy" | "sleepy" | "error";

const RUST = "#d8632e";
const RUST_DEEP = "#bf4f23";
const CREAM = "#fff4e6";
const DARK = "#2a1a14";
const PAW = "#3a2721";
const TEAR = "#a8482a";
const BLUSH = "#f4a0a0";

export function RedPanda({
  mood = "idle",
  size = 48,
  still = false,
  bg = "#dcebdc",
  className,
}: {
  mood?: Mood;
  size?: number;
  /** no motion at all (lists, pickers, the README) */
  still?: boolean;
  /** the circle behind it; "none" for transparent */
  bg?: string;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 200 200"
      width={size}
      height={size}
      className={cx("rp", `rp-${mood}`, still && "rp-still", className)}
      aria-hidden="true"
      focusable="false"
    >
      {bg !== "none" && <circle cx="100" cy="100" r="100" fill={bg} />}

      <g className="rp-all">
        {/* tail, behind everything: rust with dark rings */}
        <g className="rp-tail">
          <path d="M150 200 Q178 190 186 150 Q190 128 178 118" fill="none" stroke={RUST} strokeWidth="26" strokeLinecap="round" />
          <path d="M150 200 Q178 190 186 150 Q190 128 178 118" fill="none" stroke={PAW} strokeWidth="26" strokeLinecap="butt" strokeDasharray="12 16" strokeDashoffset="4" opacity="0.9" />
        </g>

        {/* body */}
        <ellipse cx="100" cy="205" rx="66" ry="60" fill={RUST_DEEP} />
        <ellipse cx="100" cy="214" rx="36" ry="40" fill={PAW} opacity="0.35" />

        {/* paws at rest */}
        {mood !== "working" && mood !== "waiting" && (
          <>
            <ellipse className="rp-paw-l" cx="64" cy="188" rx="17" ry="12" fill={PAW} />
            <ellipse className="rp-paw-r" cx="136" cy="188" rx="17" ry="12" fill={PAW} />
          </>
        )}
        {mood === "waiting" && <ellipse className="rp-paw-l" cx="64" cy="188" rx="17" ry="12" fill={PAW} />}

        <g className="rp-head">
          {/* ears */}
          <g className="rp-ear rp-ear-l">
            <path d="M42 68 Q14 30 26 14 Q38 6 82 44 Z" fill={RUST} strokeLinejoin="round" />
            <path d="M46 62 Q30 38 34 26 Q42 20 72 46 Z" fill={CREAM} opacity="0.92" />
          </g>
          <g className="rp-ear rp-ear-r">
            <path d="M158 68 Q186 30 174 14 Q162 6 118 44 Z" fill={RUST} strokeLinejoin="round" />
            <path d="M154 62 Q170 38 166 26 Q158 20 128 46 Z" fill={CREAM} opacity="0.92" />
          </g>

          {/* head */}
          <ellipse cx="100" cy="100" rx="72" ry="62" fill={RUST} />
          {/* face markings: cheeks, muzzle, brow spots */}
          <ellipse cx="60" cy="124" rx="32" ry="28" fill={CREAM} />
          <ellipse cx="140" cy="124" rx="32" ry="28" fill={CREAM} />
          <ellipse cx="100" cy="138" rx="36" ry="26" fill={CREAM} />
          <ellipse cx="70" cy="70" rx="11" ry="7" fill={CREAM} />
          <ellipse cx="130" cy="70" rx="11" ry="7" fill={CREAM} />
          {/* tear marks: from under the eyes out across the cheeks */}
          <path d="M66 108 Q60 116 56 124" fill="none" stroke={TEAR} strokeWidth="7" strokeLinecap="round" opacity="0.55" />
          <path d="M134 108 Q140 116 144 124" fill="none" stroke={TEAR} strokeWidth="7" strokeLinecap="round" opacity="0.55" />
          {/* blush */}
          <ellipse cx="52" cy="134" rx="9" ry="5.5" fill={BLUSH} opacity={mood === "happy" ? 0.95 : 0.7} />
          <ellipse cx="148" cy="134" rx="9" ry="5.5" fill={BLUSH} opacity={mood === "happy" ? 0.95 : 0.7} />

          {/* eyes */}
          <g className="rp-eyes">
            {mood === "happy" ? (
              <>
                <path d="M61 98 Q72 84 83 98" fill="none" stroke={DARK} strokeWidth="5.5" strokeLinecap="round" />
                <path d="M117 98 Q128 84 139 98" fill="none" stroke={DARK} strokeWidth="5.5" strokeLinecap="round" />
              </>
            ) : mood === "sleepy" ? (
              <>
                <path d="M62 95 Q72 103 82 95" fill="none" stroke={DARK} strokeWidth="4.5" strokeLinecap="round" />
                <path d="M118 95 Q128 103 138 95" fill="none" stroke={DARK} strokeWidth="4.5" strokeLinecap="round" />
              </>
            ) : (
              <>
                <g className="rp-eye">
                  <g className="rp-blink">
                    <circle cx="72" cy="96" r={mood === "waiting" ? 11 : 10} fill={DARK} />
                    <circle cx="75.5" cy="92.5" r="3.2" fill="#fff" />
                    <circle cx="69" cy="99" r="1.5" fill="#fff" opacity="0.8" />
                  </g>
                </g>
                <g className="rp-eye">
                  <g className="rp-blink">
                    <circle cx="128" cy="96" r={mood === "waiting" ? 11 : 10} fill={DARK} />
                    <circle cx="131.5" cy="92.5" r="3.2" fill="#fff" />
                    <circle cx="125" cy="99" r="1.5" fill="#fff" opacity="0.8" />
                  </g>
                </g>
              </>
            )}
          </g>
          {mood === "error" && (
            <>
              <path d="M58 82 L80 76" fill="none" stroke={PAW} strokeWidth="3.5" strokeLinecap="round" />
              <path d="M142 82 L120 76" fill="none" stroke={PAW} strokeWidth="3.5" strokeLinecap="round" />
            </>
          )}

          {/* nose and mouth */}
          <path d="M93 126 Q100 121 107 126 Q105 136 100 139 Q95 136 93 126 Z" fill={DARK} />
          {mood === "happy" ? (
            <>
              <path d="M88 141 Q100 158 112 141 Z" fill={DARK} />
              <path d="M94 148 Q100 155 106 148 Z" fill="#f28c8c" />
            </>
          ) : mood === "waiting" ? (
            <circle cx="100" cy="147" r="4" fill="none" stroke={DARK} strokeWidth="3" />
          ) : mood === "error" ? (
            <path d="M90 148 Q95 142 100 148 T110 148" fill="none" stroke={DARK} strokeWidth="3" strokeLinecap="round" />
          ) : mood === "sleepy" ? (
            <path d="M96 147 Q100 150 104 147" fill="none" stroke={DARK} strokeWidth="3" strokeLinecap="round" />
          ) : (
            <path d="M100 139 V143 M91 143 Q100 152 109 143" fill="none" stroke={DARK} strokeWidth="3" strokeLinecap="round" />
          )}
        </g>

        {/* the laptop it works at, and paws on the keys */}
        {mood === "working" && (
          <g className="rp-laptop">
            <rect x="50" y="156" width="100" height="60" rx="10" fill="#3b3f47" />
            <rect x="58" y="164" width="84" height="46" rx="6" fill="#2b2f36" />
            <circle cx="100" cy="186" r="5" fill={CREAM} opacity="0.35" />
            <ellipse className="rp-paw-l rp-typing" cx="70" cy="158" rx="14" ry="10" fill={PAW} />
            <ellipse className="rp-paw-r rp-typing" cx="130" cy="158" rx="14" ry="10" fill={PAW} />
          </g>
        )}

        {/* a raised paw, and the card it holds up */}
        {mood === "waiting" && (
          <g className="rp-raise">
            <path d="M150 178 Q160 150 158 132" fill="none" stroke={PAW} strokeWidth="18" strokeLinecap="round" />
            <ellipse cx="158" cy="128" rx="14" ry="12" fill={PAW} />
            <g className="rp-bang">
              <circle cx="164" cy="50" r="18" fill="#fff" stroke="#e5e7eb" strokeWidth="2" />
              <text x="164" y="59" textAnchor="middle" fontSize="26" fontWeight="800" fill="#0064d4" fontFamily="Figtree, system-ui, sans-serif">
                !
              </text>
            </g>
          </g>
        )}

        {mood === "happy" && (
          <g className="rp-sparkles">
            <path className="rp-spark" d="M38 40 Q39 52 50 54 Q39 56 38 68 Q37 56 26 54 Q37 52 38 40 Z" fill="#f5b400" />
            <path className="rp-spark rp-spark-2" d="M166 34 Q167 43 175 44 Q167 45 166 54 Q165 45 157 44 Q165 43 166 34 Z" fill="#f5b400" />
          </g>
        )}

        {mood === "sleepy" && (
          <g className="rp-zs" fill="#6b7280" fontFamily="Figtree, system-ui, sans-serif" fontWeight="700">
            <text className="rp-z" x="146" y="70" fontSize="18">z</text>
            <text className="rp-z rp-z-2" x="158" y="54" fontSize="14">z</text>
            <text className="rp-z rp-z-3" x="167" y="41" fontSize="11">z</text>
          </g>
        )}

        {mood === "error" && <path className="rp-drop" d="M156 58 Q166 72 156 82 Q146 72 156 58 Z" fill="#8ec5ff" />}
      </g>
    </svg>
  );
}
