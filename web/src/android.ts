/**
 * The Android app (android/) shows this web app in a WebView and exposes the phone-side bits
 * as `window.NanoMuseAndroid`. Web Push does not work there — the app keeps its own connection
 * to the server and posts notifications itself — so the settings offer that instead.
 */
export interface AndroidBridge {
  version(): string;
  serverUrl(): string;
  notificationsEnabled(): boolean;
  setNotificationsEnabled(on: boolean): void;
  disconnect(): void;
  /** Whether this app hosts the agent's browser itself (a WebView the user can take over in place). */
  hasBrowser?(): boolean;
  /**
   * Show the agent's browser in the app for the user to drive; when done the app dispatches
   * `nanomuse:browser-handed-back` with `{thread}` on window.
   */
  takeOverBrowser?(thread: string): void;
}

export function androidApp(): AndroidBridge | null {
  const w = window as unknown as { NanoMuseAndroid?: AndroidBridge };
  return w.NanoMuseAndroid ?? null;
}

/** True when the app can hand the agent's own browser to the user in place (no screenshots in between). */
export function nativeTakeOver(): boolean {
  const app = androidApp();
  return !!app && typeof app.takeOverBrowser === "function" && (typeof app.hasBrowser !== "function" || app.hasBrowser());
}
