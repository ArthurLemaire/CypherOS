/**
 * The Android app (android/) shows this web app in a WebView and exposes the phone-side bits
 * as `window.OpenMuseAndroid`. Web Push does not work there — the app keeps its own connection
 * to the server and posts notifications itself — so the settings offer that instead.
 */
export interface AndroidBridge {
  version(): string;
  serverUrl(): string;
  notificationsEnabled(): boolean;
  setNotificationsEnabled(on: boolean): void;
  disconnect(): void;
}

export function androidApp(): AndroidBridge | null {
  const w = window as unknown as { OpenMuseAndroid?: AndroidBridge };
  return w.OpenMuseAndroid ?? null;
}
