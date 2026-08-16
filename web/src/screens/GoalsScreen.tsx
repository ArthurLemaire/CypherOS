import { CheckCircle2, Circle, CircleDashed, CircleSlash, OctagonAlert, Pause, Play, Plus, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { Sheet } from "../components/Sheet";
import { useStore } from "../store";
import type { Goal, GoalStep } from "../types";
import { cx, relativeTime } from "../util";

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

export function GoalsScreen() {
  const { state, refreshGoals, send, openThread, toast } = useStore();
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const name = state.profile?.name ?? "Muse";

  useEffect(() => {
    void refreshGoals();
  }, [refreshGoals]);

  const active = state.goals.filter((g) => g.status === "active");
  const paused = state.goals.filter((g) => g.status === "paused");
  const finished = state.goals.filter((g) => g.status === "done" || g.status === "cancelled");
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
      <header className="safe-top shrink-0 px-5 pt-4 pb-3 flex items-center gap-3">
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

      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-5">
        {state.goals.length === 0 && (
          <div className="rounded-3xl border border-dashed border-border p-6 text-center">
            <Sparkles className="mx-auto text-accent" />
            <div className="mt-2 font-semibold">No goals yet</div>
            <p className="mt-1 text-[13.5px] text-muted">
              Tell {name} about something you want to achieve and it will break it into steps, keep track, and keep working
              on it in the background.
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
          <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
        </div>
        <div className="mt-1.5 text-[11.5px] text-muted">Updated {relativeTime(goal.updated_at)}</div>
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
          {goal.description && <p className="text-[14px] text-muted leading-snug">{goal.description}</p>}
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
  const [busy, setBusy] = useState(false);
  const name = state.profile?.name ?? "Muse";

  const create = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      await api.createGoal(title.trim(), description.trim(), steps.split("\n").map((s) => s.trim()).filter(Boolean));
      setTitle("");
      setDescription("");
      setSteps("");
      onCreated();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const askMuse = () => {
    if (!title.trim()) return;
    void send(
      "main",
      `Create a goal for me: "${title.trim()}"${description.trim() ? ` — ${description.trim()}` : ""}. Break it into concrete steps with the goals tool, then tell me the plan.`,
    );
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
      <div className="space-y-3">
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What do you want to achieve?" className="w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[15px] outline-none focus:ring-2 focus:ring-accent/40" />
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Why it matters, constraints, deadline (optional)" rows={2} className="w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40 resize-none" />
        <textarea value={steps} onChange={(e) => setSteps(e.target.value)} placeholder={"Steps, one per line (optional — or let " + name + " plan them)"} rows={4} className="w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40 resize-none" />
      </div>
    </Sheet>
  );
}
