import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Which of the files the agent made does this text name?
 *
 * A reply says "saved it to `kyoto-notes/packing-list.html`" or just "`packing-list.html`":
 * accept the workspace path, a path suffix, or the bare file name (when it is unambiguous).
 */
export function matchFile(text: string, files: readonly string[]): string | null {
  const t = text.trim().replace(/^\.?\//, "");
  if (!t || files.length === 0) return null;
  if (files.includes(t)) return t;
  const suffix = files.filter((f) => f.endsWith(`/${t}`));
  return suffix.length === 1 ? suffix[0] : null;
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&");

/**
 * Put backticks around bare mentions of the thread's files, so "saved as packing-list.html"
 * gets the same tappable chip as "`packing-list.html`". Text already in code, fenced blocks
 * or links is left alone; a bare name is marked only when it names exactly one file.
 */
export function markFiles(text: string, files: readonly string[]): string {
  if (!text || files.length === 0) return text;
  const names = new Set<string>(files);
  for (const f of files) {
    const base = f.slice(f.lastIndexOf("/") + 1);
    if (base.includes(".") && matchFile(base, files) === f) names.add(base);
  }
  // longest first, so a path wins over the file name inside it
  const alts = [...names].sort((a, b) => b.length - a.length).map(escapeRe);
  const mention = new RegExp(`(?<![\\w./\\\\-])(${alts.join("|")})(?![\\w/-]|\\.\\w)`, "g");
  const untouched = /(```[\s\S]*?```|`[^`\n]*`|\[[^\]]*\]\([^)]*\)|<[^>]*>)/;
  return text
    .split(untouched)
    .map((part, i) => (i % 2 === 1 ? part : part.replace(mention, "`$1`")))
    .join("");
}

function inlineCode(props: ComponentPropsWithoutRef<"code">): boolean {
  // react-markdown gives fenced blocks a `language-*` class and a newline in the text
  const text = typeof props.children === "string" ? props.children : "";
  return !String(props.className ?? "").includes("language-") && !text.includes("\n");
}

export function Markdown({
  text,
  files = [],
  onOpenFile,
}: {
  text: string;
  /** workspace paths of files this reply may refer to (the thread's artifacts) */
  files?: readonly string[];
  onOpenFile?: (path: string) => void;
}) {
  // which of the thread's files does this text name, if we can open it at all
  const fileFor = (text: string | undefined): string | null =>
    onOpenFile && text && files.length > 0 ? matchFile(text, files) : null;
  const open = (path: string) => onOpenFile?.(path);
  const source = onOpenFile && files.length > 0 ? markFiles(text, files) : text;
  return (
    <div className="md text-[15px] leading-[1.5] break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children, ...props }) => {
            const path = href && !/^[a-z]+:/i.test(href) ? fileFor(decodeURIComponent(href)) : null;
            if (path) {
              return (
                <button type="button" className="md-file" onClick={() => open(path)}>
                  {children}
                </button>
              );
            }
            return (
              <a href={href} {...props} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            );
          },
          code: ({ children, ...props }) => {
            const path = inlineCode({ children, ...props }) && typeof children === "string" ? fileFor(children) : null;
            if (path) {
              return (
                <button type="button" className="md-file" onClick={() => open(path)} title={path}>
                  {children}
                </button>
              );
            }
            return <code {...props}>{children}</code>;
          },
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
