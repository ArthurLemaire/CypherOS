import { ArrowUp, ChevronDown, MessageSquarePlus, Moon, MoreHorizontal, Plus, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { Avatar } from "../components/Avatar";
import { ApprovalCard, ArtifactCard, Notice, QuestionCard, ToolChip } from "../components/Cards";
import { Markdown } from "../components/Markdown";
import { Sheet } from "../components/Sheet";
import { useStore } from "../store";
import type { ThreadMeta, TimelineEvent, UserEvent } from "../types";
import { cx, timeShort } from "../util";
import { MuseSheet } from "./MuseSheet";

export function ChatScreen() {
  const { state, send, decide, loadEvents, openThread, openFile, toast } = useStore();
  const { profile, status, activeThread, threads } = state;
  const events = state.events[activeThread] ?? [];
  // undefined until the first fetch for this thread has returned — don't flash the empty state
  const eventsLoaded = state.events[activeThread] !== undefined;
  const stream = state.streams[activeThread];
  const thread = threads.find((t) => t.id === activeThread);
  const [activityOpen, setActivityOpen] = useState(false);
  const [threadsOpen, setThreadsOpen] = useState(false);
  const name = profile?.name ?? "Muse";

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
    if (queued > 0 && status.state !== "working") return `${queued} approval${queued > 1 ? "s" : ""} waiting for you`;
    if (status.state === "idle" && !thread?.busy) return "Idle · tap the avatar for activity";
    if (status.detail) return status.detail;
    return status.state === "waiting" ? "Waiting for you" : "Working…";
  }, [status, thread, queued]);

  const pendingApprovals = events.filter((e) => e.type === "approval" && e.status === "pending").length;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="safe-top shrink-0 border-b border-border bg-surface/85 backdrop-blur">
        <div className="flex items-center gap-3 px-4 py-2.5">
          <div className="relative">
            <Avatar profile={profile} status={status} size={42} onClick={() => setActivityOpen(true)} />
            {queued > 0 && (
              <span className="pointer-events-none absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500 text-white text-[10.5px] font-bold flex items-center justify-center border-2 border-bg">
                {queued}
              </span>
            )}
          </div>
          <button type="button" className="flex-1 min-w-0 text-left" onClick={() => setActivityOpen(true)}>
            <div className="font-semibold text-[16px] leading-tight truncate">{name}</div>
            <div
              className={cx(
                "text-[12.5px] truncate",
                status.state === "idle" && !thread?.busy ? "text-muted" : "text-accent",
              )}
            >
              {statusLine}
            </div>
          </button>
          <button
            type="button"
            onClick={() => setThreadsOpen(true)}
            aria-label="Chats"
            className="p-2 rounded-full text-muted hover:bg-surface-2"
          >
            <MoreHorizontal size={22} />
          </button>
        </div>
        <ThreadStrip threads={threads} active={activeThread} onPick={openThread} onNew={() => setThreadsOpen(true)} />
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
              Load earlier messages
            </button>
          </div>
        )}
        {eventsLoaded && events.length === 0 && !stream && <EmptyChat name={name} emoji={profile?.emoji ?? "✨"} onSend={(t) => void send(activeThread, t)} />}
        {events.map((ev, i) => (
          <EventView
            key={ev.id}
            event={ev}
            prev={events[i - 1]}
            name={name}
            onDecide={(approved, scope) =>
              decide(ev.id, approved, scope).catch((e: Error) => toast(e.message || "Could not send decision"))
            }
            onOpenFile={openFile}
          />
        ))}
        {stream && stream.text && (
          <AssistantBubble text={stream.text} streaming />
        )}
        {(thread?.busy || status.state !== "idle") && !stream?.text && status.state !== "waiting" && (
          <TypingIndicator label={thread?.queued ? `${thread.queued} queued` : undefined} />
        )}
        {showJump && (
          <button
            type="button"
            onClick={jumpToBottom}
            className="sticky bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-surface border border-border shadow px-3 py-1.5 text-[12.5px] flex items-center gap-1"
          >
            <ChevronDown size={14} /> Latest{pendingApprovals ? ` · ${pendingApprovals} approval` : ""}
          </button>
        )}
      </div>

      <Composer
        name={name}
        busy={!!thread?.busy && pendingApprovals === 0}
        waiting={events.some((e) => e.type === "question" && e.status === "pending")}
        onSend={(text) => send(activeThread, text).catch((e: Error) => toast(e.message || "Could not send"))}
      />

      <MuseSheet open={activityOpen} onClose={() => setActivityOpen(false)} />
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
function ThreadStrip({
  threads,
  active,
  onPick,
  onNew,
}: {
  threads: ThreadMeta[];
  active: string;
  onPick: (id: string) => void;
  onNew: () => void;
}) {
  if (threads.length <= 1) return null;
  return (
    <div className="no-scrollbar flex gap-2 overflow-x-auto px-4 pb-2.5">
      {threads.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onPick(t.id)}
          className={cx(
            "shrink-0 rounded-full px-3 py-1 text-[13px] flex items-center gap-1.5 border transition",
            t.id === active ? "bg-accent text-accent-fg border-accent" : "bg-surface-2 border-transparent text-fg",
          )}
        >
          {t.busy && <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />}
          {t.title}
        </button>
      ))}
      <button type="button" onClick={onNew} aria-label="New side chat" className="shrink-0 rounded-full px-2.5 py-1 bg-surface-2 text-muted">
        <Plus size={16} />
      </button>
    </div>
  );
}

function EventView({
  event,
  prev,
  name,
  onDecide,
  onOpenFile,
}: {
  event: TimelineEvent;
  prev?: TimelineEvent;
  name: string;
  onDecide: (approved: boolean, scope: string) => void;
  onOpenFile: (path: string) => void;
}) {
  switch (event.type) {
    case "user":
      return <UserBubble event={event} showTime={!prev || prev.type !== "user"} />;
    case "assistant":
      if (event.quiet) return <QuietLine text={event.text} about={event.about} ts={event.ts} />;
      return <AssistantBubble text={event.text} reasoning={event.reasoning} ts={event.ts} continued={prev?.type === "assistant"} />;
    case "tool":
      return <ToolChip event={event} />;
    case "approval":
      return <ApprovalCard event={event} onDecide={onDecide} />;
    case "question":
      return <QuestionCard event={event} name={name} />;
    case "notice":
      return <Notice event={event} />;
    case "artifact":
      return <ArtifactCard event={event} onOpen={onOpenFile} />;
    default:
      return null;
  }
}

function UserBubble({ event, showTime }: { event: UserEvent; showTime: boolean }) {
  return (
    <div className="rise flex flex-col items-end pl-12">
      <div className="bubble-user max-w-full rounded-3xl rounded-br-lg bg-accent text-accent-fg px-4 py-2.5 shadow-sm">
        <div className="md text-[15px] leading-[1.45] whitespace-pre-wrap break-words">{event.text}</div>
      </div>
      {showTime && <div className="mt-1 mr-1 text-[11px] text-muted">{timeShort(event.ts)}</div>}
    </div>
  );
}

function AssistantBubble({
  text,
  reasoning,
  ts,
  streaming,
  continued,
}: {
  text: string;
  reasoning?: string;
  ts?: string;
  streaming?: boolean;
  continued?: boolean;
}) {
  const [showReasoning, setShowReasoning] = useState(false);
  return (
    <div className={cx("rise flex items-end gap-2 pr-8", continued && "-mt-1")}>
      <div className="w-9 shrink-0" />
      <div className="min-w-0 max-w-full">
        {reasoning && (
          <button type="button" className="mb-1 ml-1 text-[12px] text-muted" onClick={() => setShowReasoning((s) => !s)}>
            {showReasoning ? "Hide thinking" : "Show thinking"}
          </button>
        )}
        {reasoning && showReasoning && (
          <div className="mb-1.5 rounded-2xl bg-surface-2/70 px-3 py-2 text-[13px] text-muted whitespace-pre-wrap break-words">
            {reasoning}
          </div>
        )}
        <div className="rounded-3xl rounded-bl-lg bg-surface border border-border/70 px-4 py-2.5 shadow-sm">
          <Markdown text={text} />
          {streaming && <span className="inline-block w-1.5 h-4 ml-0.5 align-middle bg-accent/70 animate-pulse rounded-sm" />}
        </div>
        {ts && <div className="mt-1 ml-1 text-[11px] text-muted">{timeShort(ts)}</div>}
      </div>
    </div>
  );
}

/** A background pass that found nothing worth interrupting you for: one muted line, not a bubble. */
function QuietLine({ text, about, ts }: { text: string; about?: string; ts?: string }) {
  const [open, setOpen] = useState(false);
  const label = about?.replace(/^Working on your goal: /, "") ?? "background check";
  return (
    <div className="rise flex justify-center px-6">
      <button type="button" onClick={() => setOpen((o) => !o)} className="max-w-full rounded-2xl px-3 py-1.5 text-[12px] text-muted text-center leading-snug">
        <span className="inline-flex items-center gap-1.5">
          <Moon size={12} /> Checked on {label} — nothing new{ts ? ` · ${timeShort(ts)}` : ""}
        </span>
        {open && <span className="block mt-1 text-left whitespace-pre-wrap text-[12.5px]">{text}</span>}
      </button>
    </div>
  );
}

function TypingIndicator({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 pl-11">
      <div className="rounded-3xl rounded-bl-lg bg-surface border border-border/70 px-3.5 py-2.5 flex items-center gap-1">
        <span className="typing-dot h-2 w-2 rounded-full bg-muted" />
        <span className="typing-dot h-2 w-2 rounded-full bg-muted" />
        <span className="typing-dot h-2 w-2 rounded-full bg-muted" />
      </div>
      {label && <span className="text-[12px] text-muted">{label}</span>}
    </div>
  );
}

function EmptyChat({ name, emoji, onSend }: { name: string; emoji: string; onSend: (t: string) => void }) {
  const starters = [
    "What can you do for me?",
    "Plan my week — ask me what's on my plate",
    "Research and compare two options for me",
    "Set up a long-term goal and track it",
  ];
  return (
    <div className="flex flex-col items-center text-center px-6 pt-10 pb-6 gap-3">
      <div className="text-5xl">{emoji}</div>
      <div className="text-[20px] font-semibold">Hi, I'm {name}.</div>
      <p className="text-muted text-[14.5px] leading-snug max-w-sm">
        I don't just answer — I get things done: research, plans, files, code, email, long-running goals. Everything I
        do shows up here, and anything hard to undo waits for your approval.
      </p>
      <div className="mt-2 flex flex-wrap justify-center gap-2">
        {starters.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSend(s)}
            className="rounded-full border border-border bg-surface px-3.5 py-1.5 text-[13.5px] hover:bg-surface-2"
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
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t) return;
    onSend(t);
    setText("");
    ref.current?.focus();
  };

  return (
    <form onSubmit={submit} className="safe-bottom shrink-0 border-t border-border bg-surface/90 backdrop-blur px-3 pt-2 pb-2">
      {busy && !waiting && (
        <div className="px-2 pb-1 text-[12px] text-muted">{name} is working — anything you send now is picked up right away.</div>
      )}
      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder={waiting ? `Answer ${name}…` : `Message ${name}`}
          className="flex-1 resize-none rounded-3xl bg-surface-2 px-4 py-2.5 text-[15px] leading-[1.4] outline-none placeholder:text-muted focus:ring-2 focus:ring-accent/40"
        />
        <button
          type="submit"
          disabled={!text.trim()}
          aria-label="Send"
          className="mb-0.5 h-10 w-10 shrink-0 rounded-full bg-accent text-accent-fg flex items-center justify-center disabled:opacity-40 active:scale-95 transition"
        >
          <ArrowUp size={20} strokeWidth={2.5} />
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
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const create = async () => {
    setCreating(true);
    try {
      const t = await api.createThread(title.trim() || "Side chat");
      dispatch({ type: "ws", msg: { kind: "thread", thread: t } });
      setTitle("");
      onPick(t.id);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm("Delete this side chat and its history?")) return;
    try {
      await api.deleteThread(id);
      dispatch({ type: "ws", msg: { kind: "thread_deleted", thread: id } });
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const clear = async (id: string) => {
    if (!window.confirm("Clear this conversation? Memory and goals are kept.")) return;
    try {
      await api.clearThread(id);
      dispatch({ type: "ws", msg: { kind: "thread_cleared", thread: id } });
      onClose();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Chats">
      <p className="text-[13px] text-muted mb-3">
        The main chat is one long conversation. Side chats keep a separate context for a project — memory, goals and
        approvals are shared.
      </p>
      <ul className="divide-y divide-border rounded-2xl border border-border overflow-hidden">
        {threads.map((t) => (
          <li key={t.id} className={cx("flex items-center gap-2 px-3 py-2.5", t.id === active && "bg-surface-2/60")}>
            <button type="button" onClick={() => onPick(t.id)} className="flex-1 text-left min-w-0">
              <div className="font-medium text-[15px] truncate flex items-center gap-2">
                {t.title}
                {t.busy && <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />}
              </div>
              <div className="text-[12px] text-muted">
                {t.events} events{t.queued ? ` · ${t.queued} queued` : ""} · {timeShort(t.updated_at)}
              </div>
            </button>
            <button type="button" aria-label="Clear" onClick={() => void clear(t.id)} className="p-2 text-muted hover:text-fg">
              <X size={16} />
            </button>
            {t.id !== "main" && (
              <button type="button" aria-label="Delete" onClick={() => void remove(t.id)} className="p-2 text-muted hover:text-rose-500">
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
          placeholder="New side chat, e.g. “Trip to Kyoto”"
          className="flex-1 rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40"
        />
        <button
          type="button"
          disabled={creating}
          onClick={() => void create()}
          className="rounded-2xl bg-accent text-accent-fg px-3.5 py-2.5 flex items-center gap-1.5 font-medium disabled:opacity-50"
        >
          <MessageSquarePlus size={18} /> New
        </button>
      </div>
    </Sheet>
  );
}
