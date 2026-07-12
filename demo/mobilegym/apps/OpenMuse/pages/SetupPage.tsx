import { useState, type FormEvent } from 'react';
import { IcLauncher, IcLink } from '../res/icons';
import { parseServerInput, useOpenMuseStore } from '../state';
import { useOpenMuseGestures } from '../hooks/useOpenMuseGestures';

/**
 * Connect the phone to an OpenMuse server. Paste the link `openmuse serve` prints (it carries
 * the token), or type the address and token separately. The token is checked by opening the
 * server's WebSocket once — the same thing the notification bridge does — so no CORS setup
 * is needed on the server.
 */
export default function SetupPage() {
  const current = useOpenMuseStore((s) => s.serverUrl);
  const currentToken = useOpenMuseStore((s) => s.token);
  const configure = useOpenMuseStore((s) => s.configure);
  const { go } = useOpenMuseGestures();

  const [address, setAddress] = useState(current || 'http://127.0.0.1:8787');
  const [token, setToken] = useState(currentToken);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const parsed = parseServerInput(address);
    const finalToken = (parsed.token || token).trim();
    if (!parsed.serverUrl) {
      setError('Enter the server address.');
      return;
    }
    setBusy(true);
    setError('');
    const result = await probe(parsed.serverUrl, finalToken);
    setBusy(false);
    if (result !== 'ok') {
      setError(
        result === 'unauthorized'
          ? 'The server refused the token. Copy it from the link openmuse serve prints.'
          : `Could not reach ${parsed.serverUrl}. Is openmuse serve running on this machine?`,
      );
      return;
    }
    configure(parsed.serverUrl, finalToken);
    go('muse.open');
  };

  return (
    <div className="h-full w-full flex flex-col bg-app-bg text-app-text pt-10" data-status-bar-foreground="dark">
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        <div className="mt-8 mb-8 flex flex-col items-center text-center">
          <div
            className="w-20 h-20 rounded-[24px] flex items-center justify-center shadow-lg mb-5"
            style={{ background: 'linear-gradient(135deg, #6d28d9 0%, #a855f7 100%)' }}
          >
            <IcLauncher size={40} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Connect your Muse</h1>
          <p className="mt-2 text-[14px] text-app-text-muted leading-snug">
            OpenMuse runs on your computer. Point this phone at it.
          </p>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-medium text-app-text-muted">Server address or link</span>
            <input
              type="url"
              inputMode="url"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="http://127.0.0.1:8787/?token=…"
              className="h-12 rounded-2xl bg-app-surface border border-app-border px-4 text-[15px] outline-none focus:border-app-primary"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-medium text-app-text-muted">Access token (if the link has none)</span>
            <input
              type="text"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="printed by openmuse serve"
              className="h-12 rounded-2xl bg-app-surface border border-app-border px-4 text-[15px] outline-none focus:border-app-primary"
            />
          </label>

          {error && <p className="text-[13px] text-rose-600 leading-snug">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="mt-2 h-12 rounded-2xl bg-app-primary text-app-on-primary font-semibold flex items-center justify-center gap-2 active:scale-[0.98] transition disabled:opacity-60"
          >
            <IcLink size={18} />
            {busy ? 'Connecting…' : 'Connect'}
          </button>
        </form>

        <div className="mt-8 rounded-2xl bg-app-surface border border-app-border p-4 text-[13px] text-app-text-muted leading-relaxed">
          <p className="font-medium text-app-text mb-1">On the computer</p>
          <p>
            <code className="font-mono">openmuse serve</code> prints a link with a one-time token
            and a QR code. Paste the link here. Approvals, questions and background results then
            also show up in this phone&apos;s notification shade.
          </p>
        </div>
      </div>
    </div>
  );
}

/** Open the server's WebSocket once: `hello` means reachable and the token is good. */
function probe(serverUrl: string, token: string): Promise<'ok' | 'unauthorized' | 'unreachable'> {
  return new Promise((resolve) => {
    let url: URL;
    try {
      url = new URL(serverUrl);
    } catch {
      resolve('unreachable');
      return;
    }
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = '/ws';
    url.search = token ? `?token=${encodeURIComponent(token)}` : '';
    let done = false;
    let ws: WebSocket | null = null;
    const finish = (r: 'ok' | 'unauthorized' | 'unreachable') => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      try {
        ws?.close();
      } catch {
        // ignore
      }
      resolve(r);
    };
    const timer = setTimeout(() => finish('unreachable'), 6000);
    try {
      ws = new WebSocket(url.toString());
    } catch {
      finish('unreachable');
      return;
    }
    ws.onmessage = () => finish('ok');
    ws.onclose = (ev) => finish(ev.code === 4401 ? 'unauthorized' : 'unreachable');
    ws.onerror = () => {
      /* onclose follows */
    };
  });
}
