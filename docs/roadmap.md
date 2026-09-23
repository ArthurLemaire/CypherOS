# Roadmap

nanoMuse is an open-source personal AI agent inspired by Meta's Muse. This page is the plan: what the shape is, which platform comes when, and what is a feature of one phase rather than the definition of the project.

## The shape

Muse, as Meta shipped it in September 2026, is one agent per person with several front doors: iOS and Android apps, the web at muse.ai, WhatsApp, and a Mac app. All of them are thin clients. The agent itself — the model loop, its browser, its files, the tasks it runs while you are away — lives in a cloud VM that belongs to that one user ("Muse Secure VM", with a confidential-computing variant announced for later). A Sentinel model sits between the agent and anything with consequences; approvals come to whichever client you have open.

nanoMuse keeps the shape and changes two things. The agent is open and runs where you say; and the *hands* are wider than APIs, because a Chinese day runs through apps that never had one. What stays the same is the centre: one agent, a name and a face, memory, goals worked on in the background, a feed, a Sentinel, approvals you scope.

## Three phases

The order follows where the VM is needed least.

### Phase 1 — the phone, no cloud VM (now)

The agent runs on a machine you own — a laptop, a home server, Docker — and the phone is the client: an Android app (a native shell around the web app, with notifications) and the web app itself, installable from any browser. Nothing runs in a cloud you do not control; the sandbox on Linux gives each command a namespace of its own, which is the small-scale answer to the VM.

Shipped: the agent, the Sentinel, the vault and the sandbox; the web and Android apps; skills (Agent Skills format) and MCP; 飞书 through lark-cli and 高德 through MCP without a screen; the phone operator on the simulated phone, with traces; the hosted showcase.

Still to do in this phase:

- **Local build** — the brain inside the APK, so that a phone with a key needs no server at all. A model behind an API is still on the network; the *agent* is not. This is the whole agent — chat, memory, goals, feed, skills, MCP, the Sentinel — and it is complete without the phone operator; operating the screen stays a switch that is off until you turn it on.
- **Android executor** — with that switch on, the nanoMuse app operates the real apps on the phone through an accessibility service: screenshots, gestures, the finger overlay; Shizuku as an option where it is allowed.
- **Starter quota** — a first budget of tokens from the showcase gateway, then your own key.
- **Muse features still missing** — durable tasks with a take-over hand-off, watches that trigger on the world, ideas with evidence, a follow-up queue.
- **Voice** — speak a message and see it as text before it goes, through any OpenAI-compatible `/audio/transcriptions`.

### Phase 2 — the web, on a cloud VM

A hosted nanoMuse: sign in from any browser and get an agent that runs in a VM of your own — its browser, its files, its background tasks inside — the way Muse does. The same package and the same Sentinel; the VM is the sandbox writ large. Your own key or the starter quota. The Android and web apps become clients of your VM as well as of your own machine, so the choice is a URL, not a fork.

The showcase gateway (`demo/showcase/`), which already starts a private nanoMuse per visitor next to the simulated phone, is the seed of this phase.

### Phase 3 — the desktop, both ways

A desktop app in two versions. *Local*: the agent runs on the computer you sit at, with its files and its browser, and asks you there. *Attached*: the same app as a client of your cloud VM, so a task started on the phone can be watched, taken over and finished at a desk. iOS follows as the same shell as the Android app.

## Features, not the definition

Some of what nanoMuse does today is easy to mistake for what it is. The definition is the first sentence of this page — an open-source personal AI agent inspired by Muse — and the rest is where the project happens to be in September 2026:

- **Operating a phone through its screen.** A hand for apps without an API — 12306, 微信, 支付宝 — and the last one the agent reaches for. 飞书 has a CLI, 高德 has an MCP server; those come first, and the showcase is written that way. It is a switch, off by default, and every build of nanoMuse — the server, the Android app, the local build to come — is a complete agent with it off.
- **A local APK.** Phase 1 puts the agent on hardware you own instead of a cloud VM. That is the starting point, not a principle: phase 2 is a VM per user, phase 3 a desktop in both forms.
- **Chinese services.** The built-in skills and the showcase speak Chinese because that is where the project lives and where the gaps were widest. They are the first set of skills, not the boundary: the agent, the Sentinel, the skills format and the apps are not tied to a country, a skill for another service is a folder with a `SKILL.md`, and the app ships in English and 简体中文 with room for more.

What does not change across phases: one agent rather than a framework, the Sentinel between it and anything irreversible, secrets that never reach the model, memory you can read and edit, any OpenAI-compatible model, MIT.

## Where things are tracked

The checklist in the [README](../README.md#roadmap) is the short form of this page. Issues and pull requests on [GitHub](https://github.com/nano-muse/nanoMuse) carry the detail; the [CHANGELOG](../CHANGELOG.md) records what landed.
