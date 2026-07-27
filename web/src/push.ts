/** Web Push on the client: register the service worker, subscribe, keep the app badge. */
import { api } from "./api";

export type PushState = "unsupported" | "insecure" | "denied" | "off" | "on";

export function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export async function registerWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return null;
  try {
    const reg = await navigator.serviceWorker.register("/sw.js");
    return reg;
  } catch {
    return null;
  }
}

export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  if (!window.isSecureContext) return "insecure";
  if (Notification.permission === "denied") return "denied";
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = reg ? await reg.pushManager.getSubscription() : null;
  return sub ? "on" : "off";
}

function keyBytes(base64url: string): ArrayBuffer {
  const padding = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}

/** Ask for permission, subscribe with the server's VAPID key, hand the subscription over. */
export async function enablePush(publicKey: string): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  if (!window.isSecureContext) return "insecure";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return permission === "denied" ? "denied" : "off";
  const reg = (await registerWorker()) ?? (await navigator.serviceWorker.ready);
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) });
  }
  await api.pushSubscribe(sub.toJSON() as Record<string, unknown>);
  return "on";
}

export async function disablePush(): Promise<PushState> {
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = reg ? await reg.pushManager.getSubscription() : null;
  if (sub) {
    try {
      await api.pushUnsubscribe(sub.endpoint);
    } finally {
      await sub.unsubscribe();
    }
  }
  return "off";
}

/** The number on the app icon: cards waiting for you. */
export function setAppBadge(n: number): void {
  const nav = navigator as Navigator & { setAppBadge?: (n: number) => Promise<void>; clearAppBadge?: () => Promise<void> };
  try {
    if (n > 0) void nav.setAppBadge?.(n);
    else void nav.clearAppBadge?.();
  } catch {
    /* best effort */
  }
}
