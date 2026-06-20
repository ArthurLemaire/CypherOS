import { intlLocale, t } from "./i18n";

export function timeShort(ts: string | undefined): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString(intlLocale(), { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return time;
  return `${d.toLocaleDateString(intlLocale(), { month: "short", day: "numeric" })} ${time}`;
}

/** A date in the UI language: "Sep 12" / "9月12日", with the year when it is not this one. */
export function dateShort(ts: string | null | undefined, opts: Intl.DateTimeFormatOptions = {}): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  const thisYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(intlLocale(), {
    month: "short",
    day: "numeric",
    ...(thisYear ? {} : { year: "numeric" }),
    ...opts,
  });
}

/** "3 min ago" for the past, "in 2 h" / "in 9 d" for the future. */
export function relativeTime(ts: string | null | undefined): string {
  if (!ts) return "";
  const diff = Date.now() - new Date(ts).getTime();
  if (Number.isNaN(diff)) return "";
  const s = Math.round(Math.abs(diff) / 1000);
  if (s < 45) return diff >= 0 ? t("just now") : t("any moment");
  const m = Math.round(s / 60);
  const h = Math.round(m / 60);
  const d = Math.round(h / 24);
  const span = m < 60 ? t("{n} min", { n: m }) : h < 24 ? t("{n} h", { n: h }) : t("{n} d", { n: d });
  return diff >= 0 ? t("{span} ago", { span }) : t("in {span}", { span });
}

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function truncate(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

export function fileKind(name: string): "text" | "code" | "html" | "image" | "pdf" | "data" | "event" | "other" {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (ext === "ics") return "event";
  if (["md", "txt", "log", "rtf"].includes(ext)) return "text";
  if (["py", "js", "ts", "tsx", "jsx", "sh", "toml", "yaml", "yml", "sql", "rs", "go", "java", "c", "cpp"].includes(ext))
    return "code";
  if (["html", "htm"].includes(ext)) return "html";
  if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) return "image";
  if (ext === "pdf") return "pdf";
  if (["csv", "json", "xlsx", "xls", "parquet"].includes(ext)) return "data";
  return "other";
}
