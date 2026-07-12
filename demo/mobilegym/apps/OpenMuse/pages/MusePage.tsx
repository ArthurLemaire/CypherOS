import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { IcOffline, IcWarning } from '../res/icons';
import { useOpenMuseStore } from '../state';
import { useOpenMuseGestures } from '../hooks/useOpenMuseGestures';

/**
 * The OpenMuse web app, full screen. `?thread=` and `?tab=` on this route are forwarded to
 * the web app's own deep links, which is how a tapped notification lands on the right chat.
 */
export default function MusePage() {
  const serverUrl = useOpenMuseStore((s) => s.serverUrl);
  const token = useOpenMuseStore((s) => s.token);
  const link = useOpenMuseStore((s) => s.link);
  const { bindTap, go } = useOpenMuseGestures();
  const location = useLocation();

  // first launch: nothing configured yet → setup
  useEffect(() => {
    if (!serverUrl) go('setup.open', {}, { mode: 'replace' });
  }, [serverUrl, go]);

  const src = useMemo(() => {
    if (!serverUrl) return '';
    const params = new URLSearchParams(location.search);
    const url = new URL(serverUrl);
    url.pathname = '/';
    // the web app stores the token on first load and removes it from its own URL
    if (token) url.searchParams.set('token', token);
    const thread = params.get('thread');
    const tab = params.get('tab');
    if (thread) url.searchParams.set('thread', thread);
    if (tab) url.searchParams.set('tab', tab);
    return url.toString();
  }, [serverUrl, token, location.search]);

  const trouble = link === 'unauthorized' || link === 'unreachable';
  const dark = useBrowserDark();
  const palette = dark ? WEB_APP_DARK : WEB_APP_LIGHT;

  return (
    <div
      className="h-full w-full flex flex-col pt-10"
      style={{ background: palette.bg }}
      data-status-bar-foreground={dark ? 'light' : 'dark'}
    >
      <div className="flex-1 relative min-h-0">
        {src && (
          <iframe
            key={src}
            src={src}
            title="OpenMuse"
            className="absolute inset-0 w-full h-full border-0"
            style={{ background: palette.bg }}
            allow="clipboard-write"
          />
        )}
        {trouble && (
          <div className="absolute inset-x-4 top-3 z-10 rounded-2xl bg-app-surface border border-app-border shadow-lg p-3.5 flex items-start gap-3">
            <div className="mt-0.5 text-amber-600 shrink-0">
              {link === 'unauthorized' ? <IcWarning size={20} /> : <IcOffline size={20} />}
            </div>
            <div className="flex-1 min-w-0 text-[13px] leading-snug text-app-text">
              {link === 'unauthorized' ? (
                <>The server refused this phone&apos;s token.</>
              ) : (
                <>
                  Can&apos;t reach your Muse at <span className="font-mono break-all">{serverUrl}</span>. Retrying…
                </>
              )}
            </div>
            <button
              type="button"
              {...bindTap('setup.open')}
              className="shrink-0 rounded-xl bg-app-primary text-app-on-primary text-[12.5px] font-semibold px-3 py-1.5"
            >
              Change server
            </button>
          </div>
        )}
      </div>
      {/* the simulator draws its gesture bar over the last 16 px; keep the web app's tab bar clear of it */}
      <div className="h-4 shrink-0" style={{ background: palette.surface }} aria-hidden="true" />
    </div>
  );
}

// The web app inside the iframe follows the *browser's* colour scheme (it cannot see the
// simulator's), so the strips above and below it match the browser, not the phone theme.
const WEB_APP_LIGHT = { bg: '#f4f3fa', surface: '#ffffff' };
const WEB_APP_DARK = { bg: '#0f0f14', surface: '#1a1a22' };

function useBrowserDark(): boolean {
  const query = useMemo(
    () => (typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null),
    [],
  );
  const [dark, setDark] = useState(query?.matches ?? false);
  useEffect(() => {
    if (!query) return;
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, [query]);
  return dark;
}
