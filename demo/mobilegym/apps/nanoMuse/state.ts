import { createAppStoreWithActions } from '@/os/createAppStore';
import { NANOMUSE_CONFIG } from './data';
import { bridge } from './bridge';

export type LinkState = 'off' | 'connecting' | 'online' | 'unauthorized' | 'unreachable';

interface NanoMuseState {
  /** Origin of the nanoMuse server, no trailing slash: "http://127.0.0.1:8787". */
  serverUrl: string;
  /** The access token `nanomuse serve` prints (also in the QR code). */
  token: string;
  /** Mirror approvals, questions and background results into the notification shade. */
  notify: boolean;
  /** Live state of the notification bridge's WebSocket. Not persisted. */
  link: LinkState;
}

interface nanoMuseActions {
  configure: (serverUrl: string, token: string) => void;
  disconnect: () => void;
  setNotify: (on: boolean) => void;
  setLink: (link: LinkState) => void;
}

const initialState: NanoMuseState = {
  serverUrl: NANOMUSE_CONFIG.serverUrl,
  token: NANOMUSE_CONFIG.token,
  notify: NANOMUSE_CONFIG.notify,
  link: 'off',
};

/** Normalise what people paste: a bare host, an origin, or the full `?token=` link. */
export function parseServerInput(raw: string): { serverUrl: string; token: string } {
  let text = raw.trim();
  if (!text) return { serverUrl: '', token: '' };
  if (!/^[a-z]+:\/\//i.test(text)) text = `http://${text}`;
  try {
    const url = new URL(text);
    const token = url.searchParams.get('token') ?? '';
    return { serverUrl: `${url.protocol}//${url.host}`, token };
  } catch {
    return { serverUrl: text.replace(/\/+$/, ''), token: '' };
  }
}

export const useNanoMuseStore = createAppStoreWithActions<NanoMuseState, nanoMuseActions>(
  'nanomuse',
  initialState,
  (set) => ({
    configure(serverUrl, token) {
      set({ serverUrl: serverUrl.replace(/\/+$/, ''), token, link: 'connecting' });
    },
    disconnect() {
      set({ serverUrl: '', token: '', link: 'off' });
    },
    setNotify(on) {
      set({ notify: on });
    },
    setLink(link) {
      set({ link });
    },
  }),
  {
    // `link` is runtime state: it always starts as 'off' and the bridge sets it
    partialize: (s) => ({ serverUrl: s.serverUrl, token: s.token, notify: s.notify }),
    afterHydration: () => bridge.sync(),
  },
);

// Keep the bridge in step with the server settings for as long as the simulator runs, whether
// or not the app is open — that is what makes notifications arrive while you are in another app.
bridge.attach({
  get: () => {
    const { serverUrl, token, notify } = useNanoMuseStore.getState();
    return { serverUrl, token, notify };
  },
  setLink: (link) => useNanoMuseStore.getState().setLink(link),
});
// hydration from localStorage is synchronous, so `afterHydration` above may already have run
// before the bridge had its hooks; this call is a no-op when it did connect
bridge.sync();
useNanoMuseStore.subscribe((s, prev) => {
  if (s.serverUrl !== prev.serverUrl || s.token !== prev.token || s.notify !== prev.notify) bridge.sync();
});
