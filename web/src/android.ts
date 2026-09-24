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
  /**
   * The accessibility service that operates the phone's screen: "on", "off", or "unsupported"
   * (Android 10 and older cannot take screenshots for it).
   */
  accessibilityState?(): string;
  /** Open Android Settings → Accessibility, where the service is switched on. */
  openAccessibilitySettings?(): void;
  /** Open this app's page in Android Settings (the "Allow restricted settings" menu lives there). */
  openAppSettings?(): void;
  /** JSON: what stands in the way of running in the background (see KeepRunningStatus). */
  keepRunning?(): string;
  /** Open the settings page for one of them: battery, overlay, alarms, autostart, app. */
  openKeepRunning?(what: string): void;
  setStartOnBoot?(on: boolean): void;
  /** Zip the crash files, the runtime log and the app's logcat lines; open the share sheet. */
  exportLogs?(): void;
}

export interface KeepRunningStatus {
  battery_unrestricted: boolean;
  overlay: boolean;
  exact_alarms: "granted" | "denied" | "n/a";
  boot_start: boolean;
  /** xiaomi · huawei · honor · oppo · vivo · samsung · meizu · "" */
  vendor: string;
  /** whether this phone has an auto-start / background manager page the app can open */
  autostart_settings: boolean;
  android: number;
  /** the runtime runs on this phone (local mode) */
  local: boolean;
}

export function keepRunningStatus(): KeepRunningStatus | null {
  const app = androidApp();
  if (!app || typeof app.keepRunning !== "function") return null;
  try {
    return JSON.parse(app.keepRunning()) as KeepRunningStatus;
  } catch {
    return null;
  }
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

/** What the app says about its accessibility service; null when this is not the Android app. */
export function accessibilityState(): "on" | "off" | "unsupported" | null {
  const app = androidApp();
  if (!app || typeof app.accessibilityState !== "function") return null;
  const state = app.accessibilityState();
  return state === "on" || state === "off" || state === "unsupported" ? state : null;
}
