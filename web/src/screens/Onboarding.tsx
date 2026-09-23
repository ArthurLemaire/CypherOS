import { ArrowRight, Loader2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { Avatar } from "../components/Avatar";
import { AVATAR_COLORS, AvatarPicker } from "../components/AvatarPicker";
import { useT } from "../i18n";
import { useStore } from "../store";
import type { ConnectionsData } from "../types";
import { cx } from "../util";
import { CalendarCard, ContactsCard, EmailCard, ModelCard, inputCls, primaryBtn, secondaryBtn } from "./ConnectionsScreen";

const STYLES = ["Warm and concise", "Direct, no small talk", "Playful and curious", "Calm and thorough"];

const FIRST_ASKS = [
  "Plan a 3-day trip to Kyoto in November on a mid-range budget",
  "Compare the three best mid-range e-readers and make me a table",
  "Set up a goal: run a 10k in 12 weeks, and check in on me weekly",
  "Find this week's top stories about small language models and summarise them",
];

type Step = "welcome" | "you" | "muse" | "model" | "connect" | "tips";
const ORDER: Step[] = ["welcome", "you", "muse", "model", "connect", "tips"];

/**
 * First run, the way Muse does it: who you are, who your OpenMuse is, which model runs it,
 * what it may reach — then a few things to try. Everything here can be changed later
 * under the avatar (Settings, Connections).
 */
export function Onboarding() {
  const { state, send, setTab, dismissOnboarding, refreshSettings, toast } = useStore();
  const [step, setStep] = useState<Step>("welcome");
  const [userName, setUserName] = useState(state.profile?.user_name ?? "");
  const [name, setName] = useState(state.profile?.name ?? "OpenMuse");
  const [look, setLook] = useState({
    avatar: state.profile?.avatar ?? "sunny",
    emoji: state.profile?.emoji ?? "✨",
    color: state.profile?.color ?? AVATAR_COLORS[0],
  });
  const [style, setStyle] = useState(state.profile?.style ?? "");
  const [conn, setConn] = useState<ConnectionsData | null>(null);
  const [saving, setSaving] = useState(false);
  const t = useT();

  const loadConn = async () => {
    try {
      setConn(await api.connections());
    } catch {
      /* shown as loading */
    }
  };
  useEffect(() => {
    void loadConn();
  }, [state.connectionsVersion]);

  const idx = ORDER.indexOf(step);
  const next = () => setStep(ORDER[Math.min(idx + 1, ORDER.length - 1)]);
  const back = () => setStep(ORDER[Math.max(idx - 1, 0)]);

  const saveProfile = async () => {
    setSaving(true);
    try {
      await api.updateSettings({ profile: { name: name.trim() || "OpenMuse", ...look, style: style.trim(), user_name: userName.trim() } });
      await refreshSettings();
      next();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const finish = async (firstAsk?: string) => {
    try {
      await api.onboarded(true);
      await refreshSettings();
    } catch {
      /* the server remembers next time */
    }
    dismissOnboarding();
    setTab("chat");
    if (firstAsk) void send("main", firstAsk);
  };

  const preview = {
    name,
    ...look,
    style,
    user_name: userName,
    proactivity: "default" as const,
    proactive: true,
    goal_interval_minutes: 60,
    quiet_hours: "",
  };
  const modelReady = conn ? conn.llm.key_source === "vault" || conn.llm.key_source === "config" || !!conn.providers[presetOf(conn)]?.no_key : false;

  return (
    <div className="mx-auto flex h-[100dvh] max-w-[760px] flex-col bg-bg sm:border-x sm:border-border">
      <header className="safe-top shrink-0 px-5 pt-4 pb-2 flex items-center justify-between">
        <div className="flex gap-1">
          {ORDER.map((s, i) => (
            <span key={s} className={cx("h-1.5 rounded-full transition-all", i <= idx ? "w-5 bg-accent" : "w-1.5 bg-border")} />
          ))}
        </div>
        {step !== "tips" && (
          <button type="button" onClick={() => void finish()} className="text-[13px] text-muted">
            {t("Skip setup")}
          </button>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-5 pb-6">
        {step === "welcome" && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Avatar profile={preview} size={96} />
            <h1 className="mt-6 text-[28px] font-bold tracking-tight">{t("Meet your OpenMuse")}</h1>
            <p className="mt-3 max-w-sm text-[15px] text-muted leading-relaxed">
              {t("A personal agent that does the work: it searches, browses, writes files and code, reads and sends mail, and keeps going on long goals while you are away.")}
            </p>
            <div className="mt-6 max-w-sm rounded-3xl bg-surface border border-border/70 p-4 text-left text-[13.5px] leading-relaxed">
              <div className="flex items-center gap-2 font-medium">
                <ShieldCheck size={18} className="text-accent" /> {t("Yours, on your machine")}
              </div>
              <p className="mt-1.5 text-muted">
                {t("It runs on the server you started. A separate Sentinel checks every action, asks before anything hard to undo, and keeps your keys and passwords in an encrypted vault the model cannot read.")}
              </p>
            </div>
          </div>
        )}

        {step === "you" && (
          <div className="pt-6">
            <h1 className="text-[26px] font-bold tracking-tight">{t("First, you")}</h1>
            <p className="mt-1 text-[14px] text-muted">{t("What should it call you?")}</p>
            <input
              autoFocus
              value={userName}
              onChange={(e) => setUserName(e.target.value)}
              maxLength={60}
              placeholder={t("Your name")}
              className={cx(inputCls, "mt-5 text-[18px] py-3")}
            />
            <p className="mt-3 text-[12.5px] text-muted">
              {t("Anything else it should know about you — where you live, what you do, what you like — you can just tell it in the chat. It remembers.")}
            </p>
          </div>
        )}

        {step === "muse" && (
          <div className="pt-6 space-y-5">
            <div>
              <h1 className="text-[26px] font-bold tracking-tight">{t("Now, your OpenMuse")}</h1>
              <p className="mt-1 text-[14px] text-muted">{t("Give it a name, a look and a way of talking.")}</p>
            </div>
            <div className="flex items-center gap-4">
              <Avatar profile={preview} size={72} />
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} className={cx(inputCls, "text-[17px] font-medium")} placeholder="OpenMuse" />
            </div>
            <AvatarPicker value={look} onChange={setLook} />
            <div>
              <div className="flex flex-wrap gap-1.5">
                {STYLES.map((s) => (
                  <button key={s} type="button" onClick={() => setStyle(t(s))} className={cx("rounded-full px-3 py-1.5 text-[13px] border", style === t(s) ? "border-accent bg-accent/10 text-accent font-medium" : "border-border text-muted")}>
                    {t(s)}
                  </button>
                ))}
              </div>
              <textarea
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                rows={2}
                placeholder={t("…or describe it: e.g. Warm, concise, a little witty. Uses metric units.")}
                className={cx(inputCls, "mt-2 resize-none text-[14px]")}
              />
            </div>
          </div>
        )}

        {step === "model" && (
          <div className="pt-6 space-y-4">
            <div>
              <h1 className="text-[26px] font-bold tracking-tight">{t("The model behind it")}</h1>
              <p className="mt-1 text-[14px] text-muted">
                {modelReady
                  ? t("A model is already set up on the server. Keep it, or switch here.")
                  : t("Pick a provider and paste a key. It is stored encrypted in the vault on the server, never shown to the model.")}
              </p>
            </div>
            {conn ? (
              <ModelCard data={conn} onChange={() => void loadConn()} compact />
            ) : (
              <div className="flex justify-center py-8 text-muted">
                <Loader2 className="animate-spin" size={20} />
              </div>
            )}
          </div>
        )}

        {step === "connect" && (
          <div className="pt-6 space-y-4">
            <div>
              <h1 className="text-[26px] font-bold tracking-tight">{t("Connect your mail, calendar and contacts")}</h1>
              <p className="mt-1 text-[14px] text-muted">
                {t("Optional. With a mailbox connected it can read what came in and draft replies; it will always ask before sending. With a calendar it knows your day and finds free time. With your contacts it knows who is who. The browser and MCP servers are under Connections later.")}
              </p>
            </div>
            {conn ? (
              <>
                <EmailCard data={conn} onChange={() => void loadConn()} compact />
                <CalendarCard data={conn} onChange={() => void loadConn()} compact />
                <ContactsCard data={conn} onChange={() => void loadConn()} compact />
              </>
            ) : (
              <div className="flex justify-center py-8 text-muted">
                <Loader2 className="animate-spin" size={20} />
              </div>
            )}
          </div>
        )}

        {step === "tips" && (
          <div className="pt-6 space-y-4">
            <div className="flex items-center gap-3">
              <Avatar profile={preview} size={48} />
              <div>
                <h1 className="text-[24px] font-bold tracking-tight">{userName ? t("Ready, {name}.", { name: userName }) : t("Ready.")}</h1>
                <p className="text-[14px] text-muted">{t("A few things people do in their first days.")}</p>
              </div>
            </div>
            <ul className="space-y-2">
              {FIRST_ASKS.map((ask) => (
                <li key={ask}>
                  <button type="button" onClick={() => void finish(t(ask))} className="w-full text-left rounded-2xl bg-surface border border-border/70 px-4 py-3 text-[14px] flex items-center gap-3 active:bg-surface-2">
                    <span className="flex-1">{t(ask)}</span>
                    <ArrowRight size={16} className="text-muted shrink-0" />
                  </button>
                </li>
              ))}
            </ul>
            <div className="rounded-3xl bg-surface-2/60 p-4 text-[13px] text-muted leading-relaxed space-y-1.5">
              <p>
                <b className="text-fg">{t("Approvals.")}</b> {t("When it wants to do something that matters — send mail, run a command, reach a new site — a card appears. Allow once, for this task, or always.")}
              </p>
              <p>
                <b className="text-fg">{t("Goals.")}</b> {t("Anything long-running lives in Goals; turn on background work in Settings and it keeps going between your visits, reporting in the Feed.")}
              </p>
              <p>
                <b className="text-fg">{t("Library.")}</b> {t("Pages, documents and files it makes for you open right here.")}
              </p>
            </div>
          </div>
        )}
      </div>

      <footer className="safe-bottom shrink-0 px-5 pb-5 pt-2 flex gap-2">
        {idx > 0 && step !== "tips" && (
          <button type="button" onClick={back} className={secondaryBtn}>
            {t("Back")}
          </button>
        )}
        {step === "welcome" && (
          <button type="button" onClick={next} className={cx(primaryBtn, "flex-1 py-3")}>
            {t("Get started")} <ArrowRight size={16} />
          </button>
        )}
        {step === "you" && (
          <button type="button" onClick={next} className={cx(primaryBtn, "flex-1 py-3")}>
            {userName.trim() ? t("Continue") : t("Skip")} <ArrowRight size={16} />
          </button>
        )}
        {step === "muse" && (
          <button type="button" disabled={saving} onClick={() => void saveProfile()} className={cx(primaryBtn, "flex-1 py-3")}>
            {saving ? <Loader2 size={16} className="animate-spin" /> : null} {t("Continue")} <ArrowRight size={16} />
          </button>
        )}
        {step === "model" && (
          <button type="button" disabled={!modelReady} onClick={next} className={cx(primaryBtn, "flex-1 py-3")}>
            {modelReady ? t("Continue") : t("Save a model to continue")} <ArrowRight size={16} />
          </button>
        )}
        {step === "connect" && (
          <button type="button" onClick={next} className={cx(primaryBtn, "flex-1 py-3")}>
            {conn?.email.configured ? t("Continue") : t("Skip for now")} <ArrowRight size={16} />
          </button>
        )}
        {step === "tips" && (
          <button type="button" onClick={() => void finish()} className={cx(primaryBtn, "flex-1 py-3")}>
            {t("Open the chat")} <ArrowRight size={16} />
          </button>
        )}
      </footer>
    </div>
  );
}

function presetOf(conn: ConnectionsData): string {
  const hit = Object.entries(conn.providers).find(([id, p]) => id !== "custom" && p.base_url && conn.llm.base_url.startsWith(p.base_url));
  return hit?.[0] ?? "custom";
}
