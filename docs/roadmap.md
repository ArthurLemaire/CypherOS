# Roadmap

nanoMuse is a fully open-source personal AI agent in the shape of Meta's Muse, for every device you own. This page is the plan: what defines the project, which piece comes when, and how the code got to where it is.

## What defines it

Four things. Two are in the app today; two are the next versions. Everything else is a feature.

1. **Muse's shape.** One agent, not a toolbox: a name and a face, a first conversation, a feed written for you, goals worked on in the background, memory you can read and edit, an approval before anything you could not undo. Muse, as Meta shipped it in September 2026, is this shape served from a cloud VM per user through thin clients (iOS, Android, the web, WhatsApp, a Mac app); nanoMuse rebuilds the shape screen by screen and lets the agent run where you say. *In the app since 0.1.2; brought level with Muse's screens through 0.1.11.*
2. **Fully open.** GPL-3.0-or-later, the whole repository; no closed component, no account, no server you have to trust, no model you have to use. Every release is built from its tag, signed with one key and installed by hand; the notes say what changed and what is not there yet. Muse, 豆包 and 千问 are products you are given; nanoMuse is one you own — and it stands on another free project, OpenMinis, whose releases it can still merge. *Since 0.1.1.*
3. **Any app, API or not.** Most of a day in China runs through apps that never had an API — 12306, 微信, 支付宝, 美团. The agent climbs a ladder: a skill, a CLI or an MCP server first; then a page fetched with your login; then the in-app browser; then, when you allow it, the device's own screen, looking at it and tapping, typing and swiping the way you would. A task is rarely all screen — it is a shell command that finds the order number, a screen that finds the button, a question to you before it is pressed — and the approvals are the same on every rung. Off by default. The Python line designed and built this ([gui.md](gui.md)); the Android app has the raw material — OpenMinis' accessibility CLI — and gets the hand itself in **0.1.12**.
4. **Every device.** One agent, and every device you own is a pair of hands and a front door for it: say it on the phone, it happens on your PC; say it to your glasses, it happens on both. Not a cloud VM the devices dial into — the agent runs on hardware of yours, and the other devices are paired to it. Pairing is explicit, a device's abilities are tools with the same approvals, and a task started on one device can be watched, taken over and finished on another. The phone drives your computer first, one way, in **0.1.13**; a desktop app, iOS, the web on a machine of your own and glasses follow.

What does not change: one agent rather than a framework, approvals between it and anything irreversible, secrets that never reach the model, memory you can read and edit, any OpenAI-compatible model, free software.

## Two lines of code

**The Python line** (`nanomuse/`, `web/`, `demo/`, `site/`, tag `pre-openminis`) was the first attempt: a Python agent served from your own computer, a web app, a Kotlin host on the phone, a Sentinel, skills, MCP, a phone operator, a simulated phone for the showcase. It works, and it is frozen — it is the base of the desktop and web front doors, and the design record for the screen as a hand ([gui.md](gui.md), [device.md](device.md), [sentinel.md](sentinel.md)).

**The Android line** (`android/`) is where the project happens. Since 2026-09-24 the app is a modified copy of [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 (GPL-3.0), imported with `git subtree`: a complete agent that runs on the phone with no server — a Linux root file system under proot, a shell, a browser, MCP, skills, scheduled tasks, an accessibility CLI, any OpenAI-compatible model. Every version is an APK you can install, with the Muse shape added layer by layer. The whole repository is GPL-3.0-or-later as a consequence ([NOTICE](../NOTICE)).

## Phase 1 — the phone (now)

The alpha versions and a beta, each a GitHub release with an APK, titled `nanoMuse <version> · <Codename>` — one English word for what the version is about; `versionName` stays a plain number so the in-app update check works.

| Version | Codename | What it adds |
|---|---|---|
| 0.1.1 | Foundation | OpenMinis 1.13 as nanoMuse: the icon and name, the brand blue instead of iOS blue, About / feedback / update source pointing here, GPL notices, one signing key for every version. Functionally identical to upstream. |
| 0.1.2 | Identity | A name and a face in the chat header with a Muse-style name pill and status line, a first conversation that asks what to call you and lets the agent pick its own name (written to `SOUL.md`), the name and face on every notification. Providers stay as upstream ships them — bring your own key, or one of the OAuth logins. |
| 0.1.3 | Home | The app opens on a conversation, not a list: one main chat, side chats in a drawer, and a bottom bar with Ideas, Goals and Library. Goals are shaped in the chat and checked on a schedule in their own conversation; routines are the scheduled tasks OpenMinis already had, shown Muse's way; the library lists what the agent wrote. |
| 0.1.4 | Guardrails | Approvals with scope — a stop before deleting, sending, paying and anything you could not undo, remembered per recipient / domain / folder if you say so; passwords and codes are always yours to type. |
| 0.1.5 | Memory | The feed written for you, the system files (SOUL, USER, MEMORY, HEARTBEAT) you can read and edit, a memory import, two-level status, the screen kept awake while it works, "continue?" instead of a premature wrap-up. |
| 0.1.6 | Avatar | A face you choose — described in a sentence, drawn four ways by your own image model, posed for every state by the same model, animated by what the agent is doing; pages cross-fade, cards settle in, the heart pops. |
| 0.1.7 | Welcome | The first run, in Muse's shape: a welcome screen with the three steps — add a provider, pick from the models it serves, meet the agent — in front of a chat that could not answer without them. |
| 0.1.8 | Polish | The shell brought level with Muse's: Muse's type scale, the one-row composer pill, only the name under the face, grey reply bubbles, and Muse's settings pages on every screen. |
| 0.1.9 | Portrait | The face, Muse's way: "change your avatar to…" in the chat, four takes to pick from, poses, a share card; the agent's page behind the face; five avatar sizes; the name pill re-measured. |
| 0.1.10 | Motion | The three models named — chat, image, video — in Settings and in what the agent knows; with a video model the face gets a looping clip per state; pictures and clips on request; the agent explains a missing model instead of a fixed message. |
| 0.1.11 | Hatch | The built-in dragon, stills and clips in the APK; the first conversation read by the chat model — a detour is answered and the name asked again later, its own names proposed in your language; one Model Studio key for all three models, or a provider per model. |
| 0.1.12 | Hands *(planned)* | **The screen as a hand — a working demo.** With the accessibility service on and the *Phone* switch on, the agent looks at the screen (a picture plus the accessibility tree), taps, types and swipes in the apps that have no API, and shows what it is doing in a floating capsule with *Stop*. The ladder is in the prompt and the skills: a skill, CLI, MCP server or the browser first, the screen last, and the agent says so before it starts. Logins, passwords and codes are handed to you. The same `RiskGate` approvals before paying, sending or deleting. Two demo tasks end to end — read 12306's real seats for a route; reply in a chat app and stop at the send button. Off by default. |
| 0.1.13 | Reach *(planned)* | **The phone drives your computer — a working demo.** A small companion on the PC (Linux, macOS, Windows) that the app pairs with by code on the same network; a sentence on the phone runs there — the shell, the files, the browser — and the results, the step cards and the approvals come back to the phone. One way, phone to computer. The pairing, the device list and the "which device does this run on" are the pieces every later device reuses. |
| 0.2.0 | Beta | Polish from the first weeks of use; the first beta. |

There is no "Chinese services" version: the shell, MCP and skills OpenMinis ships already reach 飞书, 高德, 快递100 and the rest from a sentence in the chat, so those stay a matter of skills and docs ([services.md](services.md)), not of a release.

Kept from the plan's fine print: the Kotlin package stays `com.openminis.app` so upstream releases can be merged; new code lives in `io.github.nanomuse.*`; rebranding is a script that is re-run after every merge ([CONTRIBUTING](../CONTRIBUTING.md)).

## Phase 2 — the other front doors

Each one adds a pair of hands and a way in for the same agent; the order can change with what people ask for.

- **Desktop.** An app for the computer you sit at, in two roles: an agent of its own — its files, its browser, its screen, asking you there — and a client of the phone's, so a task started on the phone can be watched, taken over and finished at a desk. The one-way link of 0.1.13 becomes two-way here.
- **iOS.** OpenMinis already runs there; nanoMuse's shape and the pairing follow.
- **The web, on a machine of your own.** A nanoMuse that runs on a VM or a home server of yours and is reachable from any browser — the Muse arrangement, minus Meta. The Python line and the showcase gateway (`demo/showcase/`), which already starts a private agent per visitor, are the seed. The phone and the desktop become clients of it as well as agents of their own.
- **Glasses.** The shortest front door: a sentence in, a sentence back, the hands elsewhere.

## Which docs belong to which line

Written for the Python line and kept as design records, not as descriptions of the app in `android/`: [android.md](android.md), [app.md](app.md), [local-runtime.md](local-runtime.md), [gui.md](gui.md), [device.md](device.md), [browser.md](browser.md), [deployment.md](deployment.md), [configuration.md](configuration.md), [cli.md](cli.md), [sentinel.md](sentinel.md), [architecture.md](architecture.md), [design.md](design.md). Current for both: [brand.md](brand.md), [services.md](services.md), [showcase.md](showcase.md), this page, the [CHANGELOG](../CHANGELOG.md).
