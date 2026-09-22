import {
  AlertTriangle,
  Ban,
  Bot,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  FileText,
  Globe,
  Image as ImageIcon,
  Loader2,
  Mail,
  MessageCircleQuestion,
  Search,
  ShieldAlert,
  ShieldCheck,
  Target,
  Terminal,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { frameUrl } from "../api";
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
    <div className="rise flex justify-start pl-11 pr-8">
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
  onDecide,
}: {
  event: ApprovalEvent;
  onDecide: (approved: boolean, scope: string) => void;
}) {
  const [showArgs, setShowArgs] = useState(false);
  const [more, setMore] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const t = useT();
  const pending = event.status === "pending";
  const sensitive = event.risk === "sensitive";
  const standing = (event.grant_options ?? ["once"]).filter((s) => s !== "once");
  // Expanding the card near the bottom of the chat must not hide the new buttons under the tab bar.
  useEffect(() => {
    if (more || showArgs) cardRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [more, showArgs]);
  return (
    <div className="rise flex justify-start pl-11 pr-4" ref={cardRef}>
      <div
        className={cx(
          "w-full max-w-md rounded-3xl border bg-surface shadow-sm overflow-hidden",
          pending ? (sensitive ? "border-rose-400/60" : "border-amber-400/60") : "border-border",
        )}
      >
        <div className="px-4 pt-3.5 pb-2 flex items-start gap-3">
          <div
            className={cx(
              "mt-0.5 rounded-2xl p-2",
              sensitive ? "bg-rose-500/12 text-rose-500" : "bg-amber-500/12 text-amber-500",
            )}
          >
            {sensitive ? <ShieldAlert size={20} /> : <ShieldCheck size={20} />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <div className="font-semibold text-[15px]">{t("Approval needed")}</div>
              <RiskBadge risk={event.risk} />
            </div>
            <div className="mt-1 text-[14px] leading-snug break-words">{event.summary}</div>
            {event.purpose && (
              <div className="mt-1 text-[12.5px] text-muted italic break-words line-clamp-2">{t("For: {purpose}", { purpose: event.purpose })}</div>
            )}
            <div className="mt-1 flex items-center gap-1.5 text-[12px] text-muted">
              {toolIcon(event.tool, 13)} <span>{event.tool}</span>
              {(event.target || event.egress_target) && (
                <>
                  <span>·</span>
                  <Globe size={12} /> <span className="truncate">{event.target || event.egress_target}</span>
                </>
              )}
            </div>
          </div>
        </div>
        {event.warnings?.length > 0 && (
          <div className="px-4 pb-2 space-y-1">
            {event.warnings.map((w) => (
              <div key={w} className="flex items-start gap-1.5 text-[12.5px] text-rose-600 dark:text-rose-300">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" /> <span>{w}</span>
              </div>
            ))}
          </div>
        )}
        <div className="px-4 pb-2">
          <button
            type="button"
            className="text-[12.5px] text-accent flex items-center gap-1"
            onClick={() => setShowArgs((s) => !s)}
          >
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
          <div className="px-3 pb-3 pt-1 flex flex-col gap-2">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onDecide(false, "once")}
                className="flex-1 rounded-2xl border border-border py-2.5 font-semibold text-[15px] active:scale-[0.98] transition"
              >
                {t("Deny")}
              </button>
              <button
                type="button"
                onClick={() => onDecide(true, "once")}
                className="flex-1 rounded-2xl bg-accent text-accent-fg py-2.5 font-semibold text-[15px] active:scale-[0.98] transition"
              >
                {t("Allow once")}
              </button>
            </div>
            {standing.length > 0 ? (
              <>
                <button type="button" className="text-[12.5px] text-muted self-center" onClick={() => setMore((m) => !m)}>
                  {more ? t("Fewer options") : t("Allow {subject} for longer…", { subject: grantSubject(event.tool, event.target) })}
                </button>
                {more && (
                  <div className="grid grid-cols-2 gap-2">
                    {standing.map((scope) => (
                      <button
                        key={scope}
                        type="button"
                        onClick={() => onDecide(true, scope)}
                        className="rounded-2xl bg-surface-2 px-3 py-2 text-[13px] font-medium text-left leading-snug"
                      >
                        {scopeLabel(scope, event.tool, event.target)}
                      </button>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div className="text-[12px] text-muted self-center">{t("This kind of action is approved one at a time.")}</div>
            )}
          </div>
        ) : (
          <div
            className={cx(
              "px-4 py-2.5 text-[13px] font-medium flex items-center gap-1.5 border-t border-border",
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
    <div className="rise flex justify-start pl-11 pr-8">
      <div className="max-w-full rounded-3xl rounded-tl-lg border border-accent/40 bg-surface px-4 py-3 shadow-sm">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-accent uppercase tracking-wide">
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
    <div className="rise flex justify-start pl-11 pr-8">
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
  const what = kind === "html" ? t("Page") : kind === "image" ? t("Image") : kind === "data" ? t("Data") : kind === "code" ? t("Code") : t("Document");
  const label = event.action === "update" ? `${what} · ${t("updated")}` : what;
  return (
    <div className="rise flex justify-start pl-11 pr-8">
      <button
        type="button"
        onClick={() => onOpen(event.path)}
        className="flex items-center gap-3 rounded-3xl rounded-tl-lg border border-border bg-surface px-4 py-3 shadow-sm hover:bg-surface-2 transition max-w-full text-left"
      >
        <div className="rounded-2xl bg-accent/12 text-accent p-2.5">
          {kind === "code" ? <Code2 size={20} /> : kind === "html" ? <Globe size={20} /> : kind === "image" ? <ImageIcon size={20} /> : <FileText size={20} />}
        </div>
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wide text-muted font-semibold">{label}</div>
          <div className="font-medium text-[14.5px] truncate">{event.name}</div>
          <div className="text-[12px] text-muted truncate">{event.path}</div>
        </div>
        <ChevronRight size={16} className="text-muted ml-1 shrink-0" />
      </button>
    </div>
  );
}
