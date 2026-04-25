import { ArrowRight, Check, ChevronRight, Loader2, Lock } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { MASCOT } from "../avatars";
import { Avatar } from "../components/Avatar";
import { AVATAR_COLORS } from "../components/AvatarPicker";
import { IdentityForm, identityBody, identityOf, type Identity } from "../components/IdentityForm";
import { useT } from "../i18n";
import { useStore } from "../store";
import type { ConnectionsData, Profile } from "../types";
import { cx } from "../util";
import { CalendarCard, ContactsCard, EmailCard, ModelCard, inputCls, primaryBtn, secondaryBtn } from "./ConnectionsScreen";

const FIRST_ASKS = [
  "Plan a 3-day trip to Kyoto in November on a mid-range budget",
  "Compare the three best mid-range e-readers and make me a table",
  "Set up a goal: run a 10k in 12 weeks, and check in on me weekly",
  "Find this week's top stories about small language models and summarise them",
];

type Step = "welcome" | "list" | "muse" | "model" | "connect" | "tips";

/**
 * First run, the way Muse does it: meet it and name it, give it a model, start. A short
 * list in that order — done items ticked, the start locked until a model answers — and
 * three optional connections under it. Everything here can be changed later under the
 * avatar (Settings, Connections).
 */
export function Onboarding() {
  const { state, send, setTab, dismissOnboarding, refreshSettings, toast } = useStore();
  const [step, setStep] = useState<Step>("welcome");
  const [identity, setIdentity] = useState<Identity>(() => identityOf(state.profile, MASCOT, AVATAR_COLORS[0]));
  // "named" survives a reload: a profile that differs from the defaults was saved by the user
  const [named, setNamed] = useState(() => customised(state.profile));
  useEffect(() => {
    if (step === "muse") return; // never clobber what is being typed
    setIdentity(identityOf(state.profile, MASCOT, AVATAR_COLORS[0]));
    setNamed(customised(state.profile));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.profile]);
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

  const saveIdentity = async () => {
    setSaving(true);
    try {
      await api.updateSettings({ profile: identityBody(identity) });
      await refreshSettings();
      setNamed(true);
      setStep("list");
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

  const preview = { ...identity, proactivity: "default" as const, proactive: true, goal_interval_minutes: 60, quiet_hours: "" };
  const name = identity.name.trim() || "nanoMuse";
  const modelReady = conn ? conn.llm.key_source === "vault" || conn.llm.key_source === "config" || !!conn.providers[presetOf(conn)]?.no_key : false;
  const connected = !!conn && (conn.email.configured || conn.calendar.feeds.length > 0 || conn.contacts.sources.length > 0);
  const progress: Step[] = ["welcome", "list", "tips"];
  const idx = step === "welcome" ? 0 : step === "tips" ? 2 : 1;

  return (
    <div className="mx-auto flex h-[100dvh] max-w-[760px] flex-col bg-bg sm:border-x sm:border-border">
      <header className="safe-top shrink-0 px-5 pt-4 pb-2 flex items-center justify-between">
        <div className="flex gap-1">
          {progress.map((s, i) => (
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
            <h1 className="mt-6 text-[28px] font-bold tracking-tight">{t("Meet your nanoMuse")}</h1>
            <p className="mt-2 text-[15px] text-muted">{t("A personal agent of your own. Three things to know:")}</p>
            <ul className="mt-6 w-full max-w-sm space-y-2.5 text-left">
              <Point n={1} title={t("It does things for you.")} body={t("Searches, browses, writes, books, reads mail — and hands you the result, not a list of links.")} />
              <Point n={2} title={t("It keeps working when you close the app.")} body={t("Goals move forward between your visits; it reports in the Feed and notifies you when something is worth it.")} />
              <Point n={3} title={t("It asks you first where it matters.")} body={t("A separate Sentinel reviews every action. Sending, paying, deleting — it stops and asks; your keys stay in a vault the model cannot read.")} />
            </ul>
          </div>
        )}

        {step === "list" && (
          <div className="pt-6">
            <div className="flex items-center gap-3">
              <Avatar profile={preview} size={56} />
              <div className="min-w-0">
                <h1 className="text-[24px] font-bold tracking-tight truncate">{named ? name : t("Set it up")}</h1>
                <p className="text-[13.5px] text-muted truncate">{named && identity.tagline ? identity.tagline : t("Three steps, two minutes.")}</p>
              </div>
            </div>
            <ol className="mt-6 space-y-2">
              <Item done={named} title={t("Meet your nanoMuse")} body={named ? t("Named {name}. Tap to change.", { name }) : t("Give it a name, a face and a way of talking.")} onClick={() => setStep("muse")} />
              <Item done={modelReady} title={t("Add a model")} body={modelReady ? `${conn?.llm.model} · ${hostOf(conn?.llm.base_url ?? "")}` : t("Pick a provider and paste a key. Yours, stored in the vault.")} onClick={() => setStep("model")} />
              <Item done={connected} optional title={t("Connect mail, calendar, contacts")} body={connected ? t("Connected. Tap to add more.") : t("Optional — it can read what came in, know your day, and who is who.")} onClick={() => setStep("connect")} />
              <Item locked={!modelReady} done={false} title={t("Start")} body={modelReady ? t("Open the chat and ask for the first thing.") : t("Needs a model first.")} onClick={() => modelReady && setStep("tips")} />
            </ol>
          </div>
        )}

        {step === "muse" && (
          <div className="pt-6 space-y-5">
            <div>
              <h1 className="text-[26px] font-bold tracking-tight">{t("Meet your nanoMuse")}</h1>
              <p className="mt-1 text-[14px] text-muted">{t("The name comes first. Then a face, a tagline and how it talks — and what it should call you.")}</p>
            </div>
            <IdentityForm value={identity} onChange={setIdentity} inputCls={inputCls} />
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
                <h1 className="text-[24px] font-bold tracking-tight">{identity.user_name.trim() ? t("Ready, {name}.", { name: identity.user_name.trim() }) : t("Ready.")}</h1>
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
        {(step === "model" || step === "connect") && (
          <button type="button" onClick={() => setStep("list")} className={secondaryBtn}>
            {t("Back")}
          </button>
        )}
        {step === "welcome" && (
          <button type="button" onClick={() => setStep("list")} className={cx(primaryBtn, "flex-1 py-3")}>
            {t("Get started")} <ArrowRight size={16} />
          </button>
        )}
        {step === "list" && (
          <button type="button" disabled={!modelReady} onClick={() => setStep("tips")} className={cx(primaryBtn, "flex-1 py-3")}>
            {modelReady ? t("Start") : t("Add a model to start")} <ArrowRight size={16} />
          </button>
        )}
        {step === "muse" && (
          <button type="button" disabled={saving} onClick={() => void saveIdentity()} className={cx(primaryBtn, "flex-1 py-3")}>
            {saving ? <Loader2 size={16} className="animate-spin" /> : null} {t("That's {name}", { name })} <ArrowRight size={16} />
          </button>
        )}
        {step === "model" && (
          <button type="button" disabled={!modelReady} onClick={() => setStep("list")} className={cx(primaryBtn, "flex-1 py-3")}>
            {modelReady ? t("Done") : t("Save a model to continue")} <ArrowRight size={16} />
          </button>
        )}
        {step === "connect" && (
          <button type="button" onClick={() => setStep("list")} className={cx(primaryBtn, "flex-1 py-3")}>
            {connected ? t("Done") : t("Skip for now")} <ArrowRight size={16} />
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

function Point({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <li className="flex gap-3 rounded-3xl bg-surface border border-border/70 p-4">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/12 text-[13px] font-semibold text-accent">{n}</span>
      <div className="text-[13.5px] leading-relaxed">
        <div className="font-medium text-fg">{title}</div>
        <div className="text-muted">{body}</div>
      </div>
    </li>
  );
}

/** One row of the first-run list: ticked when done, greyed and locked until it can be done. */
function Item({ done, locked, optional, title, body, onClick }: { done: boolean; locked?: boolean; optional?: boolean; title: string; body: ReactNode; onClick: () => void }) {
  const t = useT();
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        disabled={locked}
        aria-disabled={locked}
        className={cx("w-full flex items-center gap-3 rounded-3xl border px-4 py-3.5 text-left transition-colors", done ? "border-accent/30 bg-accent/5" : "border-border/70 bg-surface", locked && "opacity-50")}
      >
        <span className={cx("flex h-7 w-7 shrink-0 items-center justify-center rounded-full", done ? "bg-accent text-white" : locked ? "bg-surface-2 text-muted" : "border border-border text-muted")}>
          {done ? <Check size={15} strokeWidth={3} /> : locked ? <Lock size={13} /> : null}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-[15px] font-medium">
            <span className="truncate">{title}</span>
            {optional && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10.5px] font-medium text-muted">{t("optional")}</span>}
          </span>
          <span className="block truncate text-[12.5px] text-muted">{body}</span>
        </span>
        {!locked && <ChevronRight size={16} className="shrink-0 text-muted" />}
      </button>
    </li>
  );
}

/** Whether the saved profile carries anything the user chose (name, tagline, tone, style, their own name). */
function customised(p: Profile | null | undefined): boolean {
  if (!p) return false;
  return (p.name && p.name !== "nanoMuse") || !!p.tagline || !!p.tone || !!p.communication || !!p.style || !!p.user_name;
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function presetOf(conn: ConnectionsData): string {
  const hit = Object.entries(conn.providers).find(([id, p]) => id !== "custom" && p.base_url && conn.llm.base_url.startsWith(p.base_url));
  return hit?.[0] ?? "custom";
}
