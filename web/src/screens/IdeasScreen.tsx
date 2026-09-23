import {
  BookOpen,
  CalendarCheck,
  ChevronRight,
  FileText,
  HeartPulse,
  House,
  Loader2,
  PiggyBank,
  RefreshCw,
  Search,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import { useStore } from "../store";
import type { Idea, IdeasData } from "../types";
import { relativeTime } from "../util";

/** The areas an idea can belong to, in the order they are listed; icon and label for each. */
const AREAS: Array<{ id: string; label: string; icon: (size: number) => ReactNode }> = [
  { id: "planning", label: "Planning", icon: (s) => <CalendarCheck size={s} /> },
  { id: "goals", label: "Goals", icon: (s) => <Target size={s} /> },
  { id: "research", label: "Research", icon: (s) => <Search size={s} /> },
  { id: "money", label: "Money", icon: (s) => <PiggyBank size={s} /> },
  { id: "health", label: "Health", icon: (s) => <HeartPulse size={s} /> },
  { id: "home", label: "Home", icon: (s) => <House size={s} /> },
  { id: "learning", label: "Learning", icon: (s) => <BookOpen size={s} /> },
  { id: "people", label: "People", icon: (s) => <Users size={s} /> },
  { id: "files", label: "Files & tools", icon: (s) => <FileText size={s} /> },
  { id: "fun", label: "Just for you", icon: (s) => <Sparkles size={s} /> },
];

/** Muse "always thinks about what it can do for you" — suggestions from goals, memory and recent chat. */
export function IdeasScreen() {
  const { state, send, openThread, toast } = useStore();
  const [data, setData] = useState<IdeasData | null>(null);
  const [loading, setLoading] = useState(false);
  const name = state.profile?.name ?? "OpenMuse";
  const t = useT();

  const load = async (refresh = false) => {
    setLoading(true);
    try {
      const d = await api.ideas(refresh);
      setData(d);
      if (d.error) toast(t("Could not refresh ideas: {error}", { error: d.error }));
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const groups = groupByArea(data?.ideas ?? []);

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-4 pb-3 flex items-center gap-3">
        <div className="flex-1">
          <h1 className="text-[24px] font-bold tracking-tight">{t("Ideas")}</h1>
          <p className="text-[13px] text-muted">{t("Things {name} could do for you, based on your goals, memory and recent conversations.", { name })}</p>
        </div>
        <button
          type="button"
          onClick={() => void load(true)}
          disabled={loading}
          aria-label={t("Refresh ideas")}
          className="h-10 w-10 rounded-full bg-surface-2 text-accent flex items-center justify-center disabled:opacity-60"
        >
          {loading ? <Loader2 size={20} className="animate-spin" /> : <RefreshCw size={19} />}
        </button>
      </header>
      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-5">
        {data && (
          <div className="px-1 text-[12px] text-muted">
            {data.source === "model" ? t("Generated {when}", { when: relativeTime(data.generated_at) }) : t("Starter ideas — refresh once {name} knows you better.", { name })}
          </div>
        )}
        {groups.map(({ area, ideas }) => (
          <section key={area.id}>
            <div className="mb-1.5 flex items-center gap-2 px-1 text-[13px] font-semibold text-muted">
              <span className="text-fg/70">{area.icon(15)}</span> {t(area.label)}
            </div>
            <ul className="overflow-hidden rounded-[22px] border border-border/70 bg-surface">
              {ideas.map((idea) => (
                <li key={idea.title} className="border-b border-border/60 last:border-b-0">
                  <button
                    type="button"
                    onClick={() => {
                      void send("main", idea.prompt);
                      openThread("main");
                    }}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left transition active:bg-surface-2/70"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] font-medium leading-snug">{idea.title}</span>
                      {idea.detail && <span className="mt-0.5 block text-[13px] leading-snug text-muted">{idea.detail}</span>}
                    </span>
                    <ChevronRight size={16} className="shrink-0 text-muted/70" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {!data && loading && (
          <div className="py-10 text-center text-muted flex items-center justify-center gap-2">
            <Loader2 className="animate-spin" size={18} /> {t("Thinking about what I could do for you…")}
          </div>
        )}
      </div>
    </div>
  );
}

function groupByArea(ideas: Idea[]): Array<{ area: (typeof AREAS)[number]; ideas: Idea[] }> {
  const fallback = AREAS[AREAS.length - 1];
  const out = AREAS.map((area) => ({ area, ideas: [] as Idea[] }));
  for (const idea of ideas) {
    const hit = out.find((g) => g.area.id === (idea.area || fallback.id)) ?? out[out.length - 1];
    hit.ideas.push(idea);
  }
  return out.filter((g) => g.ideas.length > 0);
}
