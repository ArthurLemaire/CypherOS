import { Check, LogOut, Shield, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api, setToken } from "../api";
import { Avatar } from "../components/Avatar";
import { useStore } from "../store";
import { cx } from "../util";

const EMOJI = ["✨", "🌙", "🪐", "🌿", "🔥", "🌊", "🦉", "🦊", "🐙", "🎯", "🧭", "💎", "🍀", "🎈", "🤖", "🧠"];
const COLORS = ["#7c3aed", "#2563eb", "#0891b2", "#059669", "#d97706", "#dc2626", "#db2777", "#4b5563"];

const MODES: Array<{ id: "ask" | "strict" | "auto"; title: string; text: string; icon: ReactNode }> = [
  {
    id: "ask",
    title: "Balanced",
    text: "Browse, read and write files freely; stop for anything hard to undo — email, purchases, shell commands.",
    icon: <ShieldCheck size={18} />,
  },
  {
    id: "strict",
    title: "Cautious",
    text: "Also ask before moderate actions like fetching web pages or writing files.",
    icon: <Shield size={18} />,
  },
  {
    id: "auto",
    title: "Hands-off",
    text: "Approve everything automatically except explicit deny rules. For trusted, unattended runs only.",
    icon: <ShieldAlert size={18} />,
  },
];

export function SettingsScreen() {
  const { state, refreshSettings, toast } = useStore();
  const s = state.settings;
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("✨");
  const [color, setColor] = useState(COLORS[0]);
  const [style, setStyle] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!s) void refreshSettings();
  }, [s, refreshSettings]);

  useEffect(() => {
    if (state.profile) {
      setName(state.profile.name);
      setEmoji(state.profile.emoji);
      setColor(state.profile.color);
      setStyle(state.profile.style);
    }
  }, [state.profile]);

  const update = async (body: Record<string, unknown>, msg?: string) => {
    setSaving(true);
    try {
      await api.updateSettings(body);
      await refreshSettings();
      if (msg) toast(msg);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const dirty =
    !!state.profile &&
    (name !== state.profile.name || emoji !== state.profile.emoji || color !== state.profile.color || style !== state.profile.style);

  const preview = state.profile ? { ...state.profile, name, emoji, color } : null;

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-4 pb-3">
        <h1 className="text-[24px] font-bold tracking-tight">You &amp; {state.profile?.name ?? "Muse"}</h1>
        <p className="text-[13px] text-muted">Make it yours, and decide how careful it should be.</p>
      </header>

      <div className="flex-1 overflow-y-auto px-4 pb-8 space-y-5">
        {/* Your Muse */}
        <Section title="Your Muse">
          <div className="flex items-center gap-4">
            <Avatar profile={preview} size={64} />
            <div className="flex-1">
              <label className="text-[12px] text-muted">Name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={40}
                className="mt-0.5 w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[15px] font-medium outline-none focus:ring-2 focus:ring-accent/40"
              />
            </div>
          </div>
          <div>
            <label className="text-[12px] text-muted">Avatar</label>
            <div className="mt-1.5 grid grid-cols-8 gap-1.5">
              {EMOJI.map((e) => (
                <button
                  key={e}
                  type="button"
                  onClick={() => setEmoji(e)}
                  className={cx("aspect-square rounded-2xl text-[22px] flex items-center justify-center bg-surface-2", emoji === e && "ring-2 ring-accent")}
                >
                  {e}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[12px] text-muted">Colour</label>
            <div className="mt-1.5 flex gap-2">
              {COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-label={c}
                  onClick={() => setColor(c)}
                  className="h-8 w-8 rounded-full flex items-center justify-center text-white"
                  style={{ background: c }}
                >
                  {color === c && <Check size={16} />}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[12px] text-muted">Personality &amp; style</label>
            <textarea
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              rows={2}
              placeholder="e.g. Warm, concise, a little witty. Uses metric units. Calls me Sam."
              className="mt-0.5 w-full resize-none rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40"
            />
          </div>
          <button
            type="button"
            disabled={!dirty || saving}
            onClick={() => void update({ profile: { name, emoji, color, style } }, "Saved")}
            className="w-full rounded-2xl bg-accent text-accent-fg py-2.5 font-medium disabled:opacity-40"
          >
            Save
          </button>
        </Section>

        {/* Sentinel */}
        <Section title="Safety · Sentinel">
          <p className="text-[13px] text-muted -mt-1">
            A separate gatekeeper reviews every action. Pick how often it should check in with you.
          </p>
          <div className="space-y-2">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => void update({ sentinel_mode: m.id })}
                className={cx(
                  "w-full text-left rounded-2xl border px-3.5 py-3 flex items-start gap-3 transition",
                  s?.sentinel.mode === m.id ? "border-accent bg-accent/8" : "border-border",
                )}
              >
                <div className={cx("mt-0.5", m.id === "auto" ? "text-rose-500" : "text-accent")}>{m.icon}</div>
                <div className="flex-1">
                  <div className="font-medium text-[14.5px]">
                    {m.title} <span className="text-muted font-normal">· {m.id}</span>
                  </div>
                  <div className="text-[12.5px] text-muted leading-snug mt-0.5">{m.text}</div>
                </div>
                {s?.sentinel.mode === m.id && <Check size={18} className="text-accent mt-0.5" />}
              </button>
            ))}
          </div>
          {s && (
            <div className="text-[12.5px] text-muted leading-relaxed">
              Always asks for: {s.sentinel.always_ask_tools.join(", ") || "—"}.{" "}
              {s.sentinel.taint_tracking && "After reading private data, new network destinations need approval."}
            </div>
          )}
        </Section>

        {/* Background work */}
        <Section title="Background work">
          <Toggle
            label="Keep working on goals while I'm away"
            hint={`Every ${state.profile?.goal_interval_minutes ?? 60} minutes, advance one active goal and post an update in the main chat.`}
            checked={!!state.profile?.proactive}
            onChange={(v) => void update({ profile: { proactive: v } })}
          />
          <div className="flex items-center gap-3">
            <label className="text-[13.5px] flex-1">Check-in interval</label>
            <select
              value={state.profile?.goal_interval_minutes ?? 60}
              onChange={(e) => void update({ profile: { goal_interval_minutes: Number(e.target.value) } })}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              {[15, 30, 60, 120, 240, 480, 1440].map((m) => (
                <option key={m} value={m}>
                  {m < 60 ? `${m} min` : `${m / 60} h`}
                </option>
              ))}
            </select>
          </div>
        </Section>

        {/* Model */}
        <Section title="Model">
          {s && (
            <div className="text-[13.5px] flex items-center justify-between">
              <span className="text-muted">Provider / model</span>
              <span className="font-mono text-[12.5px]">
                {s.llm.provider} · {s.llm.model}
              </span>
            </div>
          )}
          <Toggle
            label="Show thinking"
            hint="Reveal the model's reasoning under each reply when the provider exposes it."
            checked={!!s?.agent.show_thinking}
            onChange={(v) => void update({ show_thinking: v })}
          />
          <div className="flex items-center gap-3">
            <label className="text-[13.5px] flex-1">Reply language</label>
            <select
              value={s?.agent.language ?? "auto"}
              onChange={(e) => void update({ language: e.target.value })}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              <option value="auto">Match mine</option>
              <option value="English">English</option>
              <option value="中文">中文</option>
              <option value="日本語">日本語</option>
              <option value="Español">Español</option>
              <option value="Deutsch">Deutsch</option>
              <option value="Français">Français</option>
            </select>
          </div>
          {s && (
            <div className="text-[12.5px] text-muted">
              Tools: {s.tools.map((t) => t.name).join(", ")}.
              {s.connectors.email ? " Email connected." : " Email not configured."}
              {s.connectors.browser ? " Browser enabled." : ""}
              {s.connectors.mcp.length ? ` MCP: ${s.connectors.mcp.join(", ")}.` : ""}
            </div>
          )}
        </Section>

        {/* About */}
        <Section title="About">
          <div className="text-[13px] text-muted space-y-1">
            <div>OpenMuse {state.version}</div>
            {s && <div className="break-all">Data: {s.data_dir}</div>}
            {s && <div className="break-all">Workspace: {s.agent.workspace}</div>}
            <div>{state.connected ? "Connected" : "Reconnecting…"}</div>
          </div>
          <button
            type="button"
            onClick={() => {
              setToken("");
              window.location.reload();
            }}
            className="w-full rounded-2xl border border-border py-2.5 text-[14px] font-medium flex items-center justify-center gap-2 text-muted"
          >
            <LogOut size={16} /> Forget this device's access token
          </button>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-3xl bg-surface border border-border/70 shadow-sm p-4 space-y-3">
      <h2 className="text-[12px] font-semibold uppercase tracking-wide text-muted">{title}</h2>
      {children}
    </section>
  );
}

function Toggle({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start gap-3 cursor-pointer">
      <div className="flex-1">
        <div className="text-[14px]">{label}</div>
        {hint && <div className="text-[12.5px] text-muted leading-snug">{hint}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cx("relative mt-0.5 h-7 w-12 shrink-0 rounded-full transition", checked ? "bg-accent" : "bg-surface-2 border border-border")}
      >
        <span className={cx("absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition", checked ? "left-[22px]" : "left-0.5")} />
      </button>
    </label>
  );
}
