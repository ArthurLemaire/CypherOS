/* OpenMuse service worker: Web Push and the app badge.
 *
 * The server (openmuse/server/push.py) sends {title, body, tag, url, badge, kind}. If the
 * app is on screen the card is already there, so nothing is shown; the badge is kept in
 * step either way. Tapping a notification focuses the app on the right chat.
 */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

async function setBadge(n) {
  if (typeof n !== "number" || !("setAppBadge" in navigator)) return;
  try {
    if (n > 0) await navigator.setAppBadge(n);
    else await navigator.clearAppBadge();
  } catch {
    /* badges are best effort */
  }
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "OpenMuse", body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    (async () => {
      await setBadge(data.badge);
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const onScreen = windows.some((c) => c.visibilityState === "visible");
      if (onScreen && data.kind !== "test") return;
      await self.registration.showNotification(data.title || "OpenMuse", {
        body: data.body || "",
        tag: data.tag || undefined,
        renotify: !!data.tag,
        icon: "/icon-192.png",
        badge: "/icon-192.png",
        timestamp: data.ts ? Date.parse(data.ts) : Date.now(),
        data: { url: data.url || "/", kind: data.kind || "" },
      });
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        if ("focus" in client) {
          await client.focus();
          client.postMessage({ type: "open", url });
          return;
        }
      }
      await self.clients.openWindow(url);
    })(),
  );
});
