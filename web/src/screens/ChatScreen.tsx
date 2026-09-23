import { ArrowUp, ChevronDown, FileText, Loader2, Menu, MessageSquarePlus, Moon, MoreHorizontal, Plus, Table2, Trash2, Wand2, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, fileUrl } from "../api";
import { Avatar } from "../components/Avatar";
import { BrowserViewer } from "../components/BrowserViewer";
import { ApprovalCard, ArtifactCard, BrowserCard, Notice, QuestionCard, ToolChip } from "../components/Cards";
import { Markdown } from "../components/Markdown";
import { Sheet } from "../components/Sheet";
import { localLabel, useT } from "../i18n";
import { useStore } from "../store";
import type { AttachmentInfo, SkillInfo, ThreadMeta, TimelineEvent, UserEvent } from "../types";
import { cx, timeDivider, timeShort } from "../util";
import { MuseSheet } from "./MuseSheet";

export function ChatScreen() {
  const { state, send, decide, loadEvents, openThread, openFile, toast } = useStore();
  const t = useT();
  const { profile, status, activeThread, threads } = state;
  // undefined until the first fetch for this thread has returned — don't flash the empty state
  const loaded = state.events[activeThread];
  const events = useMemo(() => loaded ?? [], [loaded]);
  const eventsLoaded = loaded !== undefined;
  const stream = state.streams[activeThread];
  const thread = threads.find((t) => t.id === activeThread);
  const [activityOpen, setActivityOpen] = useState(false);
  const [threadsOpen, setThreadsOpen] = useState(false);
  // the browser card being watched (or driven) full-screen
  const [browserView, setBrowserView] = useState<string | null>(null);
  const name = profile?.name ?? "OpenMuse";

  const listRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [showJump, setShowJump] = useState(false);

  const onScroll = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = gap < 120;
    setShowJump(gap > 400);
  }, []);

  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [events, stream?.text, activeThread]);

  useEffect(() => {
    stickToBottom.current = true;
  }, [activeThread]);

  const jumpToBottom = () => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  const queued = state.pendingApprovals.length;
  const statusLine = useMemo(() => {
    if (queued > 0 && status.state !== "working") {
      return queued > 1 ? t("{n} approvals waiting for you", { n: queued }) : t("1 approval waiting for you");
    }
    if (status.state === "idle" && !thread?.busy) return t("Idle · tap the avatar for activity");
    if (status.detail) return status.detail;
    return status.state === "waiting" ? t("Waiting for you") : t("Working…");
  }, [status, thread, queued, t]);

  const pendingApprovals = events.filter((e) => e.type === "approval" && e.status === "pending").length;
  // files made in this chat: a reply that names one ("saved to `plan.md`") opens it on tap
  const files = useMemo(
    () => Array.from(new Set(events.flatMap((e) => (e.type === "artifact" ? [e.path] : [])))),
    [events],
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header: the agent in the middle, what it is doing under its name; chats left, menu right */}
      <header className="safe-top shrink-0 bg-bg">
        <div className="relative flex items-start justify-between px-3 pt-2 pb-1">
          <button
            type="button"
            onClick={() => setThreadsOpen(true)}
            aria-label={t("Chats")}
            className={cx(
              "relative flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-fg/80 hover:text-fg",
              activeThread !== "main" && "text-accent",
            )}
          >
            <Menu size={20} />
            {threads.length > 1 && <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-accent" />}
          </button>
          <button type="button" className="flex min-w-0 flex-1 flex-col items-center px-2 pt-0.5" onClick={() => setActivityOpen(true)}>
            <span className="relative">
              <Avatar profile={profile} status={status} size={48} />
              {queued > 0 && (
                <span className="pointer-events-none absolute -right-1 -top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full border-2 border-bg bg-rose-500 px-1 text-[10.5px] font-bold text-white">
                  {queued}
                </span>
              )}
            </span>
            <span className="mt-1 max-w-full truncate text-[13px] font-semibold leading-tight">{name}</span>
            <span
              className={cx(
                "mt-0.5 flex max-w-full items-center gap-1 truncate text-[12px] leading-tight",
                status.state === "idle" && !thread?.busy ? "text-muted" : "text-accent",
              )}
            >
              {(status.state === "working" || thread?.busy) && queued === 0 && <Loader2 size={11} className="shrink-0 animate-spin" />}
              <span className="truncate">{statusLine}</span>
            </span>
            {thread && thread.id !== "main" && (
              <span className="mt-1 rounded-full bg-surface-2 px-2.5 py-0.5 text-[11.5px] font-medium text-fg/80">{thread.title}</span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setActivityOpen(true)}
            aria-label={t("Menu")}
            className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-fg/80 hover:text-fg"
          >
            <MoreHorizontal size={20} />
          </button>
        </div>
      </header>

      {/* Timeline */}
      <div ref={listRef} onScroll={onScroll} className="relative flex-1 overflow-y-auto px-3 py-3 space-y-2.5">
        {state.hasMore[activeThread] && events.length > 0 && (
          <div className="flex justify-center">
            <button
              type="button"
              className="text-[12.5px] text-accent px-3 py-1 rounded-full bg-surface-2"
              onClick={() => void loadEvents(activeThread, events[0]?.id)}
            >
              {t("Load earlier messages")}
            </button>
          </div>
        )}
        {eventsLoaded && events.length === 0 && !stream && <EmptyChat name={name} onSend={(text) => void send(activeThread, text)} />}
        {events.map((ev, i) => (
          <EventView
            key={ev.id}
            event={ev}
            prev={events[i - 1]}
            name={name}
            onDecide={(approved, scope) =>
              decide(ev.id, approved, scope).catch((e: Error) => toast(e.message || t("Could not send decision")))
            }
            onOpenFile={openFile}
            onOpenBrowser={setBrowserView}
            files={files}
          />
        ))}
        {stream && stream.text && (
          <AssistantBubble text={stream.text} streaming files={files} onOpenFile={openFile} />
        )}
        {(thread?.busy || status.state !== "idle") && !stream?.text && status.state !== "waiting" && (
          <TypingIndicator label={thread?.queued ? t("{n} queued", { n: thread.queued }) : undefined} />
        )}
        {showJump && (
          <button
            type="button"
            onClick={jumpToBottom}
            className="sticky bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-surface border border-border shadow px-3 py-1.5 text-[12.5px] flex items-center gap-1"
          >
            <ChevronDown size={14} /> {t("Latest")}{pendingApprovals ? ` · ${t("{n} approval", { n: pendingApprovals })}` : ""}
          </button>
        )}
      </div>

      <Composer
        name={name}
        busy={!!thread?.busy && pendingApprovals === 0}
        waiting={events.some((e) => e.type === "question" && e.status === "pending")}
        onSend={(text, files) => send(activeThread, text, files).catch((e: Error) => toast(e.message || t("Could not send")))}
      />

      <MuseSheet open={activityOpen} onClose={() => setActivityOpen(false)} />
      {browserView && <BrowserViewer thread={activeThread} eventId={browserView} onClose={() => setBrowserView(null)} />}
      <ThreadsSheet
        open={threadsOpen}
        onClose={() => setThreadsOpen(false)}
        threads={threads}
        active={activeThread}
        onPick={(id) => {
          openThread(id);
          setThreadsOpen(false);
        }}
      />
    </div>
  );
}

// ------------------------------------------------------------------ pieces
function EventView({
  event,
  prev,
  name,
  onDecide,
  onOpenFile,
  onOpenBrowser,
  files,
}: {
  event: TimelineEvent;
  prev?: TimelineEvent;
  name: string;
  onDecide: (approved: boolean, scope: string) => void;
  onOpenFile: (path: string) => void;
  onOpenBrowser: (id: string) => void;
  files: readonly string[];
}) {
  // a small centred time, iMessage style, when the conversation pauses for a while
  const divider = needsDivider(prev, event) ? <TimeDivider ts={event.ts} /> : null;
  const body = (() => {
    switch (event.type) {
      case "user":
        return <UserBubble event={event} onOpenFile={onOpenFile} />;
      case "assistant":
        if (event.quiet) return <QuietLine text={event.text} about={event.about} ts={event.ts} />;
        return (
          <AssistantBubble
            text={event.text}
            reasoning={event.reasoning}
            continued={prev?.type === "assistant"}
            files={files}
            onOpenFile={onOpenFile}
          />
        );
      case "tool":
        return <ToolChip event={event} />;
      case "approval":
        return <ApprovalCard event={event} name={name} onDecide={onDecide} />;
      case "question":
        return <QuestionCard event={event} name={name} />;
      case "notice":
        return <Notice event={event} />;
      case "artifact":
        return <ArtifactCard event={event} onOpen={onOpenFile} />;
      case "browser":
        return <BrowserCard event={event} onOpen={onOpenBrowser} />;
      default:
        return null;
    }
  })();
  if (!body) return null;
  return (
    <>
      {divider}
      {body}
    </>
  );
}

const DIVIDER_GAP_MS = 10 * 60 * 1000;

function needsDivider(prev: TimelineEvent | undefined, event: TimelineEvent): boolean {
  if (!event.ts) return false;
  if (!prev?.ts) return true;
  return new Date(event.ts).getTime() - new Date(prev.ts).getTime() >= DIVIDER_GAP_MS;
}

function TimeDivider({ ts }: { ts?: string }) {
  const label = timeDivider(ts);
  if (!label) return null;
  return <div className="pt-2 pb-0.5 text-center text-[11.5px] font-medium text-muted">{label}</div>;
}

function UserBubble({ event, onOpenFile }: { event: UserEvent; onOpenFile: (path: string) => void }) {
  const files = event.files ?? [];
  const pictures = files.filter((f) => f.kind === "image");
  const others = files.filter((f) => f.kind !== "image");
  return (
    <div className="rise flex flex-col items-end pl-12">
      {pictures.length > 0 && (
        <div className="mb-1 flex max-w-full flex-wrap justify-end gap-1.5">
          {pictures.map((f) => (
            <button
              key={f.path}
              type="button"
              onClick={() => onOpenFile(f.path)}
              aria-label={f.name}
              className={cx("overflow-hidden rounded-2xl border border-border/60 bg-surface-2 shadow-sm active:scale-[0.98] transition", pictures.length === 1 ? "max-h-64 max-w-[240px]" : "h-28 w-28")}
            >
              <img src={fileUrl(f.path)} alt={f.name} loading="lazy" className={cx("object-cover", pictures.length === 1 ? "max-h-64 w-auto max-w-full" : "h-full w-full")} />
            </button>
          ))}
        </div>
      )}
      {others.map((f) => (
        <button
          key={f.path}
          type="button"
          onClick={() => onOpenFile(f.path)}
          className="mb-1 flex max-w-full items-center gap-2.5 rounded-2xl border border-border bg-surface px-3 py-2 text-left shadow-sm hover:bg-surface-2 active:scale-[0.98] transition"
        >
          <span className="rounded-xl bg-accent/12 p-2 text-accent">{f.kind === "data" ? <Table2 size={17} /> : <FileText size={17} />}</span>
          <span className="min-w-0">
            <span className="block truncate text-[14px] font-medium">{f.name}</span>
            <span className="block text-[11.5px] text-muted">{fileSize(f.size)}</span>
          </span>
        </button>
      ))}
      {event.text && (
        <div className="bubble-user max-w-full rounded-[20px] rounded-br-md bg-bubble-user px-4 py-2.5 text-bubble-user-fg">
          <div className="md text-[15px] leading-[1.45] whitespace-pre-wrap break-words">{event.text}</div>
        </div>
      )}
    </div>
  );
}

function fileSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** A file picked in the composer: uploading, uploaded, or failed. */
interface Pending {
  key: string;
  file: File;
  preview: string | null;
  info: AttachmentInfo | null;
  error: string | null;
}

function chipKind(name: string): "data" | "other" {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  return ["csv", "tsv", "json", "xlsx", "xls"].includes(ext) ? "data" : "other";
}

const ACCEPT = "image/*,.pdf,.txt,.md,.csv,.tsv,.json,.log,.html,.xml,.yaml,.yml,.toml,.ics,.vcf,.xlsx,.xls,.docx";

function AssistantBubble({
  text,
  reasoning,
  streaming,
  continued,
  files,
  onOpenFile,
}: {
  text: string;
  reasoning?: string;
  streaming?: boolean;
  continued?: boolean;
  files?: readonly string[];
  onOpenFile?: (path: string) => void;
}) {
  const [showReasoning, setShowReasoning] = useState(false);
  const t = useT();
  return (
    <div className={cx("rise flex items-end gap-2 pr-10", continued && "-mt-1")}>
      <div className="min-w-0 max-w-full">
        {reasoning && (
          <button type="button" className="mb-1 ml-1 text-[12px] text-muted" onClick={() => setShowReasoning((s) => !s)}>
            {showReasoning ? t("Hide thinking") : t("Show thinking")}
          </button>
        )}
        {reasoning && showReasoning && (
          <div className="mb-1.5 rounded-2xl bg-surface-2/70 px-3 py-2 text-[13px] text-muted whitespace-pre-wrap break-words">
            {reasoning}
          </div>
        )}
        <div className="rounded-[20px] rounded-bl-md bg-surface-2 px-4 py-2.5">
          <Markdown text={text} files={files} onOpenFile={onOpenFile} />
          {streaming && <span className="inline-block w-1.5 h-4 ml-0.5 align-middle bg-accent/70 animate-pulse rounded-sm" />}
        </div>
      </div>
    </div>
  );
}

/** A background pass that found nothing worth interrupting you for: one muted line, not a bubble. */
function QuietLine({ text, about, ts }: { text: string; about?: string; ts?: string }) {
  const [open, setOpen] = useState(false);
  const t = useT();
  const label = about ? localLabel(about.replace(/^Working on your goal: /, "")) : t("background check");
  return (
    <div className="rise flex justify-center px-6">
      <button type="button" onClick={() => setOpen((o) => !o)} className="max-w-full rounded-2xl px-3 py-1.5 text-[12px] text-muted text-center leading-snug">
        <span className="inline-flex items-center gap-1.5">
          <Moon size={12} /> {t("Checked on {label} — nothing new", { label })}{ts ? ` · ${timeShort(ts)}` : ""}
        </span>
        {open && <span className="block mt-1 text-left whitespace-pre-wrap text-[12.5px]">{text}</span>}
      </button>
    </div>
  );
}

function TypingIndicator({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="rounded-[20px] rounded-bl-md bg-surface-2 px-3.5 py-2.5 flex items-center gap-1">
        <span className="typing-dot h-2 w-2 rounded-full bg-muted" />
        <span className="typing-dot h-2 w-2 rounded-full bg-muted" />
        <span className="typing-dot h-2 w-2 rounded-full bg-muted" />
      </div>
      {label && <span className="text-[12px] text-muted">{label}</span>}
    </div>
  );
}

function EmptyChat({ name, onSend }: { name: string; onSend: (text: string) => void }) {
  const { state } = useStore();
  const t = useT();
  const starters = [
    t("What can you do for me?"),
    t("Plan my week — ask me what's on my plate"),
    t("Research and compare two options for me"),
    t("Set up a long-term goal and track it"),
  ];
  return (
    <div className="flex flex-col items-center text-center px-6 pt-8 pb-6 gap-3">
      <Avatar profile={state.profile} size={96} />
      <div className="text-[20px] font-semibold">{t("Hi, I'm {name}.", { name })}</div>
      <p className="text-muted text-[14.5px] leading-snug max-w-sm">
        {t("I don't just answer — I get things done: research, plans, files, code, email, long-running goals. Everything I do shows up here, and anything hard to undo waits for your approval.")}
      </p>
      <div className="mt-2 flex flex-wrap justify-center gap-2">
        {starters.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSend(s)}
            className="rounded-full bg-surface-2 px-3.5 py-1.5 text-[13.5px] hover:bg-border/60"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function Composer({
  name,
  busy,
  waiting,
  onSend,
}: {
  name: string;
  busy: boolean;
  waiting: boolean;
  onSend: (text: string, files: string[]) => void;
}) {
  const { state, draft, toast } = useStore();
  const [text, setText] = useState("");
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const t = useT();

  // previews are object URLs; let them go when the chip goes
  useEffect(() => () => pending.forEach((p) => p.preview && URL.revokeObjectURL(p.preview)), [pending]);

  const addFiles = (list: FileList | File[]) => {
    const files = Array.from(list).slice(0, Math.max(0, 10 - pending.length));
    if (files.length === 0) return;
    const items: Pending[] = files.map((file) => ({
      key: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 7)}`,
      file,
      preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : null,
      info: null,
      error: null,
    }));
    setPending((cur) => [...cur, ...items]);
    for (const item of items) {
      api.upload(item.file)
        .then((info) => setPending((cur) => cur.map((p) => (p.key === item.key ? { ...p, info } : p))))
        .catch((e: Error) => {
          setPending((cur) => cur.map((p) => (p.key === item.key ? { ...p, error: e.message || t("Upload failed") } : p)));
          toast(e.message || t("Upload failed"));
        });
    }
  };
  const remove = (key: string) => setPending((cur) => cur.filter((p) => p.key !== key));
  const uploading = pending.some((p) => !p.info && !p.error);
  const attached = pending.filter((p) => p.info).map((p) => p.info!.path);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  // text handed over from another screen (a skill's "Use" button)
  useEffect(() => {
    if (state.draft === null) return;
    setText(state.draft);
    draft(null);
    const el = ref.current;
    if (el) {
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.draft]);

  // "/" at the start of the message offers the skills; the list is small and cached
  const skillsOn = state.settings?.skills?.enabled !== false;
  useEffect(() => {
    if (!skillsOn) return;
    api.skills()
      .then((d) => setSkills(d.skills.filter((sk) => sk.enabled)))
      .catch(() => setSkills([]));
  }, [skillsOn, state.skillsVersion]);
  const slash = /^\/([a-z0-9-]*)$/i.exec(text);
  const matches = slash ? skills.filter((sk) => sk.name.startsWith(slash[1].toLowerCase())).slice(0, 6) : [];
  const pick = (sk: SkillInfo) => {
    setText(`/${sk.name} `);
    ref.current?.focus();
  };

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const trimmed = text.trim();
    if ((!trimmed && attached.length === 0) || uploading) return;
    onSend(trimmed, attached);
    setText("");
    setPending([]);
    ref.current?.focus();
  };

  return (
    <form onSubmit={submit} className="shrink-0 bg-bg px-3 pt-1.5 pb-1">
      {busy && !waiting && (
        <div className="px-2 pb-1 text-[12px] text-muted">{t("{name} is working — anything you send now is picked up right away.", { name })}</div>
      )}
      {matches.length > 0 && (
        <ul className="mb-2 max-h-72 overflow-y-auto rounded-3xl border border-border/70 bg-surface shadow-lg divide-y divide-border/70" role="listbox" aria-label={t("Skills")}>
          {matches.map((sk) => (
            <li key={sk.name}>
              <button type="button" onClick={() => pick(sk)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-surface-2/70 active:bg-surface-2">
                <Wand2 size={16} className="shrink-0 text-accent" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-medium">/{sk.name}</span>
                  <span className="block truncate text-[12.5px] text-muted">{sk.description}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {pending.length > 0 && (
        <div className="mb-1 flex gap-2.5 overflow-x-auto px-1 pt-2.5 pb-1 pr-3" role="list" aria-label={t("Attachments")}>
          {pending.map((p) => (
            <div key={p.key} role="listitem" className={cx("relative shrink-0 rounded-2xl border bg-surface-2", p.error ? "border-danger/60" : "border-border/70")}>
              {p.preview ? (
                <img src={p.preview} alt={p.file.name} className="h-16 w-16 rounded-2xl object-cover" />
              ) : (
                <div className="flex h-16 w-40 items-center gap-2 px-2.5">
                  <span className="rounded-xl bg-accent/12 p-1.5 text-accent">{chipKind(p.file.name) === "data" ? <Table2 size={16} /> : <FileText size={16} />}</span>
                  <span className="min-w-0">
                    <span className="block truncate text-[12.5px] font-medium">{p.file.name}</span>
                    <span className="block text-[11px] text-muted">{p.error ? t("Upload failed") : fileSize(p.file.size)}</span>
                  </span>
                </div>
              )}
              {!p.info && !p.error && (
                <div className="absolute inset-0 flex items-center justify-center rounded-2xl bg-bg/50">
                  <Loader2 size={18} className="animate-spin text-accent" />
                </div>
              )}
              <button
                type="button"
                onClick={() => remove(p.key)}
                aria-label={t("Remove")}
                className="absolute -right-1.5 -top-1.5 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-muted shadow-sm"
              >
                <X size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2 rounded-[26px] border border-border bg-surface px-1.5 py-1.5 shadow-[0_2px_12px_-6px_rgba(0,0,0,0.12)] focus-within:border-fg/20">
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          aria-label={t("Attach a file")}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg/70 transition hover:bg-surface-2 active:scale-95"
        >
          <Plus size={22} />
        </button>
        <textarea
          ref={ref}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={(e) => {
            const files = Array.from(e.clipboardData?.files ?? []);
            if (files.length > 0) {
              e.preventDefault();
              addFiles(files);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Tab" && matches.length > 0 && matches[0]) {
              e.preventDefault();
              pick(matches[0]);
              return;
            }
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder={waiting ? t("Answer {name}…", { name }) : pending.length > 0 ? t("Say what to do with it…") : t("Message")}
          className="flex-1 resize-none bg-transparent px-1 py-2 text-[15px] leading-[1.4] outline-none placeholder:text-muted"
        />
        <button
          type="submit"
          disabled={(!text.trim() && attached.length === 0) || uploading}
          aria-label={t("Send")}
          className={cx(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition active:scale-95",
            text.trim() || attached.length > 0 ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted",
            "disabled:opacity-60",
          )}
        >
          <ArrowUp size={19} strokeWidth={2.5} />
        </button>
      </div>
    </form>
  );
}

function ThreadsSheet({
  open,
  onClose,
  threads,
  active,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  threads: ThreadMeta[];
  active: string;
  onPick: (id: string) => void;
}) {
  const { toast, dispatch } = useStore();
  const t = useT();
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const create = async () => {
    setCreating(true);
    try {
      const created = await api.createThread(title.trim() || t("Side chat"));
      dispatch({ type: "ws", msg: { kind: "thread", thread: created } });
      setTitle("");
      onPick(created.id);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm(t("Delete this side chat and its history?"))) return;
    try {
      await api.deleteThread(id);
      dispatch({ type: "ws", msg: { kind: "thread_deleted", thread: id } });
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const clear = async (id: string) => {
    if (!window.confirm(t("Clear this conversation? Memory and goals are kept."))) return;
    try {
      await api.clearThread(id);
      dispatch({ type: "ws", msg: { kind: "thread_cleared", thread: id } });
      onClose();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title={t("Chats")}>
      <p className="text-[13px] text-muted mb-3">
        {t("The main chat is one long conversation. Side chats keep a separate context for a project — memory, goals and approvals are shared.")}
      </p>
      <ul className="divide-y divide-border rounded-2xl border border-border overflow-hidden">
        {threads.map((th) => (
          <li key={th.id} className={cx("flex items-center gap-2 px-3 py-2.5", th.id === active && "bg-surface-2/60")}>
            <button type="button" onClick={() => onPick(th.id)} className="flex-1 text-left min-w-0">
              <div className="font-medium text-[15px] truncate flex items-center gap-2">
                {th.id === "main" ? t(th.title) : th.title}
                {th.busy && <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />}
              </div>
              <div className="text-[12px] text-muted">
                {t("{n} events", { n: th.events })}{th.queued ? ` · ${t("{n} queued", { n: th.queued })}` : ""} · {timeShort(th.updated_at)}
              </div>
            </button>
            <button type="button" aria-label={t("Clear")} onClick={() => void clear(th.id)} className="p-2 text-muted hover:text-fg">
              <X size={16} />
            </button>
            {th.id !== "main" && (
              <button type="button" aria-label={t("Delete")} onClick={() => void remove(th.id)} className="p-2 text-muted hover:text-rose-500">
                <Trash2 size={16} />
              </button>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-4 flex gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t("New side chat, e.g. “Trip to Kyoto”")}
          className="flex-1 rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40"
        />
        <button
          type="button"
          disabled={creating}
          onClick={() => void create()}
          className="rounded-2xl bg-accent text-accent-fg px-3.5 py-2.5 flex items-center gap-1.5 font-medium disabled:opacity-50"
        >
          <MessageSquarePlus size={18} /> {t("New")}
        </button>
      </div>
    </Sheet>
  );
}
