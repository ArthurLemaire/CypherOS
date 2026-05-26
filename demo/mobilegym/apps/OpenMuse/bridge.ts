import { NotificationService } from '@/os/NotificationService';
import { manifest } from './manifest';

/**
 * The notification bridge.
 *
 * OpenMuse pushes real Web Push notifications to real phones. Inside the simulator there is
 * no push service, so this module keeps one WebSocket to the OpenMuse server open for the
 * whole simulator session and turns the events a phone would be notified about into
 * simulated Android notifications: approvals waiting for you, questions the agent asked,
 * and results of background work. Tapping one opens the OpenMuse app on that chat.
 */

type LinkState = 'off' | 'connecting' | 'online' | 'unauthorized' | 'unreachable';

interface Settings {
  serverUrl: string;
  token: string;
  notify: boolean;
}

interface Hooks {
  get: () => Settings;
  setLink: (link: LinkState) => void;
}

/** The subset of the server's timeline events we care about. */
interface TimelineEvent {
  id: string;
  type: string;
  thread: string;
  status?: string;
  summary?: string;
  purpose?: string;
  text?: string;
  source?: string;
  about?: string;
  quiet?: boolean;
  final?: boolean;
  tool?: string;
}

type WsMessage =
  | { kind: 'hello'; state: { pending_approvals?: TimelineEvent[] } }
  | { kind: 'event' | 'update'; event: TimelineEvent }
  | { kind: string };

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30000;

function threadRoute(thread: string): string {
  return `/?thread=${encodeURIComponent(thread)}`;
}

/** Same titles the server uses for its Web Push notifications. */
function backgroundTitle(about: string): string {
  if (about.startsWith('Check-in: ')) return 'OpenMuse · check-in';
  return about.replace('Working on your goal: ', '') || 'OpenMuse';
}

function firstLine(text: string, max = 140): string {
  const line = text.replace(/\s+/g, ' ').trim();
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

class MuseBridge {
  private hooks: Hooks | null = null;
  private ws: WebSocket | null = null;
  private key = '';
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private backoff = RECONNECT_MIN_MS;
  /** timeline event id → notification id, so a resolved card takes its notification down */
  private shown = new Map<string, string>();

  attach(hooks: Hooks): void {
    this.hooks = hooks;
  }

  /** (Re)connect if the settings changed; disconnect if they were cleared. Idempotent. */
  sync(): void {
    if (!this.hooks) return;
    const { serverUrl, token, notify } = this.hooks.get();
    const key = serverUrl && token && notify ? `${serverUrl}|${token}` : '';
    if (key === this.key && (this.ws || this.reconnectTimer)) return;
    this.key = key;
    this.teardown();
    if (!key) {
      this.hooks.setLink('off');
      return;
    }
    this.backoff = RECONNECT_MIN_MS;
    this.open();
  }

  private teardown(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      const ws = this.ws;
      this.ws = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      try {
        ws.close();
      } catch {
        // already closed
      }
    }
  }

  private open(): void {
    if (!this.hooks) return;
    const { serverUrl, token } = this.hooks.get();
    let url: URL;
    try {
      url = new URL(serverUrl);
    } catch {
      this.hooks.setLink('unreachable');
      return;
    }
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = '/ws';
    url.search = `?token=${encodeURIComponent(token)}`;

    this.hooks.setLink('connecting');
    const ws = new WebSocket(url.toString());
    this.ws = ws;
    const settingsKey = this.key;

    ws.onopen = () => {
      this.backoff = RECONNECT_MIN_MS;
    };
    ws.onmessage = (ev) => {
      let msg: WsMessage;
      try {
        msg = JSON.parse(String(ev.data)) as WsMessage;
      } catch {
        return;
      }
      this.handle(msg);
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (!this.hooks || this.key !== settingsKey) return;
      if (ev.code === 4401) {
        // the server rejected the token: no point retrying until the settings change
        this.hooks.setLink('unauthorized');
        return;
      }
      this.hooks.setLink('unreachable');
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        if (this.key === settingsKey) this.open();
      }, this.backoff);
      this.backoff = Math.min(this.backoff * 2, RECONNECT_MAX_MS);
    };
    ws.onerror = () => {
      // onclose follows and does the bookkeeping
    };
  }

  private handle(msg: WsMessage): void {
    if (!this.hooks) return;
    if (msg.kind === 'hello') {
      this.hooks.setLink('online');
      const pending = (msg as { state: { pending_approvals?: TimelineEvent[] } }).state.pending_approvals ?? [];
      for (const ev of pending) this.notifyFor(ev);
      return;
    }
    if (msg.kind === 'event' || msg.kind === 'update') {
      const ev = (msg as { event: TimelineEvent }).event;
      if (ev.type === 'approval' || ev.type === 'question') {
        if (ev.status === 'pending') this.notifyFor(ev);
        else this.retract(ev.id);
        return;
      }
      if (ev.type === 'assistant') {
        // Background work reporting in. Only the run's last word is flagged `final` (the
        // step-by-step narration before it is not), and the agent already decided it was
        // worth surfacing (`quiet` otherwise). The flag can arrive as an update when the
        // bubble was on screen before the run ended, hence the dedupe.
        if (ev.source === 'background' && ev.final && !ev.quiet && ev.text && !this.shown.has(ev.id)) {
          const item = NotificationService.push({
            appId: manifest.id,
            title: backgroundTitle(ev.about ?? ''),
            body: firstLine(ev.text),
            route: threadRoute(ev.thread),
            importance: 'default',
          });
          this.shown.set(ev.id, item.id);
        }
      }
    }
  }

  private notifyFor(ev: TimelineEvent): void {
    if (this.shown.has(ev.id)) return;
    const isApproval = ev.type === 'approval';
    const body = isApproval ? [ev.summary, ev.purpose && `For: ${ev.purpose}`].filter(Boolean).join(' — ') : ev.text ?? '';
    const item = NotificationService.push({
      appId: manifest.id,
      title: isApproval ? 'OpenMuse needs your approval' : 'OpenMuse has a question',
      body: firstLine(body, 200),
      route: threadRoute(ev.thread),
      importance: 'high',
      autoCancel: true,
    });
    this.shown.set(ev.id, item.id);
  }

  private retract(eventId: string): void {
    const id = this.shown.get(eventId);
    if (!id) return;
    this.shown.delete(eventId);
    NotificationService.dismiss(id);
  }
}

export const bridge = new MuseBridge();
