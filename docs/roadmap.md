# Roadmap

nanoMuse is an open-source personal AI agent inspired by Meta's Muse. This page is the plan: what the shape is, which platform comes when, and how the code got to where it is.

## The shape

Muse, as Meta shipped it in September 2026, is one agent per person with several front doors: iOS and Android apps, the web at muse.ai, WhatsApp, and a Mac app. All of them are thin clients. The agent itself — the model loop, its browser, its files, the tasks it runs while you are away — lives in a cloud VM that belongs to that one user ("Muse Secure VM"). A Sentinel model sits between the agent and anything with consequences; approvals come to whichever client you have open.

nanoMuse keeps the shape and changes two things. The agent is open and runs where you say — on the phone itself first; and the *hands* are wider than APIs, because a Chinese day runs through apps that never had one. What stays the same is the centre: one agent, a name and a face, memory, goals worked on in the background, a feed, approvals you scope.

## Two lines of code

**The Python line** (`nanomuse/`, `web/`, `demo/`, `site/`, tag `pre-openminis`) was the first attempt: a Python agent served from your own computer, a web app, a Kotlin host on the phone, a Sentinel, skills, MCP, a simulated phone for the showcase. It works, and it is frozen — it is the base of Phases 2 and 3, not of the phone.

**The Android line** (`android/`) is where the project now happens. Since 2026-09-24 the app is a modified copy of [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 (GPL-3.0), imported with `git subtree`: a complete agent that runs on the phone with no server — a Linux root file system under proot, a shell, a browser, MCP, skills, scheduled tasks, an accessibility executor, any OpenAI-compatible model. Phase 1 is that app, one small version at a time, each one an APK you can install, with the Muse shape added layer by layer. The whole repository is GPL-3.0-or-later as a consequence ([NOTICE](../NOTICE)).

## Phase 1 — the phone, no cloud VM (now)

Six versions. Each is a GitHub pre-release with an APK; `versionName` is a plain number so the in-app update check works.

| Version | Name | What it adds |
|---|---|---|
| 0.1.1 | 换皮 | OpenMinis 1.13 as nanoMuse: the icon and name, the brand blue instead of iOS blue, About / feedback / update source pointing here, GPL notices, one signing key for every version. Functionally identical to upstream. |
| 0.1.2 | 有名字有脸 | A name and a face: the red panda in the chat header with a Muse-style name pill and status line, a first conversation that asks what to call you and lets the agent pick its own name (written to `SOUL.md`), the name and face on every notification. Providers and the three setup cards stay as upstream ships them — bring your own key, or one of the OAuth logins. |
| 0.1.3 | Muse 的形状 | The app opens on a conversation, not a list: one main chat, side chats in a drawer, and a bottom bar with Ideas, Goals and Library. Goals are shaped in the chat and checked on a schedule in their own conversation; routines are the scheduled tasks OpenMinis already had, shown Muse's way; the library lists what the agent wrote. |
| 0.1.4 | 关键处先问你 | Approvals with scope — a stop before deleting, sending, paying and anything you could not undo, remembered per recipient / domain / folder if you say so; passwords and codes are always yours to type. |
| 0.1.5 | 记得你 | The feed written for you, the system files (SOUL, USER, MEMORY, HEARTBEAT) you can read and edit, a memory import, two-level status, the screen kept awake while it works, "continue?" instead of a premature wrap-up. |
| 0.1.6 → 0.2.0 | 形象与动效 | A face you choose — generated from a description with your own image model, animated by what the agent is doing; motion and polish everywhere; 0.2.0 is the first beta. |

There is no "Chinese services" version any more: the shell, MCP and skills OpenMinis ships already reach 飞书, 高德, 快递100 and the rest from a sentence in the chat, so those stay a matter of skills and docs ([services.md](services.md)), not of a release.

Kept from the plan's fine print: the Kotlin package stays `com.openminis.app` so upstream releases can be merged; new code lives in `io.github.nanomuse.*`; rebranding is a script that is re-run after every merge ([CONTRIBUTING](../CONTRIBUTING.md)).

## Phase 2 — the web, on a cloud VM

A hosted nanoMuse: sign in from any browser and get an agent that runs in a VM of your own — its browser, its files, its background tasks inside — the way Muse does. The Python line and the showcase gateway (`demo/showcase/`), which already starts a private agent per visitor next to a simulated phone, are the seed. The phone app becomes a client of your VM as well as an agent of its own.

## Phase 3 — the desktop, both ways

A desktop app in two versions. *Local*: the agent runs on the computer you sit at, with its files and its browser, and asks you there. *Attached*: the same app as a client of your cloud VM, so a task started on the phone can be watched, taken over and finished at a desk.

## Which docs belong to which line

Written for the Python line and kept for reference, not for the app in `android/`: [android.md](android.md), [app.md](app.md), [local-runtime.md](local-runtime.md), [gui.md](gui.md), [device.md](device.md), [browser.md](browser.md), [deployment.md](deployment.md), [configuration.md](configuration.md), [cli.md](cli.md), [sentinel.md](sentinel.md), [architecture.md](architecture.md), [design.md](design.md). Current for both: [brand.md](brand.md), [services.md](services.md), [showcase.md](showcase.md), this page, the [CHANGELOG](../CHANGELOG.md).

## Features, not the definition

- **Operating a phone through its screen.** A hand for apps without an API — 12306, 微信, 支付宝 — and the last one the agent reaches for. 飞书 has a CLI, 高德 has an MCP server; those come first. It is a switch, off by default.
- **A local APK.** Phase 1 puts the agent on hardware you own instead of a cloud VM. That is the starting point, not a principle.
- **Chinese services.** The built-in skills speak Chinese because that is where the project lives and where the gaps were widest. A skill for another service is a folder with a `SKILL.md`; the app ships in seventeen languages.

What does not change across phases: one agent rather than a framework, approvals between it and anything irreversible, secrets that never reach the model, memory you can read and edit, any OpenAI-compatible model, free software.
