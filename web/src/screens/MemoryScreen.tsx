import { Brain, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import type { MemoryItem } from "../types";
import { relativeTime } from "../util";

const CATEGORIES = ["profile", "preference", "people", "routine", "constraint", "general"];

/** "Your Memory files, which you can read and edit directly." */
export function MemoryScreen() {
  const { state, toast } = useStore();
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("profile");
  const [adding, setAdding] = useState(false);
  const name = state.profile?.name ?? "Muse";

  const load = () => api.memory().then(setItems).catch((e: Error) => toast(e.message));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.memoryVersion]);

  const grouped = useMemo(() => {
    const map = new Map<string, MemoryItem[]>();
    for (const m of items) map.set(m.category, [...(map.get(m.category) ?? []), m]);
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [items]);

  const add = async () => {
    if (!content.trim()) return;
    setAdding(true);
    try {
      await api.addMemory(content.trim(), category);
      setContent("");
      await load();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setAdding(false);
    }
  };

  const forget = async (m: MemoryItem) => {
    if (!window.confirm(`Forget “${m.content.slice(0, 60)}”?`)) return;
    try {
      await api.forgetMemory(m.id);
      setItems((prev) => prev.filter((x) => x.id !== m.id));
    } catch (e) {
      toast((e as Error).message);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-4 pb-3">
        <h1 className="text-[24px] font-bold tracking-tight">Memory</h1>
        <p className="text-[13px] text-muted">
          What {name} remembers about you. Read it, add to it, or make {name} forget — nothing here is hidden from you.
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-5">
        <div className="rounded-3xl bg-surface border border-border/70 shadow-sm p-3.5 space-y-2.5">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={2}
            placeholder={`Tell ${name} something to remember, e.g. “I'm vegetarian” or “My sister's birthday is 14 May”`}
            className="w-full resize-none rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14.5px] outline-none focus:ring-2 focus:ring-accent/40"
          />
          <div className="flex items-center gap-2">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <div className="flex-1" />
            <button
              type="button"
              disabled={!content.trim() || adding}
              onClick={() => void add()}
              className="rounded-2xl bg-accent text-accent-fg px-3.5 py-2 text-[14px] font-medium flex items-center gap-1.5 disabled:opacity-50"
            >
              <Plus size={16} /> Remember
            </button>
          </div>
        </div>

        {items.length === 0 && (
          <div className="rounded-3xl border border-dashed border-border p-6 text-center">
            <Brain className="mx-auto text-accent" />
            <div className="mt-2 font-semibold">Nothing remembered yet</div>
            <p className="mt-1 text-[13.5px] text-muted">
              {name} saves durable facts you share in chat — preferences, people, routines — and never secrets.
            </p>
          </div>
        )}

        {grouped.map(([cat, list]) => (
          <section key={cat}>
            <div className="px-1 mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">
              {cat} · {list.length}
            </div>
            <ul className="rounded-3xl bg-surface border border-border/70 shadow-sm divide-y divide-border/70 overflow-hidden">
              {list.map((m) => (
                <li key={m.id} className="flex items-start gap-3 px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-[14.5px] leading-snug break-words">{m.content}</div>
                    <div className="mt-0.5 text-[11.5px] text-muted">
                      {m.source === "user" ? "added by you" : `saved by ${name}`} · {relativeTime(m.created_at)}
                    </div>
                  </div>
                  <button type="button" aria-label="Forget" onClick={() => void forget(m)} className="p-1.5 text-muted hover:text-rose-500">
                    <Trash2 size={17} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
