import {
  AlarmClock,
  Ban,
  Bell,
  Brain,
  CalendarClock,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Copy,
  Loader2,
  Mail,
  Play,
  Plug,
  Repeat,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  SlidersHorizontal,
  Wand2,
  Webhook,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { Avatar } from "../components/Avatar";
import { ApprovalCard, RiskBadge, grantSubject, scopeLabel, toolIcon } from "../components/Cards";
import { Sheet } from "../components/Sheet";
import { intlLocale, useT } from "../i18n";
import { useStore } from "../store";
import type {
  ActivityData,
  AuditEntry,
  Grant,
  Reminder,
  ReminderKind,
  RiskLevel,
  Trigger,
  TriggerKind,
  TriggersData,
  UpcomingData,
} from "../types";
import { cx, relativeTime, timeShort } from "../util";
import { describeCadence } from "./GoalsScreen";

type View = "menu" | "activity" | "approvals" | "permissions" | "upcoming";

/**
 * Tap the avatar: the menu behind your Muse. What it has been doing (activity log),
 * what is waiting for you (approvals queue, across every chat), what it is allowed to do
 * (permissions), what it will do next (upcoming), plus its memory and settings.
 */
export function MuseSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { state, setTab } = useStore();
  const [view, setView] = useState<View>("menu");
  const name = state.profile?.name ?? "OpenMuse";
  const pending = state.pendingApprovals.length;
  const t = useT();

  useEffect(() => {
    if (open) setView(pending > 0 ? "approvals" : "menu");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const go = (tab: "memory" | "skills" | "connections" | "you") => {
    onClose();
    setTab(tab);
  };

  const titles: Record<View, string> = {
    menu: name,
    activity: t("Activity"),
    approvals: t("Approvals"),
    permissions: t("Permissions"),
    upcoming: t("Upcoming"),
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center gap-1.5">
          {view !== "menu" && (
            <button type="button" onClick={() => setView("menu")} aria-label={t("Back")} className="-ml-2 p-1 rounded-full text-muted hover:bg-surface-2">
              <ChevronLeft size={20} />
            </button>
          )}
          <span>{titles[view]}</span>
          {view === "menu" && (
            <span className="text-[12px] font-normal text-muted">
              {state.status.state === "idle" ? t("idle") : state.status.detail || t(state.status.state)}
            </span>
          )}
        </div>
      }
    >
      {view === "menu" && (
        <Menu
          name={name}
          pending={pending}
          onPick={(v) => setView(v)}
          onMemory={() => go("memory")}
          onSkills={() => go("skills")}
          onConnections={() => go("connections")}
          onSettings={() => go("you")}
        />
      )}
      {view === "activity" && <ActivityView open={open} />}
      {view === "approvals" && <ApprovalsView onDone={() => setView("menu")} />}
      {view === "permissions" && <PermissionsView open={open} />}
      {view === "upcoming" && <UpcomingView onSettings={() => go("you")} />}
    </Sheet>
  );
}

// ------------------------------------------------------------------ menu
function Menu({
  name,
  pending,
  onPick,
  onMemory,
  onSkills,
  onConnections,
  onSettings,
}: {
  name: string;
  pending: number;
  onPick: (v: View) => void;
  onMemory: () => void;
  onSkills: () => void;
  onConnections: () => void;
  onSettings: () => void;
}) {
  const { state } = useStore();
  const t = useT();
  const mode = state.settings?.sentinel.mode;
  const c = state.settings?.connectors;
  const connected = [c?.email && t("email"), c?.calendar && t("calendar"), c?.browser && t("browser"), c?.mcp.length ? `${c.mcp.length} MCP` : null].filter(Boolean);
  return (
    <div className="pb-2">
      <div className="flex items-center gap-3 rounded-3xl bg-surface-2/70 px-4 py-3">
        <Avatar profile={state.profile} status={state.status} size={48} />
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-[16px] truncate">{name}</div>
          <div className="text-[12.5px] text-muted truncate">
            {state.settings?.llm.model ?? "—"} · {mode === "ask" ? t("balanced") : mode === "strict" ? t("cautious") : mode === "auto" ? t("hands-off") : ""}
          </div>
        </div>
      </div>
      <ul className="mt-3 divide-y divide-border/70 rounded-3xl border border-border/70 overflow-hidden">
        <MenuRow icon={<ShieldAlert size={19} />} label={t("Approvals")} hint={pending ? t("{n} waiting for you", { n: pending }) : t("Nothing waiting")} badge={pending} onClick={() => onPick("approvals")} />
        <MenuRow icon={<ClipboardList size={19} />} label={t("Activity")} hint={t("Every action, including refused ones")} onClick={() => onPick("activity")} />
        <MenuRow icon={<ShieldCheck size={19} />} label={t("Permissions")} hint={t("What you allowed, revoke any time")} onClick={() => onPick("permissions")} />
        <MenuRow icon={<Bell size={19} />} label={t("Upcoming")} hint={state.profile?.proactive ? t("Background work is on") : t("Background work is off")} onClick={() => onPick("upcoming")} />
      </ul>
      <ul className="mt-3 divide-y divide-border/70 rounded-3xl border border-border/70 overflow-hidden">
        <MenuRow icon={<Brain size={19} />} label={t("Memory")} hint={t("What {name} remembers about you", { name })} onClick={onMemory} />
        {state.settings?.skills?.enabled !== false && (
          <MenuRow
            icon={<Wand2 size={19} />}
            label={t("Skills")}
            hint={
              state.settings?.skills
                ? t("{n} ways of doing a job, {yours} of them yours", { n: state.settings.skills.count, yours: state.settings.skills.yours })
                : t("How {name} does a job, written down once", { name })
            }
            onClick={onSkills}
          />
        )}
        <MenuRow
          icon={<Plug size={19} />}
          label={t("Connections")}
          hint={connected.length ? t("Model, {list}", { list: connected.join(", ") }) : t("Model, email, calendar, browser, MCP servers")}
          onClick={onConnections}
        />
        <MenuRow icon={<SlidersHorizontal size={19} />} label={t("Settings")} hint={t("Name, style, how careful it is")} onClick={onSettings} />
      </ul>
    </div>
  );
}

function MenuRow({ icon, label, hint, badge, onClick }: { icon: ReactNode; label: string; hint: string; badge?: number; onClick: () => void }) {
  return (
    <li>
      <button type="button" onClick={onClick} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface-2/60 active:bg-surface-2">
        <span className="text-accent">{icon}</span>
        <span className="min-w-0 flex-1">
          <span className="block text-[15px] font-medium leading-tight">{label}</span>
          <span className="block text-[12.5px] text-muted truncate">{hint}</span>
        </span>
        {badge ? <span className="rounded-full bg-rose-500 px-2 py-0.5 text-[11.5px] font-bold text-white">{badge}</span> : null}
        <ChevronRight size={17} className="text-muted" />
      </button>
    </li>
  );
}

// ------------------------------------------------------------------ approvals queue
function ApprovalsView({ onDone }: { onDone: () => void }) {
  const { state, decide, openThread, toast } = useStore();
  const t = useT();
  const list = [...state.pendingApprovals].sort((a, b) => a.ts.localeCompare(b.ts));
  const titleOf = (id: string) => {
    const th = state.threads.find((x) => x.id === id);
    return th ? (th.id === "main" ? t(th.title) : th.title) : id;
  };

  useEffect(() => {
    if (list.length === 0) {
      const timer = window.setTimeout(onDone, 600);
      return () => window.clearTimeout(timer);
    }
  }, [list.length, onDone]);

  if (list.length === 0) {
    return (
      <div className="py-10 text-center text-muted text-[14px]">
        <Check size={26} className="mx-auto mb-2 text-emerald-500" />
        {t("Nothing is waiting for you.")}
      </div>
    );
  }
  return (
    <div className="space-y-4 pb-2">
      <p className="text-[12.5px] text-muted">
        {t("Actions your OpenMuse wants to take but cannot without you. Each one shows what will run and why; a permission you grant is bound to that exact tool and target.")}
      </p>
      {list.map((ev) => (
        <div key={ev.id}>
          <button type="button" onClick={() => openThread(ev.thread)} className="mb-1 px-1 text-[12px] font-semibold uppercase tracking-wide text-muted hover:text-accent">
            {titleOf(ev.thread)} · {timeShort(ev.ts)}
          </button>
          <div className="-ml-11 -mr-8">
            <ApprovalCard event={ev} onDecide={(approved, scope) => decide(ev.id, approved, scope).catch((e: Error) => toast(e.message))} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ upcoming
function UpcomingView({ onSettings }: { onSettings: () => void }) {
  const { state, refreshSettings, toast } = useStore();
  const [data, setData] = useState<UpcomingData | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const name = state.profile?.name ?? "OpenMuse";
  const t = useT();

  const load = () => api.upcoming().then(setData).catch((e: Error) => toast(e.message));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.goalsVersion, state.remindersVersion, state.profile?.proactive, state.profile?.goal_interval_minutes]);

  const toggle = async () => {
    try {
      await api.updateSettings({ profile: { proactive: !state.profile?.proactive } });
      await refreshSettings();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const runNow = async (goalId: string) => {
    setBusy(goalId);
    try {
      await api.advanceGoal(goalId);
      toast(t("{name} is working on it in the main chat", { name }));
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (!data) {
    return (
      <div className="py-10 flex justify-center text-muted">
        <Loader2 className="animate-spin" size={20} />
      </div>
    );
  }
  return (
    <div className="space-y-4 pb-2">
      <div className="rounded-2xl border border-border p-3.5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="font-medium">{t("Background work")}</div>
            <div className="text-[12.5px] text-muted">
              {data.proactive
                ? `${t(data.proactivity[0].toUpperCase() + data.proactivity.slice(1))} · ${t("every {n} min {name} picks one active goal and works on its next step.", { n: data.effective_interval_minutes, name })}${
                    data.quiet_until
                      ? ` ${t("Quiet hours until {time}.", { time: timeShort(data.quiet_until) })}`
                      : data.next_pass_at
                        ? ` ${t("Next around {time}.", { time: timeShort(data.next_pass_at) })}`
                        : ""
                  }`
                : t("Off. {name} only works when you ask.", { name })}
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={data.proactive}
            onClick={() => void toggle()}
            className={cx("relative h-7 w-12 shrink-0 rounded-full transition", data.proactive ? "bg-accent" : "bg-border")}
          >
            <span className={cx("absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition", data.proactive ? "left-[26px]" : "left-0.5")} />
          </button>
        </div>
        <button type="button" onClick={onSettings} className="mt-2 text-[12.5px] text-accent font-medium">
          {t("Level, interval and quiet hours in Settings")}
        </button>
      </div>

      <div>
        <div className="text-[12px] uppercase tracking-wide text-muted font-semibold mb-1.5">{t("In line")}</div>
        {data.queue.length === 0 ? (
          <div className="text-[13px] text-muted">{t("No active goal has a next step. Add one in Goals and {name} will pick it up.", { name })}</div>
        ) : (
          <ul className="space-y-1.5">
            {data.queue.map((g, i) => (
              <li key={g.goal_id} className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
                <span className="w-5 text-center text-[12px] font-semibold text-muted">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium truncate">{g.title}</div>
                  <div className="text-[11.5px] text-muted truncate">
                    {g.next_step ?? "—"} · {t("{done}/{total} done", { done: g.progress.done, total: g.progress.total })}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void runNow(g.goal_id)}
                  disabled={busy !== null || data.busy}
                  aria-label={t("Work on {title} now", { title: g.title })}
                  className="rounded-full bg-accent/12 p-2 text-accent disabled:opacity-50"
                >
                  {busy === g.goal_id ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {data.check_ins.length > 0 && (
        <div>
          <div className="text-[12px] uppercase tracking-wide text-muted font-semibold mb-1.5">{t("Check-ins")}</div>
          <ul className="space-y-1.5">
            {data.check_ins.map((c) => (
              <li key={c.goal_id} className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
                <Bell size={15} className="text-muted shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium truncate">{c.title}</div>
                  <div className="text-[11.5px] text-muted truncate">
                    {relativeTime(c.at)} · {timeShort(c.at)} · {describeCadence(c.cadence).toLowerCase()}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <div className="mt-1.5 text-[12px] text-muted">{t("Goal nudges you asked for; they arrive whatever the proactivity level, but wait out quiet hours.")}</div>
        </div>
      )}

      <RemindersSection items={data.reminders} name={name} onChange={() => void load()} />
      <TriggersSection data={data.triggers} name={name} onChange={() => void load()} />
    </div>
  );
}

// ------------------------------------------------------------------ reminders & routines
function RemindersSection({ items, name, onChange }: { items: Reminder[]; name: string; onChange: () => void }) {
  const { toast } = useStore();
  const t = useT();
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const active = items.filter((r) => r.status === "active");
  const finished = items.filter((r) => r.status !== "active");

  const cancel = async (r: Reminder) => {
    setBusy(r.id);
    try {
      await api.cancelReminder(r.id);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const fireNow = async (r: Reminder) => {
    setBusy(r.id);
    try {
      await api.fireReminder(r.id);
      toast(r.kind === "task" ? t("{name} is on it", { name }) : t("{name} will say it now", { name }));
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[12px] uppercase tracking-wide text-muted font-semibold">{t("Reminders & routines")}</div>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)} className="text-[12.5px] text-accent font-medium">
            {t("+ Add")}
          </button>
        )}
      </div>
      {adding && (
        <ReminderForm
          onDone={() => {
            setAdding(false);
            onChange();
          }}
          onCancel={() => setAdding(false)}
        />
      )}
      {active.length === 0 && !adding ? (
        <div className="text-[13px] text-muted">
          {t("Nothing scheduled. Tell {name} “remind me at six to call mum” or “every weekday morning, summarise my unread email”.", { name })}
        </div>
      ) : (
        <ul className="space-y-1.5">
          {active.map((r) => (
            <li key={r.id} className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
              {r.kind === "task" ? <Repeat size={15} className="text-muted shrink-0" /> : <AlarmClock size={15} className="text-muted shrink-0" />}
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium truncate">{r.text}</div>
                <div className="text-[11.5px] text-muted truncate">
                  {r.next_at ? `${relativeTime(r.next_at)} · ${timeShort(r.next_at)}` : "—"}
                  {r.repeat && ` · ${describeCadence(r.repeat).toLowerCase()}`}
                  {r.kind === "task" && ` · ${t("does the work")}`}
                </div>
              </div>
              <button
                type="button"
                onClick={() => void fireNow(r)}
                disabled={busy !== null}
                aria-label={r.kind === "task" ? t("Do “{text}” now", { text: r.text }) : t("Remind me now: {text}", { text: r.text })}
                className="rounded-full bg-accent/12 p-2 text-accent disabled:opacity-50"
              >
                {busy === r.id ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
              </button>
              <button
                type="button"
                onClick={() => void cancel(r)}
                disabled={busy !== null}
                aria-label={t("Cancel: {text}", { text: r.text })}
                className="rounded-full p-2 text-muted hover:text-fg disabled:opacity-50"
              >
                <X size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {finished.length > 0 && (
        <details className="mt-2">
          <summary className="text-[12px] text-muted cursor-pointer select-none">
            {t("{n} finished recently", { n: finished.length })}
          </summary>
          <ul className="mt-1.5 space-y-1">
            {finished.map((r) => (
              <li key={r.id} className="flex items-center gap-2 px-3 text-[12.5px] text-muted">
                <span className="min-w-0 flex-1 truncate line-through decoration-border">{r.text}</span>
                <span className="shrink-0">{r.status === "done" ? (r.last_fired_at ? relativeTime(r.last_fired_at) : t("done")) : t("cancelled")}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="mt-1.5 text-[12px] text-muted">
        {t("A time you named is kept whatever the level or the quiet hours. Reminders just say it; routines do the work and report.")}
      </div>
    </div>
  );
}

function ReminderForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { toast } = useStore();
  const t = useT();
  const [text, setText] = useState("");
  const [kind, setKind] = useState<ReminderKind>("remind");
  const [mode, setMode] = useState<"once" | "repeat">("once");
  const [at, setAt] = useState(() => defaultAt());
  const [cadence, setCadence] = useState("daily");
  const [time, setTime] = useState("09:00");
  const [weekday, setWeekday] = useState("mon");
  const [day, setDay] = useState("1");
  const [saving, setSaving] = useState(false);

  const repeat =
    cadence === "weekly" ? `weekly ${weekday} ${time}` : cadence === "monthly" ? `monthly ${day} ${time}` : `${cadence} ${time}`;

  const submit = async () => {
    if (!text.trim()) return;
    setSaving(true);
    try {
      await api.createReminder(
        mode === "once" ? { text: text.trim(), kind, at: at.replace("T", " ") } : { text: text.trim(), kind, repeat },
      );
      onDone();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const field = "h-9 rounded-xl bg-surface border border-border px-3 text-[13px] outline-none focus:border-accent";
  return (
    <div className="mb-2 rounded-2xl border border-border p-3 space-y-2">
      <input
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={kind === "task" ? t("What should be done…") : t("What to remind you of…")}
        className={cx(field, "w-full h-10 text-[14px]")}
      />
      <div className="flex gap-1.5 text-[12.5px]">
        <Segment options={[["remind", t("Remind me")], ["task", t("Do it for me")]]} value={kind} onChange={(v) => setKind(v as ReminderKind)} />
        <Segment options={[["once", t("Once")], ["repeat", t("Repeat")]]} value={mode} onChange={(v) => setMode(v as "once" | "repeat")} />
      </div>
      {mode === "once" ? (
        <input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} className={cx(field, "w-full")} />
      ) : (
        <div className="flex flex-wrap gap-1.5">
          <select value={cadence} onChange={(e) => setCadence(e.target.value)} className={field}>
            <option value="daily">{t("Every day")}</option>
            <option value="weekdays">{t("Weekdays")}</option>
            <option value="weekly">{t("Weekly")}</option>
            <option value="monthly">{t("Monthly")}</option>
          </select>
          {cadence === "weekly" && (
            <select value={weekday} onChange={(e) => setWeekday(e.target.value)} className={field}>
              {["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((d, i) => (
                <option key={d} value={d}>
                  {new Date(2024, 0, 1 + i).toLocaleDateString(intlLocale(), { weekday: "long" })}
                </option>
              ))}
            </select>
          )}
          {cadence === "monthly" && (
            <select value={day} onChange={(e) => setDay(e.target.value)} className={field}>
              {Array.from({ length: 28 }, (_, i) => String(i + 1)).map((d) => (
                <option key={d} value={d}>
                  {t("Day {d}", { d })}
                </option>
              ))}
            </select>
          )}
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={field} />
        </div>
      )}
      <div className="flex justify-end gap-2 pt-0.5">
        <button type="button" onClick={onCancel} className="rounded-full px-3 py-1.5 text-[13px] text-muted">
          {t("Cancel")}
        </button>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={saving || !text.trim()}
          className="rounded-full bg-accent px-3.5 py-1.5 text-[13px] font-medium text-accent-fg disabled:opacity-50"
        >
          {saving ? t("Saving…") : mode === "once" ? t("Set reminder") : t("Set routine")}
        </button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ triggers
const TRIGGER_ICON: Record<TriggerKind, typeof Mail> = { mail: Mail, event: CalendarClock, hook: Webhook };

/** The condition in words, for the list and the confirmation line of the form. */
export function describeTrigger(tr: Pick<Trigger, "kind" | "match" | "lead_minutes">, t: (k: string, v?: Record<string, string | number>) => string): string {
  if (tr.kind === "mail") return tr.match ? t("mail matching “{match}”", { match: tr.match }) : t("any new mail");
  if (tr.kind === "event") {
    const what = tr.match ? t("events matching “{match}”", { match: tr.match }) : t("any event");
    return t("{n} min before {what}", { n: tr.lead_minutes, what });
  }
  return tr.match ? t("webhook “{match}”", { match: tr.match }) : t("webhook");
}

function TriggersSection({ data, name, onChange }: { data: TriggersData; name: string; onChange: () => void }) {
  const { toast } = useStore();
  const t = useT();
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const active = data.items.filter((r) => r.status === "active");
  const watching = active.some((r) => r.kind === "mail");

  const cancel = async (r: Trigger) => {
    setBusy(r.id);
    try {
      await api.cancelTrigger(r.id);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const fireNow = async (r: Trigger) => {
    setBusy(r.id);
    try {
      await api.fireTrigger(r.id);
      toast(t("{name} is on it", { name }));
      onChange();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const copy = async (r: Trigger) => {
    if (!r.url) return;
    try {
      await navigator.clipboard.writeText(r.url);
      toast(t("Webhook URL copied"));
    } catch {
      toast(r.url);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[12px] uppercase tracking-wide text-muted font-semibold">{t("When something happens")}</div>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)} className="text-[12.5px] text-accent font-medium">
            {t("+ Add")}
          </button>
        )}
      </div>
      {adding && (
        <TriggerForm
          available={data.available}
          onDone={() => {
            setAdding(false);
            onChange();
          }}
          onCancel={() => setAdding(false)}
        />
      )}
      {active.length === 0 && !adding ? (
        <div className="text-[13px] text-muted">
          {t("Nothing yet. Tell {name} “when the landlord writes back, summarise it and draft a reply” or “half an hour before any review, brief me”.", { name })}
        </div>
      ) : (
        <ul className="space-y-1.5">
          {active.map((r) => {
            const Icon = TRIGGER_ICON[r.kind];
            return (
              <li key={r.id} className="flex items-start gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
                <Icon size={15} className="text-muted shrink-0 mt-[3px]" />
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium">{describeTrigger(r, t)}</div>
                  <div className="text-[12px] leading-snug text-fg/80 line-clamp-2">{r.text}</div>
                  <div className="text-[11.5px] text-muted flex flex-wrap items-center gap-x-1.5">
                    {r.fired > 0 ? (
                      <span>
                        {t("fired {n}×", { n: r.fired })}
                        {r.last_fired_at && ` · ${relativeTime(r.last_fired_at)}`}
                      </span>
                    ) : (
                      <span>{t("not fired yet")}</span>
                    )}
                    {r.kind === "hook" && r.url && (
                      <button type="button" onClick={() => void copy(r)} className="inline-flex items-center gap-1 text-accent font-medium">
                        <Copy size={11} /> {t("Copy URL")}
                      </button>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void fireNow(r)}
                  disabled={busy !== null}
                  aria-label={t("Run now: {text}", { text: r.text })}
                  className="rounded-full bg-accent/12 p-2 text-accent disabled:opacity-50"
                >
                  {busy === r.id ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
                </button>
                <button
                  type="button"
                  onClick={() => void cancel(r)}
                  disabled={busy !== null}
                  aria-label={t("Cancel: {text}", { text: r.text })}
                  className="rounded-full p-2 text-muted hover:text-fg disabled:opacity-50"
                >
                  <X size={15} />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {watching && (
        <div className={cx("mt-1.5 text-[12px]", data.mail_error ? "text-rose-500" : "text-muted")}>
          {data.mail_error
            ? t("The inbox could not be read: {error}", { error: data.mail_error })
            : data.mail_checked_at
              ? t("Inbox checked {when}; {name} looks every {n} min.", { when: relativeTime(data.mail_checked_at), name, n: data.mail_poll_minutes })
              : t("{name} will look at the inbox shortly, then every {n} min.", { name, n: data.mail_poll_minutes })}
        </div>
      )}
      <div className="mt-1.5 text-[12px] text-muted">
        {t("Each time it happens {name} does the work in the chat it was set from and reports in the Feed. A mail or a request is treated as data, never as instructions.", { name })}
      </div>
    </div>
  );
}

function TriggerForm({ available, onDone, onCancel }: { available: Record<TriggerKind, boolean>; onDone: () => void; onCancel: () => void }) {
  const { toast } = useStore();
  const t = useT();
  const firstKind = (["mail", "event", "hook"] as TriggerKind[]).find((k) => available[k]) ?? "hook";
  const [kind, setKind] = useState<TriggerKind>(firstKind);
  const [match, setMatch] = useState("");
  const [lead, setLead] = useState("30");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [made, setMade] = useState<Trigger | null>(null);

  const submit = async () => {
    if (!text.trim()) return;
    setSaving(true);
    try {
      const tr = await api.createTrigger({ kind, text: text.trim(), match: match.trim(), lead_minutes: Number(lead) || 30 });
      if (tr.kind === "hook" && tr.url) setMade(tr);
      else onDone();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const field = "h-9 rounded-xl bg-surface border border-border px-3 text-[13px] outline-none focus:border-accent";
  if (made) {
    return (
      <div className="mb-2 rounded-2xl border border-border p-3 space-y-2">
        <div className="text-[13.5px] font-medium">{t("Webhook ready")}</div>
        <div className="text-[12.5px] text-muted">{t("POST anything to this URL and the work starts. The key is in the URL — share it only with the program that will call it.")}</div>
        <code className="block break-all rounded-xl bg-surface-2 px-3 py-2 text-[12px]">{made.url}</code>
        <div className="flex justify-end gap-2 pt-0.5">
          <button
            type="button"
            onClick={() => void navigator.clipboard.writeText(made.url ?? "").then(() => toast(t("Webhook URL copied")), () => toast(made.url ?? ""))}
            className="rounded-full px-3 py-1.5 text-[13px] text-accent font-medium"
          >
            {t("Copy")}
          </button>
          <button type="button" onClick={onDone} className="rounded-full bg-accent px-3.5 py-1.5 text-[13px] font-medium text-accent-fg">
            {t("Done")}
          </button>
        </div>
      </div>
    );
  }
  const kinds: Array<[TriggerKind, string]> = [
    ["mail", t("New mail")],
    ["event", t("Before an event")],
    ["hook", t("Webhook")],
  ];
  return (
    <div className="mb-2 rounded-2xl border border-border p-3 space-y-2">
      <Segment options={kinds} value={kind} onChange={(v) => setKind(v as TriggerKind)} />
      {!available[kind] && (
        <div className="text-[12.5px] text-rose-500">
          {kind === "mail" ? t("Connect a mailbox under Connections first.") : t("Add a calendar under Connections first.")}
        </div>
      )}
      <div className="flex gap-1.5">
        <input
          value={match}
          onChange={(e) => setMatch(e.target.value)}
          placeholder={kind === "mail" ? t("Words in the sender or subject (empty: any mail)") : kind === "event" ? t("Words in the title or place (empty: any event)") : t("A name for this hook")}
          className={cx(field, "min-w-0 flex-1")}
        />
        {kind === "event" && (
          <label className="flex items-center gap-1 text-[12.5px] text-muted">
            <input type="number" min={0} max={1440} value={lead} onChange={(e) => setLead(e.target.value)} className={cx(field, "w-[64px] px-2")} aria-label={t("Minutes before")} />
            {t("min before")}
          </label>
        )}
      </div>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("What should be done each time…")}
        className={cx(field, "w-full h-10 text-[14px]")}
      />
      <div className="text-[12px] text-muted">{t("When {condition}", { condition: describeTrigger({ kind, match: match.trim(), lead_minutes: Number(lead) || 30 }, t) })}</div>
      <div className="flex justify-end gap-2 pt-0.5">
        <button type="button" onClick={onCancel} className="rounded-full px-3 py-1.5 text-[13px] text-muted">
          {t("Cancel")}
        </button>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={saving || !text.trim() || !available[kind]}
          className="rounded-full bg-accent px-3.5 py-1.5 text-[13px] font-medium text-accent-fg disabled:opacity-50"
        >
          {saving ? t("Saving…") : t("Set trigger")}
        </button>
      </div>
    </div>
  );
}

function Segment({ options, value, onChange }: { options: Array<[string, string]>; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex rounded-full bg-surface-2 p-0.5">
      {options.map(([v, label]) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cx("rounded-full px-2.5 py-1 transition", value === v ? "bg-surface shadow-sm font-medium" : "text-muted")}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** An hour from now, on the next full hour, as datetime-local wants it (local time, no zone). */
function defaultAt(): string {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setMinutes(0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ------------------------------------------------------------------ activity log
function useActivity(open: boolean): [ActivityData | null, () => Promise<void>] {
  const [data, setData] = useState<ActivityData | null>(null);
  const load = async () => {
    try {
      setData(await api.activity(150));
    } catch {
      /* offline */
    }
  };
  useEffect(() => {
    if (!open) return;
    void load();
    const t = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  return [data, load];
}

function ActivityView({ open }: { open: boolean }) {
  const [data] = useActivity(open);
  const t = useT();
  const entries = (data?.audit ?? []).filter((e) => e.event === "tool_call").reverse();
  return (
    <div className="pb-2">
      <p className="text-[12.5px] text-muted mb-2">
        {t("Every tool call goes through the Sentinel and is written to the audit log — including the ones it refused.")}
      </p>
      {data && entries.length === 0 && <div className="py-8 text-center text-muted text-[14px]">{t("Nothing yet.")}</div>}
      <ul className="space-y-1.5">
        {entries.map((e, i) => (
          <AuditRow key={`${e.ts}-${i}`} entry={e} />
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ permissions
function PermissionsView({ open }: { open: boolean }) {
  const { state, toast } = useStore();
  const t = useT();
  const [data, reload] = useActivity(open);

  const reset = async () => {
    if (!window.confirm(t("Forget every permission you granted? Your OpenMuse will ask again next time."))) return;
    try {
      await api.resetApprovals();
      await reload();
      toast(t("Permissions reset"));
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const revoke = async (g: Grant) => {
    try {
      await api.revokeGrant(g.key);
      await reload();
      toast(t("Revoked: {subject}", { subject: grantSubject(g.tool, g.target) }));
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const mode = state.settings?.sentinel.mode;
  return (
    <div className="space-y-4 pb-2">
      <div className="rounded-2xl border border-border p-3.5">
        <div className="flex items-center gap-2 font-medium">
          <ShieldCheck size={18} className="text-accent" /> {t("Sentinel mode:")} <span className="capitalize">{mode === "ask" ? t("balanced") : mode === "strict" ? t("cautious") : mode === "auto" ? t("hands-off") : mode}</span>
        </div>
        <p className="mt-1 text-[12.5px] text-muted">
          {mode === "ask" && t("Safe and moderate actions run freely; anything sensitive (email, shell, purchases) waits for you.")}
          {mode === "strict" && t("Moderate and sensitive actions both wait for your approval.")}
          {mode === "auto" && t("Everything is approved automatically except explicit deny rules. Use with care.")}
        </p>
        {data?.tainted && (
          <p className="mt-2 text-[12.5px] text-amber-600 dark:text-amber-300 flex items-center gap-1.5">
            <ShieldOff size={14} /> {t("Private data was read this session: network calls to new destinations need approval.")}
          </p>
        )}
      </div>
      <GrantList grants={data?.grants ?? []} onRevoke={revoke} />
      <PermissionList title={t("Always ask (from config)")} tools={state.settings?.sentinel.always_ask_tools ?? []} muted />
      {(data?.grants.length ?? 0) > 0 && (
        <button type="button" onClick={() => void reset()} className="w-full rounded-2xl border border-border py-2.5 text-[14px] font-medium">
          {t("Reset all granted permissions")}
        </button>
      )}
    </div>
  );
}

function grantUntil(g: Grant, t: (key: string, vars?: Record<string, string | number>) => string): string {
  switch (g.scope) {
    case "task":
      return t("for the current task");
    case "session":
      return t("until restart");
    case "24h":
      return g.expires_at ? t("until {time}", { time: timeShort(g.expires_at) }) : t("for 24 hours");
    case "always":
      return t("always");
    default:
      return g.scope;
  }
}

/** Every standing permission you granted, one row each, revocable on its own. */
function GrantList({ grants, onRevoke }: { grants: Grant[]; onRevoke: (g: Grant) => void }) {
  const t = useT();
  return (
    <div>
      <div className="text-[12px] uppercase tracking-wide text-muted font-semibold mb-1.5">{t("Permissions you granted")}</div>
      {grants.length === 0 ? (
        <div className="text-[13px] text-muted">{t("None. Approvals you give “once” are not kept.")}</div>
      ) : (
        <ul className="space-y-1.5">
          {grants.map((g) => (
            <li key={g.key} className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
              <span className="text-accent">{toolIcon(g.tool, 15)}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium truncate">{grantSubject(g.tool, g.target)}</div>
                <div className="text-[11.5px] text-muted">
                  {g.tool} · {grantUntil(g, t)} · {t("granted {time}", { time: timeShort(g.granted_at) })}
                </div>
              </div>
              <button
                type="button"
                aria-label={t("Revoke {what}", { what: scopeLabel(g.scope, g.tool, g.target) })}
                onClick={() => onRevoke(g)}
                className="rounded-full p-1.5 text-muted hover:bg-surface active:scale-95"
              >
                <X size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PermissionList({ title, tools, muted }: { title: string; tools: string[]; muted?: boolean }) {
  const t = useT();
  return (
    <div>
      <div className="text-[12px] uppercase tracking-wide text-muted font-semibold mb-1.5">{title}</div>
      {tools.length === 0 ? (
        <div className="text-[13px] text-muted">{t("None")}</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {tools.map((tool) => (
            <span key={tool} className={cx("rounded-full px-2.5 py-1 text-[12.5px] flex items-center gap-1", muted ? "bg-surface-2 text-muted" : "bg-accent/12 text-accent")}>
              {toolIcon(tool, 12)} {tool}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  const t = useT();
  const denied = entry.decision === "deny";
  const failed = entry.ok === false && !denied;
  return (
    <li className="flex items-start gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
      <div className={cx("mt-0.5", denied ? "text-rose-500" : failed ? "text-amber-500" : "text-muted")}>
        {denied || failed ? <Ban size={15} /> : <Check size={15} />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[13.5px]">
          <span className="text-muted">{toolIcon(entry.tool ?? "", 13)}</span>
          <span className="font-medium truncate">{entry.summary || entry.tool}</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-muted">
          <span>{timeShort(entry.ts)}</span>
          {entry.risk && <RiskBadge risk={entry.risk as RiskLevel} />}
          {entry.approved === true && (
            <span className="text-emerald-600 dark:text-emerald-300">
              {t("approved by you")}{entry.approval_scope && entry.approval_scope !== "once" ? ` (${entry.approval_scope})` : ""}
            </span>
          )}
          {entry.approved == null && entry.approval_scope && entry.approval_scope !== "once" && (
            <span className="text-emerald-600 dark:text-emerald-300">{t("covered by your {scope} permission", { scope: entry.approval_scope })}</span>
          )}
          {denied && <span className="text-rose-500">{t("blocked")}</span>}
          {failed && <span className="text-amber-600">{t("failed")}</span>}
          {typeof entry.duration_ms === "number" && <span>{(entry.duration_ms / 1000).toFixed(1)}s</span>}
        </div>
        {denied && entry.reasons && entry.reasons.length > 0 && <div className="mt-0.5 text-[12px] text-muted">{entry.reasons.join(" · ")}</div>}
      </div>
    </li>
  );
}
