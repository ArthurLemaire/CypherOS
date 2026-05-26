import { ChevronLeft, ChevronRight, FileCode2, Link2, Loader2, Pencil, Play, Plus, Trash2, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { BackBar } from "../components/BackBar";
import { Markdown } from "../components/Markdown";
import { useT } from "../i18n";
import { useStore } from "../store";
import type { SkillDetail, SkillInfo, SkillsData } from "../types";
import { cx, relativeTime } from "../util";

const TEMPLATE = (name: string) => `---
name: ${name}
description: What this does, and when to use it — the model picks the skill from this line.
---

# ${name.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase())}

## Gather

- What to read first, with which tools.

## Do

1. The steps, in order.
2. What to produce (a file in the workspace?).

## Finish

- What to say in chat; what to ask; what never to do.
`;

/**
 * Skills: how a job is done, written down once — a weekly review, a trip plan, an inbox
 * triage. The built-in ones ship with the app; yours are folders in the data directory
 * and can be written here, pasted in, or saved by the agent after a job went well.
 */
export function SkillsScreen() {
  const { state, toast, draft } = useStore();
  const t = useT();
  const name = state.profile?.name ?? "OpenMuse";
  const [data, setData] = useState<SkillsData | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = () => api.skills().then(setData).catch((e: Error) => toast(e.message));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.skillsVersion]);

  if (open) {
    return (
      <SkillView
        name={open}
        onBack={() => setOpen(null)}
        onUse={(n) => draft(`/${n} `)}
        onGone={() => {
          setOpen(null);
          void load();
        }}
      />
    );
  }
  if (adding) {
    return (
      <SkillEditor
        onCancel={() => setAdding(false)}
        onSaved={(sk) => {
          setAdding(false);
          setOpen(sk.name);
        }}
      />
    );
  }

  const yours = data?.skills.filter((s) => s.source === "yours") ?? [];
  const builtIn = data?.skills.filter((s) => s.source === "built-in") ?? [];

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-2 pb-3">
        <BackBar />
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <h1 className="text-[24px] font-bold tracking-tight">{t("Skills")}</h1>
            <p className="text-[13px] text-muted">
              {t("How {name} does a job, written down once. Start one in chat with /name, or just ask — it picks the skill that fits.", { name })}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="shrink-0 mt-1 rounded-2xl bg-accent text-accent-fg px-3 py-2 text-[13.5px] font-medium flex items-center gap-1.5"
          >
            <Plus size={15} /> {t("New")}
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-5">
        {data === null && (
          <div className="py-10 flex justify-center text-muted">
            <Loader2 className="animate-spin" size={20} />
          </div>
        )}
        {data && (
          <>
            <section>
              <div className="px-1 mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">
                {t("Yours")} · {yours.length}
              </div>
              {yours.length === 0 ? (
                <div className="rounded-3xl border border-dashed border-border p-5 text-center">
                  <Wand2 className="mx-auto text-accent" />
                  <div className="mt-2 font-semibold">{t("Nothing of your own yet")}</div>
                  <p className="mt-1 text-[13.5px] text-muted">
                    {t("After a job went well, tell {name} “save this as a skill” — it writes the steps down and asks you first. Or write one here, or paste a link to a SKILL.md.", { name })}
                  </p>
                </div>
              ) : (
                <SkillList items={yours} onOpen={setOpen} onChange={load} />
              )}
            </section>
            <section>
              <div className="px-1 mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">
                {t("Built in")} · {builtIn.length}
              </div>
              <SkillList items={builtIn} onOpen={setOpen} onChange={load} />
              <p className="mt-2 px-1 text-[12px] text-muted">
                {t("Switch one off to keep it out of {name}'s list. A skill of yours with the same name replaces it.", { name })}
              </p>
            </section>
            {Object.keys(data.errors).length > 0 && (
              <section className="rounded-3xl bg-amber-500/10 text-amber-800 dark:text-amber-200 p-3.5 text-[13px]">
                <div className="font-semibold">{t("Folders that could not be read")}</div>
                {Object.entries(data.errors).map(([n, err]) => (
                  <div key={n} className="mt-1 break-words">
                    <span className="font-mono">{n}</span>: {err}
                  </div>
                ))}
              </section>
            )}
            <p className="px-1 text-[12px] text-muted">
              {t("Yours live in {dir}, one folder each with a SKILL.md — the Agent Skills format, so recipes written for other agents work here too.", { dir: data.dir })}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function SkillList({ items, onOpen, onChange }: { items: SkillInfo[]; onOpen: (name: string) => void; onChange: () => void }) {
  const { toast } = useStore();
  const t = useT();
  const toggle = async (sk: SkillInfo, enabled: boolean) => {
    try {
      await api.setSkillEnabled(sk.name, enabled);
      onChange();
    } catch (e) {
      toast((e as Error).message);
    }
  };
  return (
    <ul className="rounded-3xl bg-surface border border-border/70 shadow-sm divide-y divide-border/70 overflow-hidden">
      {items.map((sk) => (
        <li key={sk.name} className={cx("flex items-center gap-3 px-4 py-3", !sk.enabled && "opacity-60")}>
          <button type="button" onClick={() => onOpen(sk.name)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
            <span className="rounded-2xl bg-accent/12 text-accent p-2">
              <Wand2 size={17} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[14.5px] font-medium">/{sk.name}</span>
              <span className="text-[12.5px] text-muted line-clamp-2">{sk.description}</span>
            </span>
            <ChevronRight size={17} className="shrink-0 text-muted" />
          </button>
          <button
            type="button"
            role="switch"
            aria-checked={sk.enabled}
            aria-label={t("On")}
            onClick={() => void toggle(sk, !sk.enabled)}
            className={cx("relative h-6 w-10 shrink-0 rounded-full transition", sk.enabled ? "bg-accent" : "bg-border")}
          >
            <span className={cx("absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition", sk.enabled ? "left-[18px]" : "left-0.5")} />
          </button>
        </li>
      ))}
    </ul>
  );
}

function SkillView({ name, onBack, onUse, onGone }: { name: string; onBack: () => void; onUse: (name: string) => void; onGone: () => void }) {
  const { toast } = useStore();
  const t = useT();
  const [skill, setSkill] = useState<SkillDetail | null>(null);
  const [editing, setEditing] = useState(false);

  const load = () => api.skill(name).then(setSkill).catch((e: Error) => toast(e.message));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  const remove = async () => {
    if (!skill || !window.confirm(t("Delete the skill “{name}”? Its folder goes with it.", { name: skill.name }))) return;
    try {
      await api.deleteSkill(skill.name);
      onGone();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  if (editing && skill) {
    return (
      <SkillEditor
        initial={skill}
        onCancel={() => setEditing(false)}
        onSaved={() => {
          setEditing(false);
          void load();
        }}
      />
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-2 pb-3">
        <button type="button" onClick={onBack} className="-ml-2 mb-1 flex items-center gap-0.5 rounded-full py-1 pl-1 pr-3 text-[14px] font-medium text-accent hover:bg-surface-2">
          <ChevronLeft size={19} /> {t("Skills")}
        </button>
        {skill && (
          <>
            <h1 className="text-[22px] font-bold tracking-tight font-mono">/{skill.name}</h1>
            <p className="text-[13px] text-muted">
              {skill.source === "built-in" ? t("Built in") : t("Yours")}
              {skill.updated_at ? ` · ${t("updated {when}", { when: relativeTime(skill.updated_at) })}` : ""}
              {skill.metadata.author ? ` · ${skill.metadata.author}` : ""}
            </p>
          </>
        )}
      </header>
      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-4">
        {!skill && (
          <div className="py-10 flex justify-center text-muted">
            <Loader2 className="animate-spin" size={20} />
          </div>
        )}
        {skill && (
          <>
            <div className="flex gap-2">
              <button type="button" onClick={() => onUse(skill.name)} className="flex-1 rounded-2xl bg-accent text-accent-fg px-3.5 py-2.5 text-[14px] font-medium flex items-center justify-center gap-1.5">
                <Play size={15} /> {t("Use in chat")}
              </button>
              <button type="button" onClick={() => setEditing(true)} className="rounded-2xl bg-surface border border-border/70 px-3.5 py-2.5 text-[14px] font-medium flex items-center gap-1.5">
                <Pencil size={15} /> {skill.source === "built-in" ? t("Make your own copy") : t("Edit")}
              </button>
              {skill.source === "yours" && (
                <button type="button" aria-label={t("Delete")} onClick={() => void remove()} className="rounded-2xl bg-surface border border-border/70 px-3 py-2.5 text-muted hover:text-rose-500">
                  <Trash2 size={17} />
                </button>
              )}
            </div>
            <div className="rounded-3xl bg-surface border border-border/70 shadow-sm p-4">
              <p className="text-[14px] leading-snug">{skill.description}</p>
            </div>
            <div className="rounded-3xl bg-surface border border-border/70 shadow-sm p-4 text-[14px]">
              <Markdown text={skill.body} />
            </div>
            {skill.files.length > 0 && (
              <div className="rounded-3xl bg-surface border border-border/70 shadow-sm p-4">
                <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-2">{t("Files that come with it")}</div>
                <ul className="space-y-1">
                  {skill.files.map((f) => (
                    <li key={f} className="flex items-center gap-2 text-[13.5px] font-mono">
                      <FileCode2 size={15} className="text-muted" /> {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="px-1 text-[12px] text-muted break-all">{skill.path}</p>
          </>
        )}
      </div>
    </div>
  );
}

/** Write a SKILL.md by hand, or fetch one from a link (a raw file, or a GitHub folder page). */
function SkillEditor({ initial, onCancel, onSaved }: { initial?: SkillDetail; onCancel: () => void; onSaved: (sk: SkillDetail) => void }) {
  const { toast } = useStore();
  const t = useT();
  const [name, setName] = useState(initial?.name ?? "");
  const [content, setContent] = useState(initial?.content ?? "");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const nameOk = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/.test(name);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const text = content.trim() ? content : TEMPLATE(name);
      onSaved(await api.saveSkill(name, text.replace(/^---\nname: .*\n/, `---\nname: ${name}\n`)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const fetchIt = async () => {
    setBusy(true);
    setError("");
    try {
      onSaved(await api.importSkill(url.trim()));
    } catch (e) {
      setError((e as Error).message);
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-2 pb-3">
        <button type="button" onClick={onCancel} className="-ml-2 mb-1 flex items-center gap-0.5 rounded-full py-1 pl-1 pr-3 text-[14px] font-medium text-accent hover:bg-surface-2">
          <ChevronLeft size={19} /> {t("Back")}
        </button>
        <h1 className="text-[22px] font-bold tracking-tight">{initial ? t("Edit skill") : t("New skill")}</h1>
        <p className="text-[13px] text-muted">
          {initial?.source === "built-in"
            ? t("Saving makes a copy of yours with the same name; it replaces the built-in one.")
            : t("A SKILL.md: a name and a one-line description up top, then the steps in Markdown.")}
        </p>
      </header>
      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-4">
        {!initial && (
          <div className="rounded-3xl bg-surface border border-border/70 shadow-sm p-3.5 space-y-2">
            <div className="text-[12px] font-semibold uppercase tracking-wide text-muted flex items-center gap-1.5">
              <Link2 size={13} /> {t("From a link")}
            </div>
            <div className="flex gap-2">
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://github.com/…/skills/pdf"
                inputMode="url"
                autoComplete="off"
                className="flex-1 min-w-0 rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40"
              />
              <button type="button" disabled={!url.trim().startsWith("https://") || busy} onClick={() => void fetchIt()} className="rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] font-medium disabled:opacity-50">
                {t("Fetch")}
              </button>
            </div>
            <p className="text-[12px] text-muted">{t("A raw SKILL.md link, or a GitHub folder or file page.")}</p>
          </div>
        )}
        <div className="rounded-3xl bg-surface border border-border/70 shadow-sm p-3.5 space-y-2.5">
          <label className="block">
            <span className="text-[12px] font-semibold uppercase tracking-wide text-muted">{t("Name")}</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))}
              placeholder="weekly-review"
              disabled={!!initial}
              autoComplete="off"
              className="mt-1 w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] font-mono outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-70"
            />
          </label>
          <label className="block">
            <span className="text-[12px] font-semibold uppercase tracking-wide text-muted">SKILL.md</span>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              onFocus={() => {
                if (!content && nameOk) setContent(TEMPLATE(name));
              }}
              rows={16}
              spellCheck={false}
              placeholder={nameOk ? TEMPLATE(name) : t("Pick a name first; a template appears here.")}
              className="mt-1 w-full resize-y rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[13px] font-mono leading-relaxed outline-none focus:ring-2 focus:ring-accent/40"
            />
          </label>
          {error && <div className="text-[13px] text-rose-600 dark:text-rose-400 break-words">{error}</div>}
          <div className="flex gap-2">
            <button type="button" onClick={onCancel} className="rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] font-medium">
              {t("Cancel")}
            </button>
            <button type="button" disabled={!nameOk || busy} onClick={() => void save()} className="flex-1 rounded-2xl bg-accent text-accent-fg px-3.5 py-2.5 text-[14px] font-medium disabled:opacity-50">
              {busy ? t("Saving…") : t("Save")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
