import {
  Ban,
  Bell,
  Brain,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Loader2,
  Play,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { Avatar } from "../components/Avatar";
import { ApprovalCard, RiskBadge, grantSubject, scopeLabel, toolIcon } from "../components/Cards";
import { Sheet } from "../components/Sheet";
import { useStore } from "../store";
import type { ActivityData, AuditEntry, Grant, RiskLevel, UpcomingData } from "../types";
import { cx, timeShort } from "../util";

type View = "menu" | "activity" | "approvals" | "permissions" | "upcoming";

/**
 * Tap the avatar: the menu behind your Muse. What it has been doing (activity log),
 * what is waiting for you (approvals queue, across every chat), what it is allowed to do
 * (permissions), what it will do next (upcoming), plus its memory and settings.
 */
export function MuseSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { state, setTab } = useStore();
  const [view, setView] = useState<View>("menu");
  const name = state.profile?.name ?? "Muse";
  const pending = state.pendingApprovals.length;

  useEffect(() => {
    if (open) setView(pending > 0 ? "approvals" : "menu");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const go = (tab: "memory" | "you") => {
    onClose();
    setTab(tab);
  };

  const titles: Record<View, string> = {
    menu: name,
    activity: "Activity",
    approvals: "Approvals",
    permissions: "Permissions",
    upcoming: "Upcoming",
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center gap-1.5">
          {view !== "menu" && (
            <button type="button" onClick={() => setView("menu")} aria-label="Back" className="-ml-2 p-1 rounded-full text-muted hover:bg-surface-2">
              <ChevronLeft size={20} />
            </button>
          )}
          <span>{titles[view]}</span>
          {view === "menu" && (
            <span className="text-[12px] font-normal text-muted">
              {state.status.state === "idle" ? "idle" : state.status.detail || state.status.state}
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
  onSettings,
}: {
  name: string;
  pending: number;
  onPick: (v: View) => void;
  onMemory: () => void;
  onSettings: () => void;
}) {
  const { state } = useStore();
  const mode = state.settings?.sentinel.mode;
  return (
    <div className="pb-2">
      <div className="flex items-center gap-3 rounded-3xl bg-surface-2/70 px-4 py-3">
        <Avatar profile={state.profile} status={state.status} size={48} />
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-[16px] truncate">{name}</div>
          <div className="text-[12.5px] text-muted truncate">
            {state.settings?.llm.model ?? "—"} · {mode === "ask" ? "balanced" : mode === "strict" ? "cautious" : mode === "auto" ? "hands-off" : ""}
          </div>
        </div>
      </div>
      <ul className="mt-3 divide-y divide-border/70 rounded-3xl border border-border/70 overflow-hidden">
        <MenuRow icon={<ShieldAlert size={19} />} label="Approvals" hint={pending ? `${pending} waiting for you` : "Nothing waiting"} badge={pending} onClick={() => onPick("approvals")} />
        <MenuRow icon={<ClipboardList size={19} />} label="Activity" hint="Every action, including refused ones" onClick={() => onPick("activity")} />
        <MenuRow icon={<ShieldCheck size={19} />} label="Permissions" hint="What you allowed, revoke any time" onClick={() => onPick("permissions")} />
        <MenuRow icon={<Bell size={19} />} label="Upcoming" hint={state.profile?.proactive ? "Background work is on" : "Background work is off"} onClick={() => onPick("upcoming")} />
      </ul>
      <ul className="mt-3 divide-y divide-border/70 rounded-3xl border border-border/70 overflow-hidden">
        <MenuRow icon={<Brain size={19} />} label="Memory" hint={`What ${name} remembers about you`} onClick={onMemory} />
        <MenuRow icon={<SlidersHorizontal size={19} />} label="Settings" hint="Name, style, how careful it is" onClick={onSettings} />
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
  const list = [...state.pendingApprovals].sort((a, b) => a.ts.localeCompare(b.ts));
  const titleOf = (id: string) => state.threads.find((t) => t.id === id)?.title ?? id;

  useEffect(() => {
    if (list.length === 0) {
      const t = window.setTimeout(onDone, 600);
      return () => window.clearTimeout(t);
    }
  }, [list.length, onDone]);

  if (list.length === 0) {
    return (
      <div className="py-10 text-center text-muted text-[14px]">
        <Check size={26} className="mx-auto mb-2 text-emerald-500" />
        Nothing is waiting for you.
      </div>
    );
  }
  return (
    <div className="space-y-4 pb-2">
      <p className="text-[12.5px] text-muted">
        Actions your Muse wants to take but cannot without you. Each one shows what will run and why; a permission you grant is bound to that exact tool and target.
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
  const name = state.profile?.name ?? "Muse";

  const load = () => api.upcoming().then(setData).catch((e: Error) => toast(e.message));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.goalsVersion, state.profile?.proactive, state.profile?.goal_interval_minutes]);

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
      toast(`${name} is working on it in the main chat`);
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
            <div className="font-medium">Background work</div>
            <div className="text-[12.5px] text-muted">
              {data.proactive
                ? `Every ${data.interval_minutes} min ${name} picks one active goal and works on its next step.${data.next_pass_at ? ` Next around ${timeShort(data.next_pass_at)}.` : ""}`
                : `Off. ${name} only works when you ask.`}
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
          Change how often in Settings
        </button>
      </div>

      <div>
        <div className="text-[12px] uppercase tracking-wide text-muted font-semibold mb-1.5">In line</div>
        {data.queue.length === 0 ? (
          <div className="text-[13px] text-muted">No active goal has a next step. Add one in Goals and {name} will pick it up.</div>
        ) : (
          <ul className="space-y-1.5">
            {data.queue.map((g, i) => (
              <li key={g.goal_id} className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
                <span className="w-5 text-center text-[12px] font-semibold text-muted">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium truncate">{g.title}</div>
                  <div className="text-[11.5px] text-muted truncate">
                    {g.next_step ?? "—"} · {g.progress.done}/{g.progress.total} done
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void runNow(g.goal_id)}
                  disabled={busy !== null || data.busy}
                  aria-label={`Work on ${g.title} now`}
                  className="rounded-full bg-accent/12 p-2 text-accent disabled:opacity-50"
                >
                  {busy === g.goal_id ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
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
  const entries = (data?.audit ?? []).filter((e) => e.event === "tool_call").reverse();
  return (
    <div className="pb-2">
      <p className="text-[12.5px] text-muted mb-2">
        Every tool call goes through the Sentinel and is written to the audit log — including the ones it refused.
      </p>
      {data && entries.length === 0 && <div className="py-8 text-center text-muted text-[14px]">Nothing yet.</div>}
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
  const [data, reload] = useActivity(open);

  const reset = async () => {
    if (!window.confirm("Forget every permission you granted? Your Muse will ask again next time.")) return;
    try {
      await api.resetApprovals();
      await reload();
      toast("Permissions reset");
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const revoke = async (g: Grant) => {
    try {
      await api.revokeGrant(g.key);
      await reload();
      toast(`Revoked: ${grantSubject(g.tool, g.target)}`);
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const mode = state.settings?.sentinel.mode;
  return (
    <div className="space-y-4 pb-2">
      <div className="rounded-2xl border border-border p-3.5">
        <div className="flex items-center gap-2 font-medium">
          <ShieldCheck size={18} className="text-accent" /> Sentinel mode: <span className="capitalize">{mode}</span>
        </div>
        <p className="mt-1 text-[12.5px] text-muted">
          {mode === "ask" && "Safe and moderate actions run freely; anything sensitive (email, shell, purchases) waits for you."}
          {mode === "strict" && "Moderate and sensitive actions both wait for your approval."}
          {mode === "auto" && "Everything is approved automatically except explicit deny rules. Use with care."}
        </p>
        {data?.tainted && (
          <p className="mt-2 text-[12.5px] text-amber-600 dark:text-amber-300 flex items-center gap-1.5">
            <ShieldOff size={14} /> Private data was read this session: network calls to new destinations need approval.
          </p>
        )}
      </div>
      <GrantList grants={data?.grants ?? []} onRevoke={revoke} />
      <PermissionList title="Always ask (from config)" tools={state.settings?.sentinel.always_ask_tools ?? []} muted />
      {(data?.grants.length ?? 0) > 0 && (
        <button type="button" onClick={() => void reset()} className="w-full rounded-2xl border border-border py-2.5 text-[14px] font-medium">
          Reset all granted permissions
        </button>
      )}
    </div>
  );
}

function grantUntil(g: Grant): string {
  switch (g.scope) {
    case "task":
      return "for the current task";
    case "session":
      return "until restart";
    case "24h":
      return g.expires_at ? `until ${timeShort(g.expires_at)}` : "for 24 hours";
    case "always":
      return "always";
    default:
      return g.scope;
  }
}

/** Every standing permission you granted, one row each, revocable on its own. */
function GrantList({ grants, onRevoke }: { grants: Grant[]; onRevoke: (g: Grant) => void }) {
  return (
    <div>
      <div className="text-[12px] uppercase tracking-wide text-muted font-semibold mb-1.5">Permissions you granted</div>
      {grants.length === 0 ? (
        <div className="text-[13px] text-muted">None. Approvals you give “once” are not kept.</div>
      ) : (
        <ul className="space-y-1.5">
          {grants.map((g) => (
            <li key={g.key} className="flex items-center gap-2.5 rounded-2xl bg-surface-2/60 px-3 py-2">
              <span className="text-accent">{toolIcon(g.tool, 15)}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium truncate">{grantSubject(g.tool, g.target)}</div>
                <div className="text-[11.5px] text-muted">
                  {g.tool} · {grantUntil(g)} · granted {timeShort(g.granted_at)}
                </div>
              </div>
              <button
                type="button"
                aria-label={`Revoke ${scopeLabel(g.scope, g.tool, g.target)}`}
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
  return (
    <div>
      <div className="text-[12px] uppercase tracking-wide text-muted font-semibold mb-1.5">{title}</div>
      {tools.length === 0 ? (
        <div className="text-[13px] text-muted">None</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {tools.map((t) => (
            <span key={t} className={cx("rounded-full px-2.5 py-1 text-[12.5px] flex items-center gap-1", muted ? "bg-surface-2 text-muted" : "bg-accent/12 text-accent")}>
              {toolIcon(t, 12)} {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
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
              approved by you{entry.approval_scope && entry.approval_scope !== "once" ? ` (${entry.approval_scope})` : ""}
            </span>
          )}
          {entry.approved == null && entry.approval_scope && entry.approval_scope !== "once" && (
            <span className="text-emerald-600 dark:text-emerald-300">covered by your {entry.approval_scope} permission</span>
          )}
          {denied && <span className="text-rose-500">blocked</span>}
          {failed && <span className="text-amber-600">failed</span>}
          {typeof entry.duration_ms === "number" && <span>{(entry.duration_ms / 1000).toFixed(1)}s</span>}
        </div>
        {denied && entry.reasons && entry.reasons.length > 0 && <div className="mt-0.5 text-[12px] text-muted">{entry.reasons.join(" · ")}</div>}
      </div>
    </li>
  );
}
