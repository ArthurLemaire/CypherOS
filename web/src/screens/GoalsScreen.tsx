import {
  Bell,
  BellRing,
  Briefcase,
  CalendarDays,
  CheckCircle2,
  Circle,
  CircleDashed,
  CircleSlash,
  Compass,
  GraduationCap,
  Heart,
  HeartHandshake,
  House,
  OctagonAlert,
  Palette,
  Pause,
  PiggyBank,
  Play,
  Plus,
  Sparkles,
  Tag,
  Trash2,
  Users,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { Sheet } from "../components/Sheet";
import { useStore } from "../store";
import type { Goal, GoalCategory, GoalStep } from "../types";
import { cx, relativeTime, timeShort } from "../util";

const STEP_ICON: Record<GoalStep["status"], (p: { size: number; className?: string }) => JSX.Element> = {
  pending: (p) => <Circle {...p} />,
  in_progress: (p) => <CircleDashed {...p} className={cx(p.className, "text-accent")} />,
  done: (p) => <CheckCircle2 {...p} className={cx(p.className, "text-emerald-500")} />,
  blocked: (p) => <OctagonAlert {...p} className={cx(p.className, "text-rose-500")} />,
  skipped: (p) => <CircleSlash {...p} className={cx(p.className, "text-muted")} />,
};

const STEP_NEXT: Record<GoalStep["status"], GoalStep["status"]> = {
  pending: "done",
  in_progress: "done",
  done: "pending",
  blocked: "pending",
  skipped: "pending",
};

/** Muse's life areas. Colours are Tailwind classes so the badge and the filter chip agree. */
export const CATEGORIES: Array<{ id: GoalCategory; label: string; icon: (p: { size: number }) => JSX.Element; tone: string }> = [
  { id: "health", label: "Health", icon: (p) => <Heart {...p} />, tone: "bg-rose-500/12 text-rose-600 dark:text-rose-300" },
  { id: "finance", label: "Finance", icon: (p) => <PiggyBank {...p} />, tone: "bg-emerald-500/12 text-emerald-600 dark:text-emerald-300" },
  { id: "career", label: "Career", icon: (p) => <Briefcase {...p} />, tone: "bg-sky-500/12 text-sky-600 dark:text-sky-300" },
  { id: "learning", label: "Learning", icon: (p) => <GraduationCap {...p} />, tone: "bg-violet-500/12 text-violet-600 dark:text-violet-300" },
  { id: "relationships", label: "Relationships", icon: (p) => <HeartHandshake {...p} />, tone: "bg-pink-500/12 text-pink-600 dark:text-pink-300" },
  { id: "family", label: "Family", icon: (p) => <Users {...p} />, tone: "bg-amber-500/12 text-amber-600 dark:text-amber-300" },
  { id: "home", label: "Home", icon: (p) => <House {...p} />, tone: "bg-orange-500/12 text-orange-600 dark:text-orange-300" },
  { id: "travel", label: "Travel", icon: (p) => <Compass {...p} />, tone: "bg-cyan-500/12 text-cyan-600 dark:text-cyan-300" },
  { id: "creative", label: "Creative", icon: (p) => <Palette {...p} />, tone: "bg-fuchsia-500/12 text-fuchsia-600 dark:text-fuchsia-300" },
  { id: "other", label: "Other", icon: (p) => <Tag {...p} />, tone: "bg-surface-2 text-muted" },
];

export function categoryOf(id: GoalCategory) {
  return CATEGORIES.find((c) => c.id === id) ?? null;
}

const CADENCES = [
  { id: "", label: "No reminders" },
  { id: "daily", label: "Every day" },
  { id: "weekdays", label: "Weekdays" },
  { id: "weekly", label: "Once a week" },
  { id: "monthly", label: "Once a month" },
];
const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

/** "weekly mon 09:00" → parts, and back. */
function splitCadence(spec: string): { cadence: string; anchor: string; time: string } {
  const m = /^(daily|weekdays|weekly|monthly)(?:\s+(\S+?))?(?:\s+(\d{1,2}:\d{2}))?$/.exec(spec.trim());
  if (!m) return { cadence: "", anchor: "", time: "09:00" };
  let anchor = m[2] ?? "";
  let time = m[3] ?? "09:00";
  if (anchor && /^\d{1,2}:\d{2}$/.test(anchor)) {
    time = anchor;
    anchor = "";
  }
  return { cadence: m[1], anchor, time: time.padStart(5, "0") };
}

function joinCadence(cadence: string, anchor: string, time: string): string {
  if (!cadence) return "";
  return [cadence, anchor, time].filter(Boolean).join(" ");
}

export function describeCadence(spec: string): string {
  const { cadence, anchor, time } = splitCadence(spec);
  const day = anchor && WEEKDAYS.includes(anchor) ? anchor[0].toUpperCase() + anchor.slice(1) : anchor;
  switch (cadence) {
    case "daily":
      return `Daily at ${time}`;
    case "weekdays":
      return `Weekdays at ${time}`;
    case "weekly":
      return `${day ? `${day}s` : "Weekly"} at ${time}`;
    case "monthly":
      return `Monthly on the ${anchor || "1"}${ordinal(Number(anchor || 1))} at ${time}`;
    default:
      return "";
  }
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return s[(v - 20) % 10] ?? s[v] ?? s[0];
}

export function dueLabel(due: string, overdue: boolean): string {
  if (!due) return "";
  const d = new Date(`${due}T00:00:00`);
  const label = d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
  if (overdue) return `Was due ${label}`;
  const days = Math.ceil((d.getTime() - Date.now()) / 86_400_000);
  if (days <= 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  if (days <= 14) return `Due in ${days} days`;
  return `By ${label}`;
}

export function GoalsScreen() {
  const { state, refreshGoals, send, openThread, toast } = useStore();
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState<GoalCategory | "all">("all");
  const name = state.profile?.name ?? "Muse";

  useEffect(() => {
    void refreshGoals();
  }, [refreshGoals]);

  const used = new Set(state.goals.map((g) => g.category).filter(Boolean));
  const shown = filter === "all" ? state.goals : state.goals.filter((g) => g.category === filter);
  const proposals = shown.filter((g) => g.proposal && g.status !== "cancelled");
  const active = shown.filter((g) => g.status === "active");
  const paused = shown.filter((g) => g.status === "paused");
  const finished = shown.filter((g) => g.status === "done" || g.status === "cancelled");
  const goal = state.goals.find((g) => g.id === selected) ?? null;

  const advance = async (g: Goal) => {
    try {
      await api.advanceGoal(g.id);
      toast(`${name} is working on “${g.title}” in the main chat`);
      openThread("main");
    } catch (e) {
      toast((e as Error).message);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-4 pb-2 flex items-center gap-3">
        <div className="flex-1">
          <h1 className="text-[24px] font-bold tracking-tight">Goals</h1>
          <p className="text-[13px] text-muted">Long-running things {name} is tracking and moving forward for you.</p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="h-10 w-10 rounded-full bg-accent text-accent-fg flex items-center justify-center active:scale-95 transition"
          aria-label="New goal"
        >
          <Plus size={22} />
        </button>
      </header>

      {used.size > 0 && (
        <div className="shrink-0 flex gap-1.5 overflow-x-auto px-4 pb-2.5 no-scrollbar">
          <Chip active={filter === "all"} onClick={() => setFilter("all")}>
            All
          </Chip>
          {CATEGORIES.filter((c) => used.has(c.id)).map((c) => (
            <Chip key={c.id} active={filter === c.id} onClick={() => setFilter(c.id)}>
              {c.icon({ size: 13 })} {c.label}
            </Chip>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-5">
        {state.goals.length === 0 && (
          <div className="rounded-3xl border border-dashed border-border p-6 text-center">
            <Sparkles className="mx-auto text-accent" />
            <div className="mt-2 font-semibold">No goals yet</div>
            <p className="mt-1 text-[13.5px] text-muted">
              Tell {name} about something you want to achieve — health, money, work, learning, the people in your life — and it will
              break it into steps, keep track, remind you, and keep working on it in the background.
            </p>
            <button
              type="button"
              onClick={() => {
                void send("main", "I want to set up a long-term goal. Ask me about it, then create it with concrete steps using the goals tool.");
                openThread("main");
              }}
              className="mt-3 rounded-full bg-accent text-accent-fg px-4 py-2 text-[14px] font-medium"
            >
              Plan a goal with {name}
            </button>
          </div>
        )}
        {proposals.length > 0 && (
          <section>
            <div className="px-1 mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">{name} suggests</div>
            <div className="space-y-2.5">
              {proposals.map((g) => (
                <ProposalCard key={g.id} goal={g} onChanged={refreshGoals} onOpen={() => setSelected(g.id)} />
              ))}
            </div>
          </section>
        )}
        <GoalGroup title="Active" goals={active} onOpen={setSelected} onAdvance={advance} />
        <GoalGroup title="Paused" goals={paused} onOpen={setSelected} />
        <GoalGroup title="Finished" goals={finished} onOpen={setSelected} />
      </div>

      <GoalDetail goal={goal} onClose={() => setSelected(null)} onAdvance={advance} onChanged={refreshGoals} />
      <NewGoalSheet
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={() => {
          setCreating(false);
          void refreshGoals();
        }}
      />
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "shrink-0 inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-[12.5px] font-medium transition",
        active ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted",
      )}
    >
      {children}
    </button>
  );
}

function CategoryBadge({ id, size = "sm" }: { id: GoalCategory; size?: "sm" | "md" }) {
  const c = categoryOf(id);
  if (!c) return null;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full font-medium", c.tone, size === "sm" ? "px-2 py-0.5 text-[11.5px]" : "px-2.5 py-1 text-[12.5px]")}>
      {c.icon({ size: size === "sm" ? 11 : 13 })} {c.label}
    </span>
  );
}

function GoalGroup({
  title,
  goals,
  onOpen,
  onAdvance,
}: {
  title: string;
  goals: Goal[];
  onOpen: (id: string) => void;
  onAdvance?: (g: Goal) => void;
}) {
  if (!goals.length) return null;
  return (
    <section>
      <div className="px-1 mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">{title}</div>
      <div className="space-y-2.5">
        {goals.map((g) => (
          <GoalCard key={g.id} goal={g} onOpen={() => onOpen(g.id)} onAdvance={onAdvance ? () => onAdvance(g) : undefined} />
        ))}
      </div>
    </section>
  );
}

function GoalCard({ goal, onOpen, onAdvance }: { goal: Goal; onOpen: () => void; onAdvance?: () => void }) {
  const pct = goal.progress.total ? Math.round((goal.progress.done / goal.progress.total) * 100) : 0;
  const due = dueLabel(goal.due, goal.overdue);
  return (
    <div className="rounded-3xl bg-surface border border-border/70 shadow-sm overflow-hidden">
      <button type="button" onClick={onOpen} className="w-full text-left px-4 pt-3.5 pb-3">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-[15.5px] leading-snug">{goal.title}</div>
            {goal.next_step && goal.status === "active" && (
              <div className="mt-1 text-[13px] text-muted truncate">Next: {goal.next_step}</div>
            )}
            {goal.status !== "active" && <div className="mt-1 text-[13px] text-muted capitalize">{goal.status}</div>}
          </div>
          <div className="text-[13px] text-muted whitespace-nowrap">
            {goal.progress.done}/{goal.progress.total}
          </div>
        </div>
        <div className="mt-3 h-1.5 rounded-full bg-surface-2 overflow-hidden">
          <div className={cx("h-full rounded-full transition-all", goal.overdue ? "bg-rose-500" : "bg-accent")} style={{ width: `${pct}%` }} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted">
          <CategoryBadge id={goal.category} />
          {due && (
            <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5", goal.overdue ? "bg-rose-500/12 text-rose-600 dark:text-rose-300 font-medium" : "bg-surface-2")}>
              <CalendarDays size={11} /> {due}
            </span>
          )}
          {goal.check_in && goal.status === "active" && (
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5">
              <Bell size={11} /> {describeCadence(goal.check_in)}
            </span>
          )}
          <span className="ml-auto">Updated {relativeTime(goal.updated_at)}</span>
        </div>
      </button>
      {onAdvance && goal.next_step && (
        <div className="border-t border-border/70 px-3 py-2 flex justify-end">
          <button type="button" onClick={onAdvance} className="flex items-center gap-1.5 rounded-full bg-accent/12 text-accent px-3 py-1.5 text-[13px] font-medium">
            <Play size={14} /> Work on it now
          </button>
        </div>
      )}
    </div>
  );
}

/** "Muse suggests adjusting the plan" — accept swaps the open steps, dismiss keeps the plan. */
function ProposalCard({ goal, onChanged, onOpen }: { goal: Goal; onChanged: () => void; onOpen: () => void }) {
  const { toast, state } = useStore();
  const [busy, setBusy] = useState(false);
  const name = state.profile?.name ?? "Muse";
  const p = goal.proposal;
  if (!p) return null;
  const act = async (accept: boolean) => {
    setBusy(true);
    try {
      if (accept) await api.acceptProposal(goal.id);
      else await api.dismissProposal(goal.id);
      toast(accept ? "Plan updated" : "Kept your plan");
      onChanged();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const kept = goal.steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  return (
    <div className="rounded-3xl border border-accent/30 bg-accent/5 px-4 py-3.5">
      <button type="button" onClick={onOpen} className="w-full text-left">
        <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-accent">
          <Sparkles size={13} /> Adjust the plan for “{goal.title}”?
        </div>
        <p className="mt-1.5 text-[14px] leading-snug">{p.reason}</p>
        <div className="mt-2 text-[12px] text-muted">
          {kept > 0 && <span>Keeps the {kept} step{kept === 1 ? "" : "s"} already done. </span>}
          New remaining steps:
        </div>
        <ol className="mt-1 space-y-0.5 text-[13.5px] list-decimal pl-5">
          {p.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </button>
      <div className="mt-3 flex gap-2">
        <button type="button" disabled={busy} onClick={() => void act(false)} className="flex-1 rounded-2xl border border-border py-2 text-[13.5px] font-medium disabled:opacity-50">
          Keep my plan
        </button>
        <button type="button" disabled={busy} onClick={() => void act(true)} className="flex-1 rounded-2xl bg-accent text-accent-fg py-2 text-[13.5px] font-medium disabled:opacity-50">
          Use {name}'s plan
        </button>
      </div>
    </div>
  );
}

function CategoryPicker({ value, onChange }: { value: GoalCategory; onChange: (v: GoalCategory) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {CATEGORIES.map((c) => (
        <button
          key={c.id}
          type="button"
          onClick={() => onChange(value === c.id ? "" : c.id)}
          className={cx(
            "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12.5px] font-medium transition border",
            value === c.id ? cx(c.tone, "border-transparent ring-2 ring-accent/40") : "border-border text-muted",
          )}
        >
          {c.icon({ size: 12 })} {c.label}
        </button>
      ))}
    </div>
  );
}

function CadencePicker({ value, onChange }: { value: string; onChange: (spec: string) => void }) {
  const { cadence, anchor, time } = splitCadence(value);
  const set = (c: string, a: string, t: string) => onChange(joinCadence(c, a, t));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {CADENCES.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => set(c.id, c.id === "weekly" ? anchor || "mon" : c.id === "monthly" ? anchor || "1" : "", time)}
            className={cx(
              "rounded-full px-2.5 py-1 text-[12.5px] font-medium border transition",
              cadence === c.id ? "bg-accent text-accent-fg border-transparent" : "border-border text-muted",
            )}
          >
            {c.label}
          </button>
        ))}
      </div>
      {cadence && (
        <div className="flex items-center gap-2 text-[13.5px]">
          {cadence === "weekly" && (
            <select value={anchor || "mon"} onChange={(e) => set(cadence, e.target.value, time)} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none">
              {WEEKDAYS.map((d) => (
                <option key={d} value={d}>
                  {d[0].toUpperCase() + d.slice(1)}
                </option>
              ))}
            </select>
          )}
          {cadence === "monthly" && (
            <select value={anchor || "1"} onChange={(e) => set(cadence, e.target.value, time)} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none">
              {Array.from({ length: 28 }, (_, i) => String(i + 1)).map((d) => (
                <option key={d} value={d}>
                  {d}
                  {ordinal(Number(d))}
                </option>
              ))}
            </select>
          )}
          <span className="text-muted">at</span>
          <input type="time" value={time} onChange={(e) => set(cadence, anchor, e.target.value || "09:00")} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none" />
        </div>
      )}
    </div>
  );
}

function GoalDetail({
  goal,
  onClose,
  onAdvance,
  onChanged,
}: {
  goal: Goal | null;
  onClose: () => void;
  onAdvance: (g: Goal) => void;
  onChanged: () => void;
}) {
  const { toast, send, openThread, state } = useStore();
  const [newStep, setNewStep] = useState("");
  const [editing, setEditing] = useState(false);
  const name = state.profile?.name ?? "Muse";

  const patch = async (body: Record<string, unknown>) => {
    if (!goal) return;
    try {
      await api.patchGoal(goal.id, body);
      onChanged();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const addStep = async () => {
    if (!goal || !newStep.trim()) return;
    try {
      await api.addStep(goal.id, newStep.trim());
      setNewStep("");
      onChanged();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const checkIn = async () => {
    if (!goal) return;
    try {
      await api.checkInGoal(goal.id);
      toast(`${name} will check in with you in the main chat`);
      openThread("main");
      onClose();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const remove = async () => {
    if (!goal || !window.confirm(`Delete “${goal.title}”?`)) return;
    try {
      await api.deleteGoal(goal.id);
      onChanged();
      onClose();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const due = goal ? dueLabel(goal.due, goal.overdue) : "";

  return (
    <Sheet
      open={!!goal}
      onClose={onClose}
      title={goal?.title}
      footer={
        goal && (
          <div className="flex gap-2">
            {goal.status === "active" ? (
              <button type="button" onClick={() => void patch({ status: "paused" })} className="flex-1 rounded-2xl border border-border py-2.5 font-medium flex items-center justify-center gap-1.5">
                <Pause size={16} /> Pause
              </button>
            ) : goal.status === "paused" ? (
              <button type="button" onClick={() => void patch({ status: "active" })} className="flex-1 rounded-2xl border border-border py-2.5 font-medium flex items-center justify-center gap-1.5">
                <Play size={16} /> Resume
              </button>
            ) : null}
            {goal.status === "active" && (
              <button type="button" onClick={() => onAdvance(goal)} className="flex-1 rounded-2xl bg-accent text-accent-fg py-2.5 font-medium flex items-center justify-center gap-1.5">
                <Play size={16} /> Work on it now
              </button>
            )}
            <button type="button" onClick={() => void remove()} aria-label="Delete goal" className="rounded-2xl border border-border px-3 text-muted hover:text-rose-500">
              <Trash2 size={18} />
            </button>
          </div>
        )
      }
    >
      {goal && (
        <div className="space-y-4">
          {goal.proposal && <ProposalCard goal={goal} onChanged={onChanged} onOpen={() => undefined} />}
          {goal.description && <p className="text-[14px] text-muted leading-snug">{goal.description}</p>}

          {/* category · due · reminders */}
          <div className="rounded-2xl bg-surface-2/60 px-3.5 py-3">
            {!editing ? (
              <button type="button" onClick={() => setEditing(true)} className="w-full text-left">
                <div className="flex flex-wrap items-center gap-1.5 text-[12.5px]">
                  {goal.category ? <CategoryBadge id={goal.category} size="md" /> : <span className="rounded-full border border-dashed border-border px-2.5 py-1 text-muted">No category</span>}
                  <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-1", goal.overdue ? "bg-rose-500/12 text-rose-600 dark:text-rose-300 font-medium" : "bg-surface text-muted")}>
                    <CalendarDays size={13} /> {due || "No target date"}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-surface px-2.5 py-1 text-muted">
                    <Bell size={13} /> {goal.check_in ? describeCadence(goal.check_in) : "No reminders"}
                  </span>
                </div>
                {goal.next_check_in && goal.status === "active" && (
                  <div className="mt-1.5 text-[12px] text-muted">Next check-in {relativeTime(goal.next_check_in)} · {timeShort(goal.next_check_in)}</div>
                )}
                <div className="mt-1.5 text-[12px] text-accent font-medium">Edit</div>
              </button>
            ) : (
              <div className="space-y-3">
                <div>
                  <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">Area of life</div>
                  <CategoryPicker value={goal.category} onChange={(v) => void patch({ category: v })} />
                </div>
                <div>
                  <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">Target date</div>
                  <div className="flex items-center gap-2">
                    <input type="date" value={goal.due} onChange={(e) => void patch({ due: e.target.value })} className="rounded-xl bg-surface px-2.5 py-1.5 text-[13.5px] outline-none" />
                    {goal.due && (
                      <button type="button" onClick={() => void patch({ due: "" })} className="text-[12.5px] text-muted">
                        Clear
                      </button>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">Reminders from {name}</div>
                  <CadencePicker value={goal.check_in} onChange={(spec) => void patch({ check_in: spec })} />
                </div>
                <button type="button" onClick={() => setEditing(false)} className="text-[12.5px] text-accent font-medium">
                  Done
                </button>
              </div>
            )}
          </div>

          <div>
            <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-2">
              Plan · {goal.progress.done}/{goal.progress.total}
            </div>
            <ul className="space-y-1">
              {goal.steps.map((s) => {
                const Icon = STEP_ICON[s.status];
                return (
                  <li key={s.idx} className="flex items-start gap-2.5 rounded-2xl px-2 py-1.5 hover:bg-surface-2/60">
                    <button
                      type="button"
                      aria-label={`Mark step ${s.idx} ${STEP_NEXT[s.status]}`}
                      onClick={() => void patch({ step_index: s.idx, step_status: STEP_NEXT[s.status] })}
                      className="mt-0.5 text-muted"
                    >
                      <Icon size={20} />
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className={cx("text-[14.5px] leading-snug", (s.status === "done" || s.status === "skipped") && "line-through text-muted")}>
                        {s.idx}. {s.title}
                      </div>
                      {s.note && <div className="text-[12.5px] text-muted mt-0.5 whitespace-pre-wrap">{s.note}</div>}
                    </div>
                  </li>
                );
              })}
            </ul>
            <div className="mt-2 flex gap-2">
              <input
                value={newStep}
                onChange={(e) => setNewStep(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void addStep()}
                placeholder="Add a step"
                className="flex-1 rounded-2xl bg-surface-2 px-3.5 py-2 text-[14px] outline-none focus:ring-2 focus:ring-accent/40"
              />
              <button type="button" onClick={() => void addStep()} className="rounded-2xl bg-surface-2 px-3 text-accent" aria-label="Add step">
                <Plus size={18} />
              </button>
            </div>
          </div>
          {goal.notes && (
            <div>
              <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">Notes from {name}</div>
              <pre className="whitespace-pre-wrap break-words text-[13px] leading-snug text-muted font-sans">{goal.notes}</pre>
            </div>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            <button
              type="button"
              onClick={() => {
                void send("main", `Let's talk about my goal “${goal.title}” (${goal.id}). What's the status and what should we do next?`);
                openThread("main");
                onClose();
              }}
              className="text-[13.5px] text-accent font-medium"
            >
              Discuss this goal in chat →
            </button>
            {goal.status === "active" && (
              <button type="button" onClick={() => void checkIn()} className="text-[13.5px] text-accent font-medium inline-flex items-center gap-1">
                <BellRing size={14} /> Check in with me now
              </button>
            )}
          </div>
        </div>
      )}
    </Sheet>
  );
}

function NewGoalSheet({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const { toast, send, openThread, state } = useStore();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState("");
  const [category, setCategory] = useState<GoalCategory>("");
  const [due, setDue] = useState("");
  const [checkIn, setCheckIn] = useState("");
  const [busy, setBusy] = useState(false);
  const name = state.profile?.name ?? "Muse";

  const reset = () => {
    setTitle("");
    setDescription("");
    setSteps("");
    setCategory("");
    setDue("");
    setCheckIn("");
  };

  const create = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      await api.createGoal({
        title: title.trim(),
        description: description.trim(),
        steps: steps.split("\n").map((s) => s.trim()).filter(Boolean),
        category,
        due,
        check_in: checkIn,
      });
      reset();
      onCreated();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const askMuse = () => {
    if (!title.trim()) return;
    const extras = [
      category ? `category: ${category}` : "",
      due ? `target date: ${due}` : "",
      checkIn ? `check in with me: ${describeCadence(checkIn).toLowerCase()} (check_in "${checkIn}")` : "",
    ].filter(Boolean);
    void send(
      "main",
      `Create a goal for me: "${title.trim()}"${description.trim() ? ` — ${description.trim()}` : ""}${extras.length ? ` (${extras.join(", ")})` : ""}. Break it into concrete steps with the goals tool, then tell me the plan.`,
    );
    reset();
    onClose();
    openThread("main");
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="New goal"
      footer={
        <div className="flex gap-2">
          <button type="button" onClick={askMuse} disabled={!title.trim()} className="flex-1 rounded-2xl border border-border py-2.5 font-medium disabled:opacity-50 flex items-center justify-center gap-1.5">
            <Sparkles size={16} /> Let {name} plan it
          </button>
          <button type="button" onClick={() => void create()} disabled={!title.trim() || busy} className="flex-1 rounded-2xl bg-accent text-accent-fg py-2.5 font-medium disabled:opacity-50">
            Create
          </button>
        </div>
      }
    >
      <div className="space-y-3.5">
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What do you want to achieve?" className="w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[15px] outline-none focus:ring-2 focus:ring-accent/40" />
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">Area of life</div>
          <CategoryPicker value={category} onChange={setCategory} />
        </div>
        <div className="flex items-center gap-3">
          <div className="text-[12px] font-semibold uppercase tracking-wide text-muted flex-1">Target date</div>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="rounded-xl bg-surface-2 px-2.5 py-1.5 text-[13.5px] outline-none" />
        </div>
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">Reminders from {name}</div>
          <CadencePicker value={checkIn} onChange={setCheckIn} />
        </div>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Why it matters, constraints (optional)" rows={2} className="w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40 resize-none" />
        <textarea value={steps} onChange={(e) => setSteps(e.target.value)} placeholder={"Steps, one per line (optional — or let " + name + " plan them)"} rows={3} className="w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40 resize-none" />
      </div>
    </Sheet>
  );
}
