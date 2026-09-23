import {
  AlertTriangle,
  Ban,
  Bot,
  Brain,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  FileText,
  Globe,
  Loader2,
  Mail,
  MessageCircleQuestion,
  Search,
  ShieldAlert,
  Target,
  Terminal,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { fileUrl, frameUrl } from "../api";
import { t, useT } from "../i18n";
import type {
  ApprovalEvent,
  ArtifactEvent,
  BrowserEvent,
  NoticeEvent,
  QuestionEvent,
  RiskLevel,
  ToolEvent,
} from "../types";
import { cx, fileKind, timeShort } from "../util";

// ------------------------------------------------------------------ helpers
export function toolIcon(tool: string, size = 15): ReactNode {
  switch (tool) {
    case "web_search":
      return <Search size={size} />;
    case "web_fetch":
    case "browser":
      return <Globe size={size} />;
    case "files":
      return <FileText size={size} />;
    case "shell":
      return <Terminal size={size} />;
    case "python_execute":
      return <Code2 size={size} />;
    case "read_emails":
    case "send_email":
      return <Mail size={size} />;
    case "goals":
      return <Target size={size} />;
    case "remember":
    case "recall":
    case "forget":
      return <Brain size={size} />;
    case "ask_user":
      return <MessageCircleQuestion size={size} />;
    default:
      return <Bot size={size} />;
  }
}

const RISK_STYLE: Record<RiskLevel, string> = {
  safe: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  moderate: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  sensitive: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
};

export function RiskBadge({ risk }: { risk: RiskLevel }) {
  return (
    <span className={cx("px-2 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide", RISK_STYLE[risk])}>
      {t(risk)}
    </span>
  );
}

function ArgsList({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args ?? {}).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (!entries.length) return null;
  return (
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="break-words whitespace-pre-wrap font-mono text-[12.5px] leading-snug">{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

// ------------------------------------------------------------------ tool activity chip
export function ToolChip({ event }: { event: ToolEvent }) {
  const [open, setOpen] = useState(false);
  const icon =
    event.status === "running" ? (
      <Loader2 size={14} className="animate-spin text-accent" />
    ) : event.status === "ok" ? (
      <Check size={14} className="text-emerald-500" />
    ) : event.status === "blocked" ? (
      <Ban size={14} className="text-rose-500" />
    ) : (
      <X size={14} className="text-rose-500" />
    );
  return (
    <div className="rise flex justify-start pr-8">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="max-w-full text-left rounded-2xl bg-surface-2/80 border border-border/60 px-3 py-1.5 text-[13px] text-muted hover:text-fg transition"
      >
        <span className="flex items-center gap-2">
          <span className="text-muted">{toolIcon(event.tool)}</span>
          <span className="truncate flex-1">{event.summary || event.tool}</span>
          {icon}
          {event.output ? open ? <ChevronDown size={13} /> : <ChevronRight size={13} /> : null}
        </span>
        {open && (
          <div className="mt-2 text-fg">
            <ArgsList args={event.args} />
            {event.output && (
              <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-bg p-2 text-[12px] leading-snug">
                {event.output}
              </pre>
            )}
          </div>
        )}
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ approval card
/** What a permission is for, in words: "git commands", "email to alice@…", "example.com". */
export function grantSubject(tool: string, target?: string | null): string {
  if (!target) return tool.replace(/_/g, " ");
  switch (tool) {
    case "shell":
      return t("{what} commands", { what: target.split(",").join(", ") });
    case "send_email":
      return t("email to {who}", { who: target.split(",").join(", ") });
    default:
      return target;
  }
}

export function scopeLabel(scope: string, tool: string, target?: string | null): string {
  switch (scope) {
    case "once":
      return t("Once");
    case "task":
      return t("For this task");
    case "session":
      return t("Until restart");
    case "24h":
      return t("For 24 hours");
    case "always":
      return t("Always for {subject}", { subject: grantSubject(tool, target) });
    default:
      return scope;
  }
}

export function ApprovalCard({
  event,
  name = "OpenMuse",
  onDecide,
}: {
  event: ApprovalEvent;
  name?: string;
  onDecide: (approved: boolean, scope: string) => void;
}) {
  const [showArgs, setShowArgs] = useState(false);
  const [more, setMore] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const t = useT();
  const pending = event.status === "pending";
  const sensitive = event.risk === "sensitive";
  const standing = (event.grant_options ?? ["once"]).filter((s) => s !== "once");
  const host = event.target || event.egress_target;
  // Expanding the card near the bottom of the chat must not hide the new buttons under the tab bar.
  useEffect(() => {
    if (more || showArgs) cardRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [more, showArgs]);
  return (
    <div className="rise flex justify-start pr-4" ref={cardRef}>
      <div
        className={cx(
          "w-full max-w-md overflow-hidden rounded-[22px] border bg-surface shadow-[0_4px_20px_-10px_rgba(0,0,0,0.18)]",
          pending ? (sensitive ? "border-rose-400/60" : "border-border") : "border-border/70",
        )}
      >
        <div className="flex items-start gap-3 px-4 pt-4 pb-2">
          <div className={cx("mt-0.5 rounded-full p-2", sensitive ? "bg-rose-500/12 text-rose-500" : "bg-surface-2 text-fg/80")}>
            {sensitive ? <ShieldAlert size={18} /> : toolIcon(event.tool, 18)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[12.5px] font-medium text-muted">{t("{name} wants to", { name })}</div>
            <div className="mt-0.5 break-words text-[15.5px] font-semibold leading-snug">{event.summary}</div>
            {host && (
              <div className="mt-1 flex items-center gap-1 text-[13px] text-muted">
                <Globe size={12} /> <span className="truncate">{t("at {host}", { host })}</span>
              </div>
            )}
            {event.purpose && <div className="mt-1.5 break-words text-[13px] leading-snug text-muted line-clamp-2">{event.purpose}</div>}
            {sensitive && (
              <div className="mt-1.5">
                <RiskBadge risk={event.risk} />
              </div>
            )}
          </div>
        </div>
        {event.warnings?.length > 0 && (
          <div className="space-y-1 px-4 pb-2">
            {event.warnings.map((w) => (
              <div key={w} className="flex items-start gap-1.5 text-[12.5px] text-rose-600 dark:text-rose-300">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" /> <span>{w}</span>
              </div>
            ))}
          </div>
        )}
        <div className="px-4 pb-2">
          <button type="button" className="flex items-center gap-1 text-[12.5px] text-accent" onClick={() => setShowArgs((s) => !s)}>
            {showArgs ? <ChevronDown size={13} /> : <ChevronRight size={13} />} {t("Exactly what will run")}
          </button>
          {showArgs && (
            <>
              <ArgsList args={event.args} />
              {event.reasons?.length > 0 && (
                <div className="mt-1.5 text-[12px] text-muted">{t("Why it asks: {reasons}", { reasons: event.reasons.join(" · ") })}</div>
              )}
            </>
          )}
        </div>
        {pending ? (
          <div className="flex flex-col gap-2 px-3 pb-3 pt-1">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onDecide(false, "once")}
                className="flex-1 rounded-full bg-surface-2 py-2.5 text-[15px] font-semibold transition active:scale-[0.98]"
              >
                {t("Deny")}
              </button>
              <button
                type="button"
                onClick={() => onDecide(true, "once")}
                className="flex-1 rounded-full bg-accent py-2.5 text-[15px] font-semibold text-accent-fg transition active:scale-[0.98]"
              >
                {t("Allow")}
              </button>
            </div>
            {standing.length > 0 ? (
              <>
                <button type="button" className="self-center text-[12.5px] text-muted" onClick={() => setMore((m) => !m)}>
                  {more ? t("Fewer options") : t("Allow {subject} for longer…", { subject: grantSubject(event.tool, event.target) })}
                </button>
                {more && (
                  <div className="grid grid-cols-2 gap-2">
                    {standing.map((scope) => (
                      <button
                        key={scope}
                        type="button"
                        onClick={() => onDecide(true, scope)}
                        className="rounded-2xl bg-surface-2 px-3 py-2 text-left text-[13px] font-medium leading-snug"
                      >
                        {scopeLabel(scope, event.tool, event.target)}
                      </button>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div className="self-center text-[12px] text-muted">{t("This kind of action is approved one at a time.")}</div>
            )}
          </div>
        ) : (
          <div
            className={cx(
              "flex items-center gap-1.5 border-t border-border px-4 py-2.5 text-[13px] font-medium",
              event.status === "approved" ? "text-emerald-600 dark:text-emerald-300" : "text-muted",
            )}
          >
            {event.status === "approved" ? <Check size={15} /> : <X size={15} />}
            {event.status === "approved"
              ? `${t("Approved")}${event.scope && event.scope !== "once" ? ` · ${scopeLabel(event.scope, event.tool, event.target).toLowerCase()}` : ""}`
              : event.status === "denied"
                ? t("Denied")
                : t("Expired without an answer")}
            <span className="ml-auto font-normal">{timeShort(event.updated_ts ?? event.ts)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ question card
export function QuestionCard({ event, name }: { event: QuestionEvent; name: string }) {
  const t = useT();
  return (
    <div className="rise flex justify-start pr-8">
      <div className="max-w-full rounded-[20px] rounded-bl-md border border-accent/30 bg-surface px-4 py-3">
        <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-accent">
          <MessageCircleQuestion size={14} /> {t("{name} asks", { name })}
        </div>
        <div className="mt-1 text-[15px] leading-snug whitespace-pre-wrap break-words">{event.text}</div>
        {event.status === "pending" && <div className="mt-1.5 text-[12.5px] text-muted">{t("Reply below to continue.")}</div>}
        {event.status === "answered" && event.answer && (
          <div className="mt-2 text-[13px] text-muted border-t border-border pt-2">
            {t("You:")} <span className="text-fg">{event.answer}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ notice
export function Notice({ event }: { event: NoticeEvent }) {
  return (
    <div className="rise flex justify-center px-6">
      <div
        className={cx(
          "max-w-full rounded-2xl px-3 py-1.5 text-center text-[12.5px] leading-snug",
          event.level === "info" && "bg-surface-2/70 text-muted",
          event.level === "warn" && "bg-amber-500/12 text-amber-700 dark:text-amber-300",
          event.level === "error" && "bg-rose-500/12 text-rose-700 dark:text-rose-300",
        )}
      >
        {event.text}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ artifact
/** A file the agent made. Opens in the in-app viewer (pages render sandboxed, never with the app's origin). */
/** The agent's browser, as a card: the latest frame, where it is, what it just did. */
export function BrowserCard({ event, onOpen }: { event: BrowserEvent; onOpen: (id: string) => void }) {
  const [gone, setGone] = useState(false);
  const t = useT();
  const live = event.status === "live";
  let host = event.url;
  try {
    host = new URL(event.url).host;
  } catch {
    /* keep the raw url */
  }
  return (
    <div className="rise flex justify-start pr-8">
      <button
        type="button"
        onClick={() => onOpen(event.id)}
        aria-label={t("Browser: {title}", { title: event.title || host })}
        className="w-full max-w-[340px] overflow-hidden rounded-3xl rounded-tl-lg border border-border bg-surface shadow-sm hover:bg-surface-2 transition text-left"
      >
        <div className="relative aspect-[16/10] bg-surface-2">
          {gone ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-muted">
              <Globe size={22} />
              <span className="text-[12px]">{t("Frame no longer available")}</span>
            </div>
          ) : (
            <img
              key={event.frame}
              src={frameUrl(event.thread, event.frame)}
              alt={event.title || host}
              onError={() => setGone(true)}
              className="absolute inset-0 h-full w-full object-cover object-top"
            />
          )}
          <div className="absolute left-2.5 top-2.5 flex items-center gap-1.5 rounded-full bg-black/60 px-2 py-0.5 text-[10.5px] font-semibold text-white">
            {live ? (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-rose-400 animate-pulse" /> {t("LIVE")}
              </>
            ) : (
              <>
                <Globe size={11} /> {t("BROWSER")}
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 px-3.5 py-2.5">
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-medium truncate">{event.title || host}</div>
            <div className="text-[12px] text-muted truncate">
              {event.by_user ? t("You") : ""}
              {event.by_user && event.action.startsWith("You") ? event.action.slice(3) : event.action} · {host}
            </div>
          </div>
          <ChevronRight size={16} className="text-muted shrink-0" />
        </div>
      </button>
    </div>
  );
}

export function ArtifactCard({ event, onOpen }: { event: ArtifactEvent; onOpen: (path: string) => void }) {
  const t = useT();
  const kind = fileKind(event.name);
  const what =
    kind === "html" ? t("Page") : kind === "image" ? t("Image") : kind === "data" ? t("Data") : kind === "code" ? t("Code") : kind === "event" ? t("Event") : t("Document");
  const label = event.action === "update" ? `${what} · ${t("updated")}` : what;
  const preview = kind === "html" || kind === "image";
  return (
    <div className="rise flex justify-start pr-8">
      <button
        type="button"
        onClick={() => onOpen(event.path)}
        className={cx(
          "max-w-full overflow-hidden rounded-[20px] border border-border bg-surface text-left shadow-[0_4px_20px_-12px_rgba(0,0,0,0.2)] transition hover:bg-surface-2",
          preview ? "w-[300px]" : "",
        )}
      >
        {preview && <ArtifactPreview path={event.path} kind={kind} />}
        <div className="flex items-center gap-3 px-4 py-3">
          {!preview && (
            <div className="rounded-2xl bg-accent/12 p-2.5 text-accent">
              {kind === "code" ? <Code2 size={20} /> : kind === "event" ? <CalendarDays size={20} /> : <FileText size={20} />}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</div>
            <div className="truncate text-[14.5px] font-medium">{event.name}</div>
            <div className="truncate text-[12px] text-muted">{event.path}</div>
          </div>
          <ChevronRight size={16} className="ml-1 shrink-0 text-muted" />
        </div>
      </button>
    </div>
  );
}

/** A small, non-interactive look at a page or picture the agent made — the file itself opens on tap. */
function ArtifactPreview({ path, kind }: { path: string; kind: "html" | "image" }) {
  if (kind === "image") {
    return <img src={fileUrl(path)} alt="" loading="lazy" className="h-40 w-full object-cover" />;
  }
  return (
    <div className="pointer-events-none relative h-40 w-full overflow-hidden bg-white">
      <iframe
        title={path}
        src={fileUrl(path)}
        sandbox=""
        tabIndex={-1}
        loading="lazy"
        scrolling="no"
        className="absolute left-0 top-0 h-[480px] w-[900px] origin-top-left scale-[0.3333] border-0"
      />
    </div>
  );
}
