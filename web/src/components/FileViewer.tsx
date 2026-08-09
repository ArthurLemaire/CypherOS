import { Download, ExternalLink, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, fileUrl } from "../api";
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
        <button type="button" onClick={onClose} aria-label="Close" className="p-2 rounded-full text-muted hover:bg-surface-2">
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
            aria-label="Open in a new tab"
            className="p-2 rounded-full text-muted hover:bg-surface-2"
          >
            <ExternalLink size={19} />
          </a>
        )}
        <a href={fileUrl(path, true)} aria-label="Download" className="p-2 rounded-full text-muted hover:bg-surface-2">
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
  if (kind === "text" || kind === "code" || kind === "data") return <TextBody path={path} kind={kind} />;
  return (
    <div className="p-8 text-center text-muted text-[14px]">
      No preview for this file type.{" "}
      <a href={fileUrl(path, true)} className="text-accent font-medium">
        Download it
      </a>
      .
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
  const rows = text
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .slice(0, 500)
    .map((l) => l.split(","));
  if (!rows.length) return <div className="p-6 text-muted text-center">Empty file.</div>;
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
  return <div className="p-8 text-center text-rose-600 dark:text-rose-300 text-[14px]">Could not load the file: {error}</div>;
}
