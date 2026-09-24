import { Shuffle } from "lucide-react";
import { useMemo, useState } from "react";
import { useT } from "../i18n";
import type { Profile } from "../types";
import { cx } from "../util";
import { Avatar } from "./Avatar";
import { AvatarPicker } from "./AvatarPicker";

/** The part of the profile that is who the agent is: name, tagline, face, voice. */
export type Identity = Pick<Profile, "name" | "tagline" | "avatar" | "emoji" | "color" | "tone" | "communication" | "style" | "user_name">;

export const NAME_MAX = 20;
export const TAGLINE_MAX = 60;

/** Names people give a helper: short, sayable, none of them a brand. Six at a time, shuffled. */
const SUGGESTED_NAMES = ["Muse", "Veda", "Nova", "Pip", "Sage", "Juno", "Kit", "Wren", "Iris", "Milo", "Echo", "Remy", "Otto", "Luna", "Ari", "Bea", "Nico", "Zed", "小墨", "阿柒", "小满", "知了", "豆豆", "小竹"];

export const TONES = ["formal", "casual", "playful", "concise"] as const;
export const COMMUNICATION = ["short", "detailed", "bullets"] as const;

const TONE_LABELS: Record<(typeof TONES)[number], string> = { formal: "Formal", casual: "Casual", playful: "Playful", concise: "Concise" };
const COMM_LABELS: Record<(typeof COMMUNICATION)[number], string> = { short: "Short replies", detailed: "Detailed", bullets: "Bullet points" };

function pickSix(exclude: string, seed: number): string[] {
  const pool = SUGGESTED_NAMES.filter((n) => n !== exclude);
  // a deterministic shuffle from the seed, so a re-render does not reshuffle
  const out: string[] = [];
  let x = seed || 1;
  const copy = [...pool];
  while (out.length < 6 && copy.length) {
    x = (x * 9301 + 49297) % 233280;
    out.push(copy.splice(x % copy.length, 1)[0]);
  }
  return out;
}

export function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={cx("rounded-full px-3 py-1.5 text-[13px] border transition-colors", active ? "border-accent bg-accent/10 text-accent font-medium" : "border-border text-muted")}>
      {children}
    </button>
  );
}

/**
 * Who your nanoMuse is. Used on the first-run naming page and under Settings; the same
 * fields, the same limits as the server (`NAME_MAX`, `TAGLINE_MAX`, the tone and
 * communication vocabularies). An empty name falls back to "nanoMuse" on save.
 */
export function IdentityForm({ value, onChange, suggestions = true, askUserName = true, inputCls }: { value: Identity; onChange: (v: Identity) => void; suggestions?: boolean; askUserName?: boolean; inputCls: string }) {
  const t = useT();
  const [seed, setSeed] = useState(7);
  const names = useMemo(() => pickSix(value.name, seed), [value.name, seed]);
  const set = (patch: Partial<Identity>) => onChange({ ...value, ...patch });
  const preview = { ...value, proactivity: "default" as const, proactive: true, goal_interval_minutes: 60, quiet_hours: "" };

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-4">
        <Avatar profile={preview} size={72} />
        <div className="flex-1 min-w-0 space-y-2">
          <div>
            <input
              value={value.name}
              onChange={(e) => set({ name: e.target.value.slice(0, NAME_MAX) })}
              maxLength={NAME_MAX}
              className={cx(inputCls, "text-[17px] font-medium")}
              placeholder="nanoMuse"
              aria-label={t("Name")}
              autoCapitalize="words"
            />
            <div className="mt-1 flex justify-between text-[11.5px] text-muted">
              <span>{t("1–20 characters. Empty means nanoMuse.")}</span>
              <span>
                {value.name.length}/{NAME_MAX}
              </span>
            </div>
          </div>
          <input
            value={value.tagline}
            onChange={(e) => set({ tagline: e.target.value.slice(0, TAGLINE_MAX) })}
            maxLength={TAGLINE_MAX}
            className={cx(inputCls, "text-[14px]")}
            placeholder={t("A line under the name, e.g. Your day, sorted.")}
            aria-label={t("Tagline")}
          />
        </div>
      </div>

      {suggestions && (
        <div className="flex flex-wrap items-center gap-1.5">
          {names.map((n) => (
            <Chip key={n} active={value.name === n} onClick={() => set({ name: n })}>
              {n}
            </Chip>
          ))}
          <button type="button" onClick={() => setSeed((s) => s + 1)} aria-label={t("More names")} className="rounded-full border border-border p-1.5 text-muted">
            <Shuffle size={14} />
          </button>
        </div>
      )}

      <AvatarPicker value={{ avatar: value.avatar, emoji: value.emoji, color: value.color }} onChange={(look) => set(look)} />

      <div>
        <label className="text-[12px] text-muted">{t("Tone")}</label>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {TONES.map((tone) => (
            <Chip key={tone} active={value.tone === tone} onClick={() => set({ tone: value.tone === tone ? "" : tone })}>
              {t(TONE_LABELS[tone])}
            </Chip>
          ))}
        </div>
      </div>
      <div>
        <label className="text-[12px] text-muted">{t("How much it says")}</label>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {COMMUNICATION.map((c) => (
            <Chip key={c} active={value.communication === c} onClick={() => set({ communication: value.communication === c ? "" : c })}>
              {t(COMM_LABELS[c])}
            </Chip>
          ))}
        </div>
      </div>
      <div>
        <label className="text-[12px] text-muted">{t("Anything else about how it should be")}</label>
        <textarea
          value={value.style}
          onChange={(e) => set({ style: e.target.value })}
          rows={2}
          placeholder={t("e.g. A little witty. Uses metric units. Never uses emoji.")}
          className={cx(inputCls, "mt-1 resize-none text-[14px]")}
        />
      </div>
      {askUserName && (
        <div>
          <label className="text-[12px] text-muted">{t("What it calls you")}</label>
          <input value={value.user_name} onChange={(e) => set({ user_name: e.target.value })} maxLength={60} placeholder={t("Your name")} className={cx(inputCls, "mt-1 text-[14px]")} />
        </div>
      )}
    </div>
  );
}

/** The identity as the store has it, with defaults for a profile from before these fields. */
export function identityOf(p: Partial<Profile> | null | undefined, fallbackAvatar: string, fallbackColor: string): Identity {
  return {
    name: p?.name ?? "nanoMuse",
    tagline: p?.tagline ?? "",
    avatar: p?.avatar ?? fallbackAvatar,
    emoji: p?.emoji ?? "✨",
    color: p?.color ?? fallbackColor,
    tone: p?.tone ?? "",
    communication: p?.communication ?? "",
    style: p?.style ?? "",
    user_name: p?.user_name ?? "",
  };
}

/** What to send: trimmed, the empty name back to the default. */
export function identityBody(v: Identity): Identity {
  return { ...v, name: v.name.trim() || "nanoMuse", tagline: v.tagline.trim(), style: v.style.trim(), user_name: v.user_name.trim() };
}
