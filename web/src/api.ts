import type {
  ActivityData,
  CalendarData,
  ConnectionsData,
  FeedItem,
  FileInfo,
  Goal,
  IdeasData,
  MemoryChange,
  MemoryItem,
  PushInfo,
  Reminder,
  ReminderKind,
  Trigger,
  TriggerKind,
  TriggersData,
  SettingsView,
  StateSnapshot,
  TestResult,
  ThreadMeta,
  TidyReport,
  TimelineEvent,
  UpcomingData,
  WsMessage,
} from "./types";

const TOKEN_KEY = "openmuse_token";

export class AuthError extends Error {
  constructor() {
    super("unauthorized");
  }
}

/** Read the token from `?token=` (first visit via QR code) or localStorage. */
export function getToken(): string {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    localStorage.setItem(TOKEN_KEY, fromUrl);
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function fileUrl(path: string, download = false): string {
  const token = getToken();
  const params = new URLSearchParams();
  if (token) params.set("token", token);
  if (download) params.set("download", "1");
  const q = params.toString();
  return `/api/files/${path.split("/").map(encodeURIComponent).join("/")}${q ? `?${q}` : ""}`;
}

/** A browser frame (JPEG) kept in memory on the server for the current run. */
export function frameUrl(thread: string, frame: string): string {
  const token = getToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `/api/browser/${encodeURIComponent(thread)}/frames/${encodeURIComponent(frame)}.jpg${q}`;
}

export interface BrowserControl {
  action: "click" | "type" | "key" | "scroll" | "navigate" | "look";
  x?: number;
  y?: number;
  text?: string;
  key?: string;
  dy?: number;
  url?: string;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (init.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) throw new AuthError();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ?? JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  state: () => request<StateSnapshot>("/api/state"),
  health: () => request<{ ok: boolean; version: string; auth: boolean }>("/api/health"),
  threads: () => request<ThreadMeta[]>("/api/threads"),
  createThread: (title: string) => request<ThreadMeta>("/api/threads", json({ title })),
  renameThread: (id: string, title: string) =>
    request<ThreadMeta>(`/api/threads/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteThread: (id: string) => request<{ ok: boolean }>(`/api/threads/${id}`, { method: "DELETE" }),
  clearThread: (id: string) => request<{ ok: boolean }>(`/api/threads/${id}/clear`, { method: "POST" }),
  events: (thread: string, limit = 200, before?: string) =>
    request<{ thread: ThreadMeta; events: TimelineEvent[]; has_more: boolean }>(
      `/api/threads/${thread}/events?limit=${limit}${before ? `&before=${before}` : ""}`,
    ),
  send: (thread: string, text: string) =>
    request<{ event: TimelineEvent; thread: ThreadMeta }>(`/api/threads/${thread}/send`, json({ text })),
  decide: (id: string, approved: boolean, scope = "once", reason = "") =>
    request<{ ok: boolean }>(`/api/approvals/${id}`, json({ approved, scope, reason })),
  resetApprovals: () => request<{ ok: boolean }>("/api/approvals", { method: "DELETE" }),
  revokeGrant: (key: string) =>
    request<{ ok: boolean }>(`/api/approvals/grants/${encodeURIComponent(key)}`, { method: "DELETE" }),
  goals: () => request<Goal[]>("/api/goals"),
  createGoal: (body: { title: string; description?: string; steps?: string[]; category?: string; due?: string; check_in?: string }) =>
    request<Goal>("/api/goals", json(body)),
  patchGoal: (id: string, patch: Record<string, unknown>) =>
    request<Goal>(`/api/goals/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  addStep: (id: string, title: string) => request<Goal>(`/api/goals/${id}/steps`, json({ title })),
  advanceGoal: (id: string) => request<Goal>(`/api/goals/${id}/advance`, { method: "POST" }),
  checkInGoal: (id: string) => request<Goal>(`/api/goals/${id}/check-in`, { method: "POST" }),
  acceptProposal: (id: string) => request<Goal>(`/api/goals/${id}/proposal/accept`, { method: "POST" }),
  dismissProposal: (id: string) => request<Goal>(`/api/goals/${id}/proposal`, { method: "DELETE" }),
  deleteGoal: (id: string) => request<{ ok: boolean }>(`/api/goals/${id}`, { method: "DELETE" }),
  memory: () => request<MemoryItem[]>("/api/memory"),
  addMemory: (content: string, category: string) =>
    request<MemoryItem>("/api/memory", json({ content, category })),
  forgetMemory: (id: string) => request<{ ok: boolean }>(`/api/memory/${id}`, { method: "DELETE" }),
  tidyMemory: () => request<TidyReport>("/api/memory/tidy", { method: "POST" }),
  memoryChanges: (limit = 30) => request<MemoryChange[]>(`/api/memory/changes?limit=${limit}`),
  restoreMemoryChange: (id: string) =>
    request<MemoryChange>(`/api/memory/changes/${id}/restore`, { method: "POST" }),
  ideas: (refresh = false) => request<IdeasData>(`/api/ideas${refresh ? "?refresh=1" : ""}`),
  activity: (n = 150) => request<ActivityData>(`/api/activity?n=${n}`),
  feed: (limit = 60) => request<FeedItem[]>(`/api/feed?limit=${limit}`),
  upcoming: () => request<UpcomingData>("/api/upcoming"),
  reminders: (all = false) => request<Reminder[]>(`/api/reminders${all ? "?all=1" : ""}`),
  createReminder: (body: { text: string; kind?: ReminderKind; at?: string; repeat?: string; thread?: string }) =>
    request<Reminder>("/api/reminders", { method: "POST", body: JSON.stringify(body) }),
  fireReminder: (id: string) => request<Reminder>(`/api/reminders/${id}/fire`, { method: "POST" }),
  cancelReminder: (id: string) => request<Reminder>(`/api/reminders/${id}`, { method: "DELETE" }),
  triggers: () => request<TriggersData>("/api/triggers"),
  createTrigger: (body: { kind: TriggerKind; text: string; match?: string; lead_minutes?: number; thread?: string }) =>
    request<Trigger>("/api/triggers", { method: "POST", body: JSON.stringify(body) }),
  fireTrigger: (id: string) => request<Trigger>(`/api/triggers/${id}/fire`, { method: "POST" }),
  cancelTrigger: (id: string) => request<Trigger>(`/api/triggers/${id}`, { method: "DELETE" }),
  files: (limit = 300) => request<FileInfo[]>(`/api/files?limit=${limit}`),
  /** Raw contents of a workspace file, fetched with the token in a header (never in a URL). */
  fileText: async (path: string): Promise<string> => {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`/api/files/${path.split("/").map(encodeURIComponent).join("/")}`, { headers });
    if (res.status === 401) throw new AuthError();
    if (!res.ok) throw new Error(res.statusText);
    return res.text();
  },
  settings: () => request<SettingsView>("/api/settings"),
  updateSettings: (body: Record<string, unknown>) =>
    request<SettingsView>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  // connections: secrets go into the vault on the server; only names ever come back
  connections: () => request<ConnectionsData>("/api/connections"),
  setLLM: (body: Record<string, unknown>) =>
    request<ConnectionsData["llm"]>("/api/connections/llm", { method: "PUT", body: JSON.stringify(body) }),
  testLLM: () => request<TestResult>("/api/connections/llm/test", { method: "POST" }),
  setEmail: (body: Record<string, unknown>) =>
    request<ConnectionsData["email"]>("/api/connections/email", { method: "PUT", body: JSON.stringify(body) }),
  disconnectEmail: () => request<ConnectionsData["email"]>("/api/connections/email", { method: "DELETE" }),
  testEmail: () => request<TestResult>("/api/connections/email/test", { method: "POST" }),
  calendar: () => request<CalendarData>("/api/calendar"),
  setCalendar: (body: Record<string, unknown>) =>
    request<ConnectionsData["calendar"]>("/api/connections/calendar", { method: "PUT", body: JSON.stringify(body) }),
  addCalendarFeed: (name: string, url: string) =>
    request<ConnectionsData["calendar"] & { error?: string }>("/api/connections/calendar/feeds", json({ name, url })),
  removeCalendarFeed: (name: string) =>
    request<ConnectionsData["calendar"]>(`/api/connections/calendar/feeds/${encodeURIComponent(name)}`, { method: "DELETE" }),
  testCalendar: () => request<TestResult>("/api/connections/calendar/test", { method: "POST" }),
  setBrowser: (enabled: boolean) =>
    request<ConnectionsData["browser"]>("/api/connections/browser", { method: "PUT", body: JSON.stringify({ enabled }) }),
  addMCP: (body: Record<string, unknown>) => request<ConnectionsData>("/api/connections/mcp", json(body)),
  removeMCP: (name: string) =>
    request<{ ok: boolean }>(`/api/connections/mcp/${encodeURIComponent(name)}`, { method: "DELETE" }),
  vaultSet: (name: string, value: string) =>
    request<string[]>(`/api/vault/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ value }) }),
  vaultDelete: (name: string) => request<{ ok: boolean }>(`/api/vault/${encodeURIComponent(name)}`, { method: "DELETE" }),
  onboarded: (done = true) => request<{ onboarded: boolean }>("/api/onboarded", json({ done })),
  // browser view
  browserControl: (thread: string, body: BrowserControl) =>
    request<{ url: string; title: string }>(`/api/browser/${encodeURIComponent(thread)}/control`, json(body)),
  // push
  push: () => request<PushInfo>("/api/push"),
  pushSubscribe: (subscription: Record<string, unknown>) => request<PushInfo>("/api/push/subscribe", json({ subscription })),
  pushUnsubscribe: (endpoint: string) => request<PushInfo>("/api/push/unsubscribe", json({ endpoint })),
  pushTest: () => request<TestResult & { sent?: number }>("/api/push/test", { method: "POST" }),
};

/** WebSocket with automatic reconnect. Returns a disposer. */
export function connectWs(handlers: {
  onMessage: (msg: WsMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onAuthError?: () => void;
}): { send: (msg: unknown) => boolean; close: () => void } {
  let ws: WebSocket | null = null;
  let closed = false;
  let attempt = 0;
  let timer: number | undefined;

  const open = () => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const token = getToken();
    const url = `${proto}://${window.location.host}/ws${token ? `?token=${encodeURIComponent(token)}` : ""}`;
    ws = new WebSocket(url);
    ws.onopen = () => {
      attempt = 0;
      handlers.onOpen?.();
    };
    ws.onmessage = (ev) => {
      try {
        handlers.onMessage(JSON.parse(ev.data) as WsMessage);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = (ev) => {
      handlers.onClose?.();
      if (ev.code === 4401) {
        handlers.onAuthError?.();
        return;
      }
      if (closed) return;
      const delay = Math.min(15000, 500 * 2 ** attempt++);
      timer = window.setTimeout(open, delay);
    };
    ws.onerror = () => ws?.close();
  };
  open();

  return {
    send: (msg) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg));
        return true;
      }
      return false;
    },
    close: () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      ws?.close();
    },
  };
}
