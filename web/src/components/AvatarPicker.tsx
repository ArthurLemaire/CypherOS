import { Check } from "lucide-react";
import { PLUSH, plushUrl } from "../avatars";
import { useT } from "../i18n";
import { cx } from "../util";

const EMOJI = ["✨", "🌙", "🪐", "🌿", "🔥", "🌊", "🦉", "🦊", "🐙", "🎯", "🧭", "💎", "🍀", "🎈", "🤖", "🧠"];
export const AVATAR_COLORS = ["#0064d4", "#7c3aed", "#0891b2", "#059669", "#d97706", "#dc2626", "#db2777", "#4b5563"];

export interface AvatarChoice {
  avatar: string;
  emoji: string;
  color: string;
}

/** The dolls, plus an emoji on a colour for anyone who would rather. Used in setup and in Settings. */
export function AvatarPicker({ value, onChange }: { value: AvatarChoice; onChange: (v: AvatarChoice) => void }) {
  const t = useT();
  const emojiMode = value.avatar === "";
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-7 gap-2">
        {PLUSH.map((p) => {
          const on = value.avatar === p.id;
          return (
            <button
              key={p.id}
              type="button"
              aria-label={p.label}
              aria-pressed={on}
              onClick={() => onChange({ ...value, avatar: p.id })}
              className={cx("relative aspect-square overflow-hidden rounded-full bg-[#eadfcd] transition", on ? "ring-[2.5px] ring-accent ring-offset-2 ring-offset-bg" : "opacity-90 hover:opacity-100")}
            >
              <img src={plushUrl(p.id)} alt="" draggable={false} className="h-full w-full object-cover" />
            </button>
          );
        })}
        <button
          type="button"
          aria-label={t("An emoji instead")}
          aria-pressed={emojiMode}
          onClick={() => onChange({ ...value, avatar: "" })}
          className={cx(
            "flex aspect-square items-center justify-center rounded-full text-[20px] transition",
            emojiMode ? "ring-[2.5px] ring-accent ring-offset-2 ring-offset-bg" : "opacity-90 hover:opacity-100",
          )}
          style={{ background: `linear-gradient(135deg, ${value.color}, color-mix(in srgb, ${value.color} 60%, #ffffff))` }}
        >
          {value.emoji}
        </button>
      </div>
      {emojiMode && (
        <>
          <div className="grid grid-cols-8 gap-1.5">
            {EMOJI.map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => onChange({ ...value, emoji: e })}
                className={cx("flex aspect-square items-center justify-center rounded-2xl bg-surface-2 text-[22px]", value.emoji === e && "ring-2 ring-accent")}
              >
                {e}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            {AVATAR_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                aria-label={c}
                onClick={() => onChange({ ...value, color: c })}
                className="flex h-8 w-8 items-center justify-center rounded-full text-white"
                style={{ background: c }}
              >
                {value.color === c && <Check size={16} />}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
