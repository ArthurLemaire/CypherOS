import { Code2, FileImage, FileSpreadsheet, FileText, Globe, Loader2, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import type { FileInfo } from "../types";
import { cx, fileKind, relativeTime } from "../util";

type Kind = ReturnType<typeof fileKind>;

const GROUPS: Array<{ id: Kind | "all"; label: string }> = [
  { id: "all", label: "All" },
  { id: "html", label: "Pages" },
  { id: "text", label: "Documents" },
  { id: "image", label: "Images" },
  { id: "data", label: "Data" },
  { id: "code", label: "Code" },
];

/**
 * Everything your Muse has made — pages, documents, trackers, images — in one place,
 * newest first, viewable in the app. This is the agent's workspace, so files you drop
 * there yourself show up too.
 */
export function LibraryScreen() {
  const { state, openFile, toast } = useStore();
  const [files, setFiles] = useState<FileInfo[] | null>(null);
  const [group, setGroup] = useState<Kind | "all">("all");
  const [query, setQuery] = useState("");
  const name = state.profile?.name ?? "Muse";

  // Reload whenever the agent finishes a step (the timeline moves) or the tab is opened.
  const version = Object.values(state.events).reduce((n, list) => n + list.length, 0);
  useEffect(() => {
    let alive = true;
    api.files(500)
      .then((d) => alive && setFiles(d))
      .catch((e: Error) => toast(e.message));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, state.feedVersion]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (files ?? []).filter((f) => {
      const kind = fileKind(f.name);
      if (group !== "all" && kind !== group && !(group === "text" && kind === "pdf")) return false;
      return !q || f.path.toLowerCase().includes(q);
    });
  }, [files, group, query]);

  return (
    <div className="flex h-full flex-col">
      <header className="safe-top shrink-0 px-5 pt-4 pb-2">
        <h1 className="text-[24px] font-bold tracking-tight">Library</h1>
        <p className="text-[13px] text-muted">Pages, documents and files {name} made for you. Tap one to open it here.</p>
        <label className="mt-3 flex items-center gap-2 rounded-2xl bg-surface-2 px-3 py-2">
          <Search size={16} className="text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search files"
            className="flex-1 bg-transparent text-[14.5px] outline-none"
          />
        </label>
        <div className="no-scrollbar mt-2.5 -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
          {GROUPS.map((g) => (
            <button
              key={g.id}
              type="button"
              onClick={() => setGroup(g.id)}
              className={cx(
                "shrink-0 rounded-full px-3 py-1 text-[13px] border transition",
                group === g.id ? "bg-accent text-accent-fg border-accent" : "bg-surface-2 border-transparent text-fg",
              )}
            >
              {g.label}
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 pb-6">
        {files === null && (
          <div className="py-10 flex justify-center text-muted">
            <Loader2 className="animate-spin" size={20} />
          </div>
        )}
        {files !== null && shown.length === 0 && (
          <div className="py-10 text-center text-muted text-[14px] px-6">
            {files.length === 0
              ? `Nothing here yet. Ask ${name} for a plan, a comparison page or a tracker and it lands in the Library.`
              : "No files match."}
          </div>
        )}
        <ul className="space-y-2">
          {shown.map((f) => (
            <li key={f.path}>
              <FileRow file={f} onOpen={() => openFile(f.path)} />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function FileRow({ file, onOpen }: { file: FileInfo; onOpen: () => void }) {
  const kind = fileKind(file.name);
  const icon =
    kind === "html" ? <Globe size={19} /> : kind === "image" ? <FileImage size={19} /> : kind === "data" ? <FileSpreadsheet size={19} /> : kind === "code" ? <Code2 size={19} /> : <FileText size={19} />;
  const dir = file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : "";
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full text-left rounded-3xl border border-border/70 bg-surface shadow-sm px-4 py-3 flex items-center gap-3 active:scale-[0.99] transition"
    >
      <div className="rounded-2xl bg-accent/12 text-accent p-2.5">{icon}</div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-[14.5px] truncate">{file.name}</div>
        <div className="text-[12px] text-muted truncate">
          {relativeTime(file.modified)} · {formatSize(file.size)}
          {dir && ` · ${dir}`}
        </div>
      </div>
    </button>
  );
}

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
