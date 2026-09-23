/**
 * The hosted showcase.
 *
 * On the public site this simulator is served next to a *showcase gateway* (`demo/showcase/`
 * in the nanoMuse repository). Ask it for a session and it starts a private nanoMuse for this
 * visitor — its own container, its own token, GUI operation on — for a limited time and within
 * a model budget. Visitors may also bring their own model key; it goes to the gateway and stays
 * there, the container never sees it.
 *
 * `VITE_NANOMUSE_DEMO` at build time (e.g. `/api/demo`) is what turns this on; a normal
 * MobileGym checkout has it empty and the app asks for a server address instead.
 */

export interface DemoInfo {
  session_ttl_s: number;
  demo_model: string | null;
  byok: boolean;
  byok_hosts: string[];
  quota: { requests: number; tokens: number };
  active_sessions: number;
  max_sessions: number;
}

export interface DemoProvider {
  base_url: string;
  api_key: string;
  model: string;
}

export interface DemoSession {
  id: string;
  serverUrl: string;
  token: string;
  /** Unix seconds. */
  expiresAt: number;
  byok: boolean;
}

export class DemoError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(gateway: string, path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${gateway.replace(/\/+$/, '')}${path}`, init);
  } catch {
    throw new DemoError('unreachable', 'The showcase server cannot be reached.');
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // not JSON
  }
  if (!res.ok) {
    const err = (data ?? {}) as { error?: string; message?: string; detail?: unknown };
    throw new DemoError(err.error ?? String(res.status), err.message ?? `The showcase server answered ${res.status}.`);
  }
  return data as T;
}

export function fetchDemoInfo(gateway: string): Promise<DemoInfo> {
  return call<DemoInfo>(gateway, '/info');
}

export async function startDemoSession(gateway: string, provider?: DemoProvider): Promise<DemoSession> {
  const raw = await call<{ id: string; server_url: string; token: string; expires_at: number; byok: boolean }>(
    gateway,
    '/session',
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(provider ? { provider } : {}),
    },
  );
  return { id: raw.id, serverUrl: raw.server_url, token: raw.token, expiresAt: raw.expires_at, byok: raw.byok };
}

export async function endDemoSession(gateway: string, id: string, token: string): Promise<void> {
  try {
    await call<void>(gateway, `/session/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: { authorization: `Bearer ${token}` },
    });
  } catch {
    // already gone, or unreachable: either way it is over for us
  }
}
