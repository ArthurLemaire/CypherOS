import { ArrowRight, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import { useStore } from "../store";
import type { IdeasData } from "../types";
import { relativeTime } from "../util";

/** Muse "always thinks about what it can do for you" — suggestions from goals, memory and recent chat. */
export function IdeasScreen() {
  const { state, send, openThread, toast } = useStore();
  const [data, setData] = useState<IdeasData | null>(null);
  const [loading, setLoading] = useState(false);
  const name = state.profile?.name ?? "Muse";
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

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-4 pb-3 flex items-center gap-3">
        <div className="flex-1">
          <h1 className="text-[24px] font-bold tracking-tight">{t("Ideas")}</h1>
          <p className="text-[13px] text-muted">
            {t("Things {name} could do for you, based on your goals, memory and recent conversations.", { name })}
          </p>
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
      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-2.5">
        {data && (
          <div className="px-1 text-[12px] text-muted">
            {data.source === "model"
              ? t("Generated {when}", { when: relativeTime(data.generated_at) })
              : t("Starter ideas — refresh once {name} knows you better.", { name })}
          </div>
        )}
        {(data?.ideas ?? []).map((idea) => (
          <button
            key={idea.title}
            type="button"
            onClick={() => {
              void send("main", idea.prompt);
              openThread("main");
            }}
            className="w-full text-left rounded-3xl bg-surface border border-border/70 shadow-sm px-4 py-3.5 active:scale-[0.99] transition"
          >
            <div className="flex items-start gap-3">
              <div className="rounded-2xl bg-accent/12 text-accent p-2 mt-0.5">
                <Sparkles size={18} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-[15.5px] leading-snug">{idea.title}</div>
                {idea.detail && <div className="mt-1 text-[13.5px] text-muted leading-snug">{idea.detail}</div>}
                <div className="mt-2 text-[13px] text-accent font-medium flex items-center gap-1">
                  {t("Ask {name}", { name })} <ArrowRight size={14} />
                </div>
              </div>
            </div>
          </button>
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
