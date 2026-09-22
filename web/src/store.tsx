import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import { api, AuthError, connectWs, getToken } from "./api";
import type {
  Goal,
  Profile,
  SettingsView,
  StateSnapshot,
  Status,
  ThreadMeta,
  TimelineEvent,
  WsMessage,
} from "./types";

export type Tab = "chat" | "goals" | "ideas" | "memory" | "you";

export interface Stream {
  id: string;
  text: string;
  ended: boolean;
}

export interface AppState {
  connected: boolean;
  loaded: boolean;
  authError: boolean;
  error: string | null;
  version: string;
  profile: Profile | null;
  status: Status;
  threads: ThreadMeta[];
  activeThread: string;
  events: Record<string, TimelineEvent[]>;
  hasMore: Record<string, boolean>;
  streams: Record<string, Stream | undefined>;
  goals: Goal[];
  settings: SettingsView | null;
  goalsVersion: number;
  memoryVersion: number;
  tab: Tab;
  toast: string | null;
}

type Action =
  | { type: "hello"; state: StateSnapshot }
  | { type: "ws"; msg: WsMessage }
  | { type: "connection"; connected: boolean }
  | { type: "authError" }
  | { type: "error"; error: string | null }
  | { type: "events"; thread: string; events: TimelineEvent[]; hasMore: boolean; prepend?: boolean }
  | { type: "activeThread"; thread: string }
  | { type: "goals"; goals: Goal[] }
  | { type: "settings"; settings: SettingsView }
  | { type: "tab"; tab: Tab }
  | { type: "toast"; toast: string | null };

const initial: AppState = {
  connected: false,
  loaded: false,
  authError: false,
  error: null,
  version: "",
  profile: null,
  status: { state: "idle", detail: "", thread: "main" },
  threads: [],
  activeThread: "main",
  events: {},
  hasMore: {},
  streams: {},
  goals: [],
  settings: null,
  goalsVersion: 0,
  memoryVersion: 0,
  tab: "chat",
  toast: null,
};

function upsertEvent(list: TimelineEvent[] | undefined, ev: TimelineEvent): TimelineEvent[] {
  const events = list ?? [];
  const idx = events.findIndex((e) => e.id === ev.id);
  if (idx >= 0) {
    const next = events.slice();
    next[idx] = ev;
    return next;
  }
  return [...events, ev];
}

function upsertThread(list: ThreadMeta[], meta: ThreadMeta): ThreadMeta[] {
  const idx = list.findIndex((t) => t.id === meta.id);
  if (idx >= 0) {
    const next = list.slice();
    next[idx] = meta;
    return next;
  }
  return [...list, meta];
}

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "hello": {
      const s = action.state;
      return {
        ...state,
        loaded: true,
        authError: false,
        version: s.version,
        profile: s.profile,
        status: s.status,
        threads: s.threads,
        goals: s.goals,
        settings: s.settings,
        activeThread: s.threads.some((t) => t.id === state.activeThread) ? state.activeThread : "main",
      };
    }
    case "connection":
      return { ...state, connected: action.connected };
    case "authError":
      return { ...state, authError: true, connected: false };
    case "error":
      return { ...state, error: action.error };
    case "events": {
      const existing = state.events[action.thread] ?? [];
      const merged = action.prepend
        ? [...action.events, ...existing.filter((e) => !action.events.some((n) => n.id === e.id))]
        : action.events;
      return {
        ...state,
        events: { ...state.events, [action.thread]: merged },
        hasMore: { ...state.hasMore, [action.thread]: action.hasMore },
      };
    }
    case "activeThread":
      return { ...state, activeThread: action.thread, tab: "chat" };
    case "goals":
      return { ...state, goals: action.goals };
    case "settings":
      return { ...state, settings: action.settings, profile: action.settings.profile };
    case "tab":
      return { ...state, tab: action.tab };
    case "toast":
      return { ...state, toast: action.toast };
    case "ws":
      return applyWs(state, action.msg);
    default:
      return state;
  }
}

function applyWs(state: AppState, msg: WsMessage): AppState {
  switch (msg.kind) {
    case "hello":
      return reducer(state, { type: "hello", state: msg.state });
    case "event":
    case "update": {
      const ev = msg.event;
      const streams = { ...state.streams };
      const stream = streams[ev.thread];
      if (ev.type === "assistant" && stream && stream.id === ev.id) streams[ev.thread] = undefined;
      const threads = state.threads.map((t) =>
        t.id === ev.thread && msg.kind === "event" ? { ...t, updated_at: ev.ts } : t,
      );
      return {
        ...state,
        streams,
        threads,
        events: { ...state.events, [ev.thread]: upsertEvent(state.events[ev.thread], ev) },
      };
    }
    case "stream_start":
      return {
        ...state,
        streams: { ...state.streams, [msg.thread]: { id: msg.id, text: "", ended: false } },
      };
    case "delta": {
      const current = state.streams[msg.thread];
      const stream: Stream =
        current && current.id === msg.id
          ? { ...current, text: current.text + msg.text }
          : { id: msg.id, text: msg.text, ended: false };
      return { ...state, streams: { ...state.streams, [msg.thread]: stream } };
    }
    case "stream_end": {
      const current = state.streams[msg.thread];
      if (!current || current.id !== msg.id) return state;
      // Keep it until the persisted assistant event replaces it (avoids flicker);
      // an empty stream can go right away.
      if (!current.text.trim()) return { ...state, streams: { ...state.streams, [msg.thread]: undefined } };
      return { ...state, streams: { ...state.streams, [msg.thread]: { ...current, ended: true } } };
    }
    case "status": {
      const st = msg.status;
      const streams = { ...state.streams };
      const s = streams[st.thread];
      if (s?.ended && st.state !== "working") streams[st.thread] = undefined;
      const overall = pickOverall(state.status, st);
      return { ...state, status: overall, streams };
    }
    case "thread":
      return { ...state, threads: upsertThread(state.threads, msg.thread) };
    case "thread_deleted": {
      const events = { ...state.events };
      delete events[msg.thread];
      return {
        ...state,
        events,
        threads: state.threads.filter((t) => t.id !== msg.thread),
        activeThread: state.activeThread === msg.thread ? "main" : state.activeThread,
      };
    }
    case "thread_cleared":
      return { ...state, events: { ...state.events, [msg.thread]: [] } };
    case "goals":
      return { ...state, goalsVersion: state.goalsVersion + 1 };
    case "memory":
      return { ...state, memoryVersion: state.memoryVersion + 1 };
    case "profile":
      return {
        ...state,
        profile: msg.profile,
        settings: state.settings ? { ...state.settings, profile: msg.profile } : state.settings,
      };
    case "settings":
      return { ...state, settings: msg.settings, profile: msg.settings.profile };
    case "error":
      return { ...state, toast: msg.error };
    case "pong":
      return { ...state, status: msg.status };
    default:
      return state;
  }
}

/** Per-thread statuses arrive one at a time; show the busiest one under the avatar. */
const perThread: Record<string, Status> = {};
function pickOverall(prev: Status, incoming: Status): Status {
  perThread[incoming.thread] = incoming;
  const working = Object.values(perThread).filter((s) => s.state !== "idle");
  if (!working.length) return { state: "idle", detail: "", thread: "main" };
  working.sort((a, b) => Number(a.thread !== "main") - Number(b.thread !== "main"));
  return working[0] ?? prev;
}

interface StoreValue {
  state: AppState;
  dispatch: (a: Action) => void;
  send: (thread: string, text: string) => Promise<void>;
  decide: (id: string, approved: boolean, scope?: string) => Promise<void>;
  loadEvents: (thread: string, before?: string) => Promise<void>;
  refreshGoals: () => Promise<void>;
  refreshSettings: () => Promise<void>;
  setTab: (tab: Tab) => void;
  openThread: (thread: string) => void;
  toast: (text: string) => void;
}

const StoreContext = createContext<StoreValue | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);
  const wsRef = useRef<ReturnType<typeof connectWs> | null>(null);

  useEffect(() => {
    getToken();
    const ws = connectWs({
      onMessage: (msg) => dispatch({ type: "ws", msg }),
      onOpen: () => dispatch({ type: "connection", connected: true }),
      onClose: () => dispatch({ type: "connection", connected: false }),
      onAuthError: () => dispatch({ type: "authError" }),
    });
    wsRef.current = ws;
    api.state()
      .then((s) => dispatch({ type: "hello", state: s }))
      .catch((e) => {
        if (e instanceof AuthError) dispatch({ type: "authError" });
        else dispatch({ type: "error", error: String(e.message ?? e) });
      });
    return () => ws.close();
  }, []);

  const loadEvents = useCallback(async (thread: string, before?: string) => {
    try {
      const data = await api.events(thread, 150, before);
      dispatch({ type: "events", thread, events: data.events, hasMore: data.has_more, prepend: !!before });
    } catch (e) {
      if (e instanceof AuthError) dispatch({ type: "authError" });
    }
  }, []);

  useEffect(() => {
    if (state.loaded) void loadEvents(state.activeThread);
  }, [state.loaded, state.activeThread, loadEvents]);

  // Reload the current thread after a reconnect so nothing is missed.
  const wasConnected = useRef(false);
  useEffect(() => {
    if (state.connected && wasConnected.current && state.loaded) void loadEvents(state.activeThread);
    wasConnected.current = state.connected;
  }, [state.connected, state.loaded, state.activeThread, loadEvents]);

  const refreshGoals = useCallback(async () => {
    try {
      dispatch({ type: "goals", goals: await api.goals() });
    } catch {
      /* offline */
    }
  }, []);

  useEffect(() => {
    if (state.loaded) void refreshGoals();
  }, [state.goalsVersion, state.loaded, refreshGoals]);

  const refreshSettings = useCallback(async () => {
    try {
      dispatch({ type: "settings", settings: await api.settings() });
    } catch {
      /* offline */
    }
  }, []);

  useEffect(() => {
    if (!state.toast) return;
    const t = window.setTimeout(() => dispatch({ type: "toast", toast: null }), 3500);
    return () => window.clearTimeout(t);
  }, [state.toast]);

  const value = useMemo<StoreValue>(
    () => ({
      state,
      dispatch,
      send: async (thread, text) => {
        if (!text.trim()) return;
        if (!wsRef.current?.send({ kind: "send", thread, text })) {
          await api.send(thread, text);
        }
      },
      decide: async (id, approved, scope = "once") => {
        if (!wsRef.current?.send({ kind: "approval", id, approved, scope })) {
          await api.decide(id, approved, scope);
        }
      },
      loadEvents,
      refreshGoals,
      refreshSettings,
      setTab: (tab) => dispatch({ type: "tab", tab }),
      openThread: (thread) => dispatch({ type: "activeThread", thread }),
      toast: (text) => dispatch({ type: "toast", toast: text }),
    }),
    [state, loadEvents, refreshGoals, refreshSettings],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): StoreValue {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore outside provider");
  return ctx;
}
