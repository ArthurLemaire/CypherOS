import { Box, Check, ChevronRight, LogOut, Moon, Shield, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api, setToken } from "../api";
import { Avatar } from "../components/Avatar";
import { BackBar } from "../components/BackBar";
import { LOCALES, setLocaleSetting, useLocaleSetting, useT } from "../i18n";
import { disablePush, enablePush, pushState, type PushState } from "../push";
import { useStore } from "../store";
import type { Proactivity, PushInfo } from "../types";
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
  const { state, refreshSettings, setTab, toast } = useStore();
  const s = state.settings;
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("✨");
  const [color, setColor] = useState(COLORS[0]);
  const [style, setStyle] = useState("");
  const [userName, setUserName] = useState("");
  const [saving, setSaving] = useState(false);
  const t = useT();
  const localeSetting = useLocaleSetting();

  useEffect(() => {
    if (!s) void refreshSettings();
  }, [s, refreshSettings]);

  useEffect(() => {
    if (state.profile) {
      setName(state.profile.name);
      setEmoji(state.profile.emoji);
      setColor(state.profile.color);
      setStyle(state.profile.style);
      setUserName(state.profile.user_name ?? "");
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
    (name !== state.profile.name ||
      emoji !== state.profile.emoji ||
      color !== state.profile.color ||
      style !== state.profile.style ||
      userName !== (state.profile.user_name ?? ""));

  const preview = state.profile ? { ...state.profile, name, emoji, color } : null;

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-2 pb-3">
        <BackBar />
        <h1 className="text-[24px] font-bold tracking-tight">{t("You & {name}", { name: state.profile?.name ?? "Muse" })}</h1>
        <p className="text-[13px] text-muted">{t("Make it yours, and decide how careful it should be.")}</p>
      </header>

      <div className="flex-1 overflow-y-auto px-4 pb-8 space-y-5">
        {/* Your Muse */}
        <Section title={t("Your Muse")}>
          <div className="flex items-center gap-4">
            <Avatar profile={preview} size={64} />
            <div className="flex-1">
              <label className="text-[12px] text-muted">{t("Name")}</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={40}
                className="mt-0.5 w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[15px] font-medium outline-none focus:ring-2 focus:ring-accent/40"
              />
            </div>
          </div>
          <div>
            <label className="text-[12px] text-muted">{t("Avatar")}</label>
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
            <label className="text-[12px] text-muted">{t("Colour")}</label>
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
            <label className="text-[12px] text-muted">{t("Personality & style")}</label>
            <textarea
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              rows={2}
              placeholder={t("e.g. Warm, concise, a little witty. Uses metric units. Calls me Sam.")}
              className="mt-0.5 w-full resize-none rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40"
            />
          </div>
          <div>
            <label className="text-[12px] text-muted">{t("What it calls you")}</label>
            <input
              value={userName}
              onChange={(e) => setUserName(e.target.value)}
              maxLength={60}
              placeholder={t("Your name")}
              className="mt-0.5 w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40"
            />
          </div>
          <button
            type="button"
            disabled={!dirty || saving}
            onClick={() => void update({ profile: { name, emoji, color, style, user_name: userName } }, t("Saved"))}
            className="w-full rounded-2xl bg-accent text-accent-fg py-2.5 font-medium disabled:opacity-40"
          >
            {t("Save")}
          </button>
        </Section>

        {/* Sentinel */}
        <Section title={t("Safety · Sentinel")}>
          <p className="text-[13px] text-muted -mt-1">
            {t("A separate gatekeeper reviews every action. Pick how often it should check in with you.")}
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
                    {t(m.title)} <span className="text-muted font-normal">· {m.id}</span>
                  </div>
                  <div className="text-[12.5px] text-muted leading-snug mt-0.5">{t(m.text)}</div>
                </div>
                {s?.sentinel.mode === m.id && <Check size={18} className="text-accent mt-0.5" />}
              </button>
            ))}
          </div>
          {s && (
            <div className="text-[12.5px] text-muted leading-relaxed">
              {t("Always asks for: {tools}.", { tools: s.sentinel.always_ask_tools.join(", ") || "—" })}{" "}
              {s.sentinel.taint_tracking && t("After reading private data, new network destinations need approval.")}
            </div>
          )}
          {s?.sandbox && (
            <div className="flex items-start gap-2.5 rounded-2xl bg-surface-2/60 px-3.5 py-2.5 text-[12.5px] leading-snug">
              <Box size={15} className={cx("shrink-0 mt-[2px]", s.sandbox.active ? "text-emerald-500" : "text-muted")} />
              <div>
                <div className="font-medium text-fg">
                  {s.sandbox.active ? t("Commands run in a sandbox") : t("Commands run without a sandbox")}
                  <span className="text-muted font-normal"> · {s.sandbox.status}</span>
                </div>
                <div className="text-muted mt-0.5">
                  {s.sandbox.active
                    ? t("Each shell or Python call gets its own namespace: only the workspace is writable, your home directory is not there, and there is no network unless the command needs it.")
                    : t("Each shell or Python call runs in the workspace with a scrubbed environment. On Linux, installing bubblewrap gives each one its own namespace.")}
                </div>
              </div>
            </div>
          )}
        </Section>

        {/* Proactivity */}
        <Section title={t("Proactivity")}>
          <ProactivityDial value={state.profile?.proactivity ?? "default"} onChange={(v) => void update({ profile: { proactivity: v } })} />
          <div className="flex items-center gap-3">
            <label className="text-[13.5px] flex-1">
              {t("Check-in interval")}
              {state.profile && state.profile.proactivity !== "default" && state.profile.proactivity !== "off" && (
                <span className="block text-[12px] text-muted">
                  {state.profile.proactivity === "low" ? t("Doubled at this level") : t("Halved at this level")}
                </span>
              )}
            </label>
            <select
              value={state.profile?.goal_interval_minutes ?? 60}
              onChange={(e) => void update({ profile: { goal_interval_minutes: Number(e.target.value) } })}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              {[...new Set([15, 30, 60, 120, 240, 480, 1440, state.profile?.goal_interval_minutes ?? 60])]
                .sort((a, b) => a - b)
                .map((m) => (
                  <option key={m} value={m}>
                    {m < 60 ? t("{n} min", { n: m }) : m % 60 ? `${t("{n} h", { n: Math.floor(m / 60) })} ${t("{n} min", { n: m % 60 })}` : t("{n} h", { n: m / 60 })}
                  </option>
                ))}
            </select>
          </div>
          <QuietHours value={state.profile?.quiet_hours ?? ""} onChange={(v) => void update({ profile: { quiet_hours: v } })} />
        </Section>

        {/* Notifications */}
        <Section title={t("Notifications")}>
          <PushSettings name={state.profile?.name ?? "Muse"} />
        </Section>

        {/* Model */}
        <Section title={t("Model")}>
          {s && (
            <button type="button" onClick={() => setTab("connections")} className="w-full text-[13.5px] flex items-center justify-between">
              <span className="text-muted">{t("Provider / model")}</span>
              <span className="font-mono text-[12.5px] flex items-center gap-1">
                {s.llm.model} <ChevronRight size={14} className="text-muted" />
              </span>
            </button>
          )}
          <Toggle
            label={t("Show thinking")}
            hint={t("Reveal the model's reasoning under each reply when the provider exposes it.")}
            checked={!!s?.agent.show_thinking}
            onChange={(v) => void update({ show_thinking: v })}
          />
          <div className="flex items-center gap-3">
            <label className="text-[13.5px] flex-1">
              {t("App language")}
              <span className="block text-[12px] text-muted">{t("This device only")}</span>
            </label>
            <select
              value={localeSetting}
              onChange={(e) => setLocaleSetting(e.target.value as typeof localeSetting)}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              {LOCALES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.value === "auto" ? t("Auto") : l.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-[13.5px] flex-1">
              {t("Reply language")}
              <span className="block text-[12px] text-muted">{t("What {name} writes in", { name: state.profile?.name ?? "Muse" })}</span>
            </label>
            <select
              value={s?.agent.language ?? "auto"}
              onChange={(e) => void update({ language: e.target.value })}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              <option value="auto">{t("Match mine")}</option>
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
              {t("Tools: {tools}.", { tools: s.tools.map((tool) => tool.name).join(", ") })}{" "}
              <button type="button" onClick={() => setTab("connections")} className="text-accent underline-offset-2 hover:underline">
                {t("Connections")}
              </button>{" "}
              {t("is where email, the browser and MCP servers are plugged in.")}
            </div>
          )}
        </Section>

        {/* About */}
        <Section title={t("About")}>
          <div className="text-[13px] text-muted space-y-1">
            <div>OpenMuse {state.version}</div>
            {s && <div className="break-all">{t("Data:")} {s.data_dir}</div>}
            {s && <div className="break-all">{t("Workspace:")} {s.agent.workspace}</div>}
            <div>{state.connected ? t("Connected") : t("Reconnecting…")}</div>
          </div>
          <button
            type="button"
            onClick={() => {
              setToken("");
              window.location.reload();
            }}
            className="w-full rounded-2xl border border-border py-2.5 text-[14px] font-medium flex items-center justify-center gap-2 text-muted"
          >
            <LogOut size={16} /> {t("Forget this device's access token")}
          </button>
        </Section>
      </div>
    </div>
  );
}

/** Web Push: on / off, what stands in the way, and a test button. */
function PushSettings({ name }: { name: string }) {
  const { toast } = useStore();
  const [info, setInfo] = useState<PushInfo | null>(null);
  const [status, setStatus] = useState<PushState>("off");
  const [busy, setBusy] = useState(false);
  const t = useT();

  const refresh = async () => {
    setStatus(await pushState());
    try {
      setInfo(await api.push());
    } catch {
      /* older server */
    }
  };
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = async () => {
    if (!info) return;
    setBusy(true);
    try {
      const next = status === "on" ? await disablePush() : await enablePush(info.public_key);
      setStatus(next);
      if (next === "denied") toast(t("Notifications are blocked for this site in the browser settings"));
      await refresh();
    } catch (e) {
      const err = e as Error;
      toast(
        err.name === "AbortError"
          ? t("This browser has no push service (embedded browsers often don't). Use Chrome, Edge, Firefox or Safari 16.4+ on the phone.")
          : err.message,
      );
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    try {
      const r = await api.pushTest();
      toast(r.ok ? t("Sent — it should arrive in a moment") : r.error ?? t("Could not send"));
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const blocked =
    status === "unsupported"
      ? t("This browser cannot receive push notifications.")
      : status === "insecure"
        ? t("Notifications need https:// (or localhost). Over plain http on your LAN the app works, this part stays off — see docs/deployment.md.")
        : status === "denied"
          ? t("Blocked for this site. Allow notifications in the browser's site settings, then try again.")
          : info && !info.available
            ? t("The server was installed without pywebpush.")
            : "";

  return (
    <>
      <Toggle
        label={t("Let {name} notify this device", { name })}
        hint={t("When it needs your approval, has a question, finished something in the background, or it is check-in time. Nothing is shown while the app is on screen.")}
        checked={status === "on"}
        onChange={() => void toggle()}
        disabled={busy || !!blocked}
      />
      {blocked && <div className="text-[12.5px] text-muted">{blocked}</div>}
      {info && info.subscriptions > 0 && (
        <div className="flex items-center justify-between text-[12.5px] text-muted">
          <span>
            {info.subscriptions === 1 ? t("1 device subscribed") : t("{n} devices subscribed", { n: info.subscriptions })}
          </span>
          <button type="button" onClick={() => void test()} className="text-accent font-medium">
            {t("Send a test")}
          </button>
        </div>
      )}
      <div className="text-[12.5px] text-muted">
        {t("On a phone, add the app to the home screen first: then the icon shows a badge with what is waiting for you, and notifications open the right chat.")}
      </div>
    </>
  );
}

const LEVELS: Array<{ id: Proactivity; title: string; text: string }> = [
  { id: "off", title: "Off", text: "Only works when you ask." },
  { id: "low", title: "Low", text: "Checks in half as often; speaks up only when a step is done or it needs you." },
  { id: "default", title: "Default", text: "Works on goals on schedule; reports real progress, stays quiet otherwise." },
  { id: "high", title: "High", text: "Checks in twice as often and always reports, even 'still on track'." },
];

export function ProactivityDial({ value, onChange }: { value: Proactivity; onChange: (v: Proactivity) => void }) {
  const t = useT();
  const current = LEVELS.find((l) => l.id === value) ?? LEVELS[2];
  return (
    <div>
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <div className="text-[14px]">{t("How much it does on its own")}</div>
          <div className="text-[12.5px] text-muted leading-snug">{t(current.text)}</div>
        </div>
      </div>
      <div className="mt-2 grid grid-cols-4 gap-1 rounded-2xl bg-surface-2 p-1">
        {LEVELS.map((l) => (
          <button
            key={l.id}
            type="button"
            onClick={() => onChange(l.id)}
            className={cx(
              "rounded-xl py-1.5 text-[13px] font-medium transition",
              value === l.id ? "bg-surface shadow-sm text-accent" : "text-muted",
            )}
          >
            {t(l.title)}
          </button>
        ))}
      </div>
    </div>
  );
}

export function QuietHours({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [start, end] = value ? value.split("-") : ["", ""];
  const on = !!value;
  const t = useT();
  const set = (s: string, e: string) => onChange(s && e ? `${s}-${e}` : "");
  return (
    <div>
      <label className="flex items-start gap-3 cursor-pointer">
        <div className="flex-1">
          <div className="text-[14px] flex items-center gap-1.5">
            <Moon size={15} className="text-muted" /> {t("Quiet hours")}
          </div>
          <div className="text-[12.5px] text-muted leading-snug">{t("No background work in this window; anything due waits until it ends.")}</div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          onClick={() => set(on ? "" : "22:00", on ? "" : "08:00")}
          className={cx("relative mt-0.5 h-7 w-12 shrink-0 rounded-full transition", on ? "bg-accent" : "bg-surface-2 border border-border")}
        >
          <span className={cx("absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition", on ? "left-[22px]" : "left-0.5")} />
        </button>
      </label>
      {on && (
        <div className="mt-2 flex items-center gap-2 text-[13.5px]">
          <span className="text-muted">{t("From")}</span>
          <input type="time" value={start} onChange={(e) => set(e.target.value, end)} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none" />
          <span className="text-muted">{t("to")}</span>
          <input type="time" value={end} onChange={(e) => set(start, e.target.value)} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none" />
        </div>
      )}
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

function Toggle({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
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
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative mt-0.5 h-7 w-12 shrink-0 rounded-full transition disabled:opacity-50",
          checked ? "bg-accent" : "bg-surface-2 border border-border",
        )}
      >
        <span className={cx("absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition", checked ? "left-[22px]" : "left-0.5")} />
      </button>
    </label>
  );
}
