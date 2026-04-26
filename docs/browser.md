# The browser

The agent has one browser tool and two browsers to run it in: Chromium through Playwright on the computer the server runs on, and the phone's own WebView inside the nanoMuse app. The tool is the same either way — the same actions, the same numbered elements on the page, the same pictures in the chat, the same take-over — so a skill written against one works on the other, and a task can move from the desk to the phone without changing a line.

Where the browser sits in the order of things: the agent reaches a service through its API, MCP server or command-line tool first; then through a **logged-in `fetch`** (a request that carries the browser's cookies, no page rendered); then through the browser page itself; and only last through the screen of an app on the phone ([gui.md](gui.md)). The browser is rung two and three of that ladder.

## Two backends

| | `playwright` | `device` |
| --- | --- | --- |
| Runs | on the server, headless Chromium | in the nanoMuse app on the phone, an offscreen WebView |
| Needs | `pip install "nanomuse[browser]" && playwright install chromium` (or the `-browser` Docker image) | the app connected — either flavour; the local build always has it |
| Logins live in | `<workspace>/browser-profile/` — a persistent profile, so a login survives a restart | the app's WebView cookie store, on the phone |
| Take over | from the browser card: tap the picture to click, type, press Enter | the same WebView slides up in the app — no reload, same cookies, your fingers on the real page |
| Sites see | Chrome on Linux (or the profile's user agent) | Android WebView (or the profile's user agent) |

`backend = "auto"` (the default) uses the phone when a nanoMuse app with a browser is connected and Playwright otherwise. On the phone's local build there is no Chromium — PRoot cannot start one — so the WebView is the browser, always.

```toml
[browser]
enabled    = true
backend    = "auto"     # auto | playwright | device
profile    = ""         # mobile | desktop | "" (the backend's own: mobile on the phone, desktop on a computer)
headless   = true       # Playwright only
timeout_ms = 30000
```

`NANOMUSE_BROWSER_ENABLED=1` switches the tool on; `NANOMUSE_BROWSER_BACKEND` picks the backend. On the phone (`NANOMUSE_DEVICE=android`) the tool is on by default.

## What the agent can do

The tool's actions, identical on both backends:

| Action | What it does |
| --- | --- |
| `navigate url` | open a page; the reply lists the interactive elements on it, numbered |
| `extract` | the page's text (the first several thousand characters) |
| `click n` | click element `n` from the last listing (by its centre — what a finger would do) |
| `type n text` | fill element `n`, with the page's own input events so React and Vue forms notice |
| `key key` | press Enter, Tab, Escape … |
| `scroll dy` | scroll by pixels, negative for up |
| `back` | one step back in history |
| `screenshot` | a fresh picture for the chat card |
| `fetch url [method] [body]` | an HTTP request with the browser's cookies, no page rendered — an order list as JSON, an `.ics` behind a login, a form post |
| `profile name` | present as `mobile` (412×915, a phone's user agent) or `desktop` (1280×900), or a custom user agent and size |
| `close` | close the page; the profile and its cookies stay |

Every action that changes the page sends a frame to the chat: a JPEG of the page, its title and URL, and a caption of what just happened ("Clicked 'Sign in'"). Frames are the size of the profile's viewport in CSS pixels, so a point on the picture is the same point on the page — the take-over relies on that. They stay in memory on the server for the session; the last dozen per chat.

From a script inside the sandbox on the phone the same tool is `nanomuse-browser <action> …` ([local-runtime.md](local-runtime.md#the-python-side-on-a-phone)): `nanomuse-browser fetch https://example.com/api/orders` is rung two from the shell, under the same Sentinel.

## Logging in

A page that wants a login is the user's job, not the model's. The agent stops at the form and asks; the user signs in; the agent continues with the page as it is. The `browser` card in the chat is where that happens:

- **On the server's Chromium**: *Take over* on the card, then tap the picture to click, type into the focused field, press Enter, or open a URL; *Hand back* returns the page. The frame is the page; the taps are mapped onto it.
- **On the phone**: *Take over* slides the real WebView up as a sheet in the app — not a picture of it. Sign in with the phone's keyboard, its autofill and its password manager, and tap **Done**. The view goes back offscreen and the agent is told the page was handed back; its next look shows what you left. The agent's actions wait while the sheet is up.

Passwords go to the website, never through the model: what the model sees is the frame after you are done.

Cookies persist. On the server the Playwright profile is a real Chromium profile directory; on the phone the WebView's cookie store is flushed to disk after every navigation and `fetch`. Session cookies — the kind without an expiry, which a browser drops when it closes — do not survive a server restart on either side, so a site that uses only those asks again after `nanomuse serve` restarts; most sites set a longer "remember me" cookie once you tick the box.

### What does not work, and why

- **Google accounts cannot sign in inside a WebView.** Google refuses embedded sign-in (`disallowed_useragent`) for good reasons. The take-over sheet has an arrow that opens the same URL in the system browser — but a login made there stays in Chrome, not in nanoMuse's WebView. For Google services use the API path (a calendar's private `.ics` link, an app password for mail) instead of the browser; on the server's Chromium a Google login works but may be challenged as "not secure".
- **A QR code cannot be scanned on the same phone.** Sites that log in by "scan with our app" (微信, 支付宝, 淘宝 …) show the code where the camera would need to be. On the phone's browser this is a dead end; on the server's Chromium you scan the frame in the chat with the phone — which is the one case where the server's browser is the easier one.
- **Passkeys are not portable.** A passkey created in the phone's Chrome belongs to that browser's credential store; the WebView does not see it, and a headless Chromium on a server has none. Password-and-code logins work everywhere.
- **Downloads** land in the workspace: `<workspace>/downloads/` on the server (Playwright) and in the local build on the phone (where the agent can read them); in the connect build, whose agent is on the computer, they go to the phone's Downloads folder.
- One tab. A link that opens a new window opens in the same page instead.

## How the phone's browser works

The WebView must think it is on screen — a hidden WebView throttles `requestAnimationFrame` to nothing and timers to one a second, and many pages never finish loading. The app therefore gives it a screen: a private **virtual display** (an `ImageReader` surface, seen by nobody) with a `Presentation` window on it holding the WebView. Chromium composes frames into that surface at full speed whether or not the app is on screen; the latest frame is what a `screenshot` returns, so video, canvas and WebGL come out as they are. Measured on the emulator with the app in the background: 60 rAF/s, `setInterval(10 ms)` at 100/s, `visibilityState = visible`. On a device that refuses a virtual display the WebView falls back to being measured and drawn by hand.

Taps are injected as touch events at the element's centre, typing goes through the page's own setters plus `input` / `change` events (so frameworks notice), Enter presses the key. The one page is a singleton; the take-over moves that same `WebView` object into the sheet's container and back, so nothing reloads. Cookies, including third-party ones, are on; `CookieManager.flush()` runs after every load and `fetch`.

### The protocol

The phone announces `{"kind": "device", …, "browser": true}` when its socket opens; the server then sends `device_request` messages with `op: "browser"` and answers arrive as `device_result` with the same `id`. The ops, from `nanomuse/tools/browser_backends.py` (`DeviceBackend`), implemented in `android/…/browser/DeviceBrowser.kt`:

```
open      {user_agent, width, height, mobile}  → {url, title, width, height, …}
navigate  {url}                                → {url, title, …}
evaluate  {js, arg}                            → {value, encoded: "json"}   runs (js)(arg)
tap       {x, y}                               → {}                          CSS px of the viewport
type      {text}                               → {}                          into the focused element
key       {key}                                → {}
scroll    {dy}                                 → {}
back      {}                                   → {url, title, …}
settle    {timeout_ms}                         → {}
screenshot {quality}                           → {jpeg: base64, width, height}
state     {}                                   → {url, title, width, height, loading, user_control, host}
fetch     {url, method, headers, body}         → {status, headers, body, url}   with the WebView's cookies
profile   {user_agent, width, height, mobile}  → {}
close     {}                                   → {}
```

An unknown op or a failure comes back as `{"ok": false, "error": "…"}` — a message the model can read. Another app that wants to lend its browser to a nanoMuse server implements these fourteen ops and the hello.

## Testing it

`tests/test_browser.py` runs the tool against a fake backend (parity of the two, frames, the take-over hand-back) and, when Playwright and Chromium are installed, against the real one (the persistent profile, cookies across a restart, `fetch` with a session, the profile switch). The phone side has been driven end to end on an Android 13 emulator: every op above, cookies set by a page arriving in `fetch`, typing landing in the right field, the take-over sheet showing the same live page and the hand-back reaching the server. What still wants a real phone: vendors' battery managers pausing the app's process, and the virtual display on Android 8–10.
