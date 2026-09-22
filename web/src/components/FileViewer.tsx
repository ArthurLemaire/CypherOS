import { CalendarDays, CalendarPlus, Download, ExternalLink, Loader2, MapPin, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, fileUrl } from "../api";
import { intlLocale, t, useT } from "../i18n";
import { fileKind } from "../util";
import { Markdown } from "./Markdown";

/**
 * In-app viewer for what the agent made: pages, images, documents, code, data.
 *
 * HTML is rendered from fetched text in a sandboxed iframe without `allow-same-origin`,
 * so an artifact's script runs in an opaque origin: it cannot read the access token or
 * call the API. Images and PDFs load by URL (the server does not run them).
 */
export function FileViewer({ path, onClose }: { path: string | null; onClose: () => void }) {
  const t = useT();
  useEffect(() => {
    if (!path) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [path, onClose]);

  if (!path) return null;
  const name = path.split("/").pop() ?? path;
  const kind = fileKind(name);
  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-bg">
      <header className="safe-top shrink-0 flex items-center gap-2 border-b border-border bg-surface/90 px-3 py-2 backdrop-blur">
        <button type="button" onClick={onClose} aria-label={t("Close")} className="p-2 rounded-full text-muted hover:bg-surface-2">
          <X size={20} />
        </button>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-[15px] truncate">{name}</div>
          <div className="text-[12px] text-muted truncate">{path}</div>
        </div>
        {kind !== "html" && (
          <a
            href={fileUrl(path)}
            target="_blank"
            rel="noreferrer noopener"
            aria-label={t("Open in a new tab")}
            className="p-2 rounded-full text-muted hover:bg-surface-2"
          >
            <ExternalLink size={19} />
          </a>
        )}
        <a href={fileUrl(path, true)} aria-label={t("Download")} className="p-2 rounded-full text-muted hover:bg-surface-2">
          <Download size={19} />
        </a>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">
        <Body path={path} kind={kind} />
      </div>
    </div>
  );
}

function Body({ path, kind }: { path: string; kind: ReturnType<typeof fileKind> }) {
  const t = useT();
  if (kind === "image") {
    return (
      <div className="flex h-full items-center justify-center p-3">
        <img src={fileUrl(path)} alt={path} className="max-h-full max-w-full rounded-2xl object-contain" />
      </div>
    );
  }
  if (kind === "pdf") {
    return <iframe title={path} src={fileUrl(path)} className="h-full w-full bg-white" />;
  }
  if (kind === "html") return <HtmlBody path={path} />;
  if (kind === "event") return <EventBody path={path} />;
  if (kind === "text" || kind === "code" || kind === "data") return <TextBody path={path} kind={kind} />;
  return (
    <div className="p-8 text-center text-muted text-[14px]">
      {t("No preview for this file type.")}{" "}
      <a href={fileUrl(path, true)} className="text-accent font-medium">
        {t("Download it")}
      </a>
    </div>
  );
}

function useFileText(path: string): { text: string | null; error: string | null } {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setText(null);
    setError(null);
    api.fileText(path)
      .then((t) => alive && setText(t))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [path]);
  return { text, error };
}

function HtmlBody({ path }: { path: string }) {
  const { text, error } = useFileText(path);
  if (error) return <Failed error={error} />;
  if (text === null) return <Loading />;
  return (
    <iframe
      title={path}
      srcDoc={text}
      sandbox="allow-scripts allow-popups allow-forms allow-modals"
      referrerPolicy="no-referrer"
      className="h-full w-full bg-white"
    />
  );
}

/** An .ics the agent drafted: the event as a card, and the file to add it with a tap. */
function EventBody({ path }: { path: string }) {
  const t = useT();
  const { text, error } = useFileText(path);
  if (error) return <Failed error={error} />;
  if (text === null) return <Loading />;
  const events = parseIcs(text);
  return (
    <div className="mx-auto max-w-[560px] px-5 py-6 space-y-4">
      {events.length === 0 && <div className="text-center text-muted text-[14px]">{t("No event in this file.")}</div>}
      {events.map((ev, i) => (
        <div key={i} className="rounded-3xl border border-border/70 bg-surface shadow-sm p-5">
          <div className="flex items-start gap-3">
            <div className="rounded-2xl bg-accent/12 text-accent p-2.5">
              <CalendarDays size={22} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[18px] font-semibold leading-snug">{ev.summary || t("Untitled event")}</div>
              <div className="mt-1 text-[14px] text-muted">{eventWhen(ev)}</div>
              {ev.location && (
                <div className="mt-1 flex items-center gap-1 text-[14px] text-muted">
                  <MapPin size={14} /> {ev.location}
                </div>
              )}
            </div>
          </div>
          {ev.description && <div className="mt-4 whitespace-pre-wrap text-[14px] leading-relaxed">{ev.description}</div>}
        </div>
      ))}
      <a href={fileUrl(path, true)} download className="flex items-center justify-center gap-2 rounded-2xl bg-accent text-accent-fg px-4 py-3 text-[15px] font-medium">
        <CalendarPlus size={18} /> {t("Add to calendar")}
      </a>
      <p className="text-center text-[12.5px] text-muted">{t("Opens in your calendar app, which asks before it saves anything.")}</p>
    </div>
  );
}

interface IcsEvent {
  summary: string;
  location: string;
  description: string;
  start: Date | null;
  end: Date | null;
  allDay: boolean;
}

/** The VEVENTs of an iCalendar text — enough of RFC 5545 to show what the agent drafted. */
export function parseIcs(text: string): IcsEvent[] {
  const lines = text
    .replace(/\r\n/g, "\n")
    .replace(/\n[ \t]/g, "")
    .split("\n");
  const events: IcsEvent[] = [];
  let cur: IcsEvent | null = null;
  const unescape = (v: string) => v.replace(/\\n/gi, "\n").replace(/\\([,;\\])/g, "$1");
  const when = (v: string, params: string): { at: Date | null; allDay: boolean } => {
    if (/VALUE=DATE(?![-])/i.test(params) || /^\d{8}$/.test(v)) {
      const m = /^(\d{4})(\d{2})(\d{2})/.exec(v);
      return { at: m ? new Date(+m[1], +m[2] - 1, +m[3]) : null, allDay: true };
    }
    const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z?)$/.exec(v);
    if (!m) return { at: null, allDay: false };
    const parts = [+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] ?? 0)] as const;
    // Z is UTC; a TZID or a floating time is shown as local time (the agent writes UTC)
    return { at: m[7] ? new Date(Date.UTC(...parts)) : new Date(...parts), allDay: false };
  };
  for (const line of lines) {
    if (line === "BEGIN:VEVENT") cur = { summary: "", location: "", description: "", start: null, end: null, allDay: false };
    else if (line === "END:VEVENT" && cur) {
      events.push(cur);
      cur = null;
    } else if (cur) {
      const idx = line.indexOf(":");
      if (idx < 0) continue;
      const [key, ...params] = line.slice(0, idx).split(";");
      const value = line.slice(idx + 1);
      const p = params.join(";");
      if (key === "SUMMARY") cur.summary = unescape(value);
      else if (key === "LOCATION") cur.location = unescape(value);
      else if (key === "DESCRIPTION") cur.description = unescape(value);
      else if (key === "DTSTART") {
        const w = when(value, p);
        cur.start = w.at;
        cur.allDay = w.allDay;
      } else if (key === "DTEND") cur.end = when(value, p).at;
    }
  }
  return events;
}

function eventWhen(ev: IcsEvent): string {
  if (!ev.start) return "";
  const locale = intlLocale();
  const day = (d: Date) => d.toLocaleDateString(locale, { weekday: "short", year: "numeric", month: "short", day: "numeric" });
  const time = (d: Date) => d.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
  if (ev.allDay) {
    // DTEND of an all-day event is the day after it ends
    const last = ev.end ? new Date(ev.end.getTime() - 86400000) : ev.start;
    return last > ev.start ? `${day(ev.start)} – ${day(last)}` : `${day(ev.start)} · ${t("all day")}`;
  }
  if (!ev.end) return `${day(ev.start)} ${time(ev.start)}`;
  const sameDay = ev.start.toDateString() === ev.end.toDateString();
  return sameDay ? `${day(ev.start)} ${time(ev.start)}–${time(ev.end)}` : `${day(ev.start)} ${time(ev.start)} – ${day(ev.end)} ${time(ev.end)}`;
}

function TextBody({ path, kind }: { path: string; kind: "text" | "code" | "data" }) {
  const { text, error } = useFileText(path);
  if (error) return <Failed error={error} />;
  if (text === null) return <Loading />;
  if (kind === "text" && /\.md$/i.test(path)) {
    return (
      <div className="mx-auto max-w-[720px] px-5 py-4">
        <Markdown text={text} />
      </div>
    );
  }
  if (kind === "data" && /\.csv$/i.test(path)) return <CsvTable text={text} />;
  return (
    <pre className="whitespace-pre-wrap break-words px-4 py-3 font-mono text-[12.5px] leading-relaxed">{text}</pre>
  );
}

function CsvTable({ text }: { text: string }) {
  const t = useT();
  const rows = text
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .slice(0, 500)
    .map((l) => l.split(","));
  if (!rows.length) return <div className="p-6 text-muted text-center">{t("Empty file.")}</div>;
  const [head, ...body] = rows;
  return (
    <div className="overflow-auto p-3">
      <table className="min-w-full text-[13px] border-separate border-spacing-0">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i} className="sticky top-0 bg-surface-2 text-left font-semibold px-3 py-2 border-b border-border whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((r, i) => (
            <tr key={i} className="odd:bg-surface">
              {r.map((c, j) => (
                <td key={j} className="px-3 py-1.5 border-b border-border/60 whitespace-nowrap">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Loading() {
  return (
    <div className="flex h-full items-center justify-center text-muted">
      <Loader2 className="animate-spin" size={22} />
    </div>
  );
}

function Failed({ error }: { error: string }) {
  const t = useT();
  return <div className="p-8 text-center text-rose-600 dark:text-rose-300 text-[14px]">{t("Could not load the file: {error}", { error })}</div>;
}
