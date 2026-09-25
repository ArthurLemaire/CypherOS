<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/app-icon.png" width="128" alt="nanoMuse app icon">
</p>

<h1 align="center">nanoMuse</h1>

<p align="center">A personal AI agent that lives on your phone. Open source, inspired by Meta Muse.</p>

<div align="center">
  <p>
    <a href="https://github.com/nano-muse/nanoMuse/blob/main/README.md">English</a> |
    <a href="https://github.com/nano-muse/nanoMuse/blob/main/README_zh.md">简体中文</a> |
    <a href="https://nano-muse.github.io/">Website</a> |
    <a href="https://github.com/nano-muse/nanoMuse/releases/latest">Download</a>
  </p>
  <p>
    <a href="https://github.com/nano-muse/nanoMuse/releases"><img src="https://img.shields.io/github/v/release/nano-muse/nanoMuse?include_prereleases&label=release" alt="Latest release"></a>
    <a href="https://github.com/nano-muse/nanoMuse/releases"><img src="https://img.shields.io/badge/Android-8.0%2B%20arm64-3DDC84?logo=android&logoColor=white" alt="Android 8.0+ arm64"></a>
    <a href="https://github.com/nano-muse/nanoMuse/actions/workflows/android.yml"><img src="https://github.com/nano-muse/nanoMuse/actions/workflows/android.yml/badge.svg?branch=main" alt="Android build"></a>
    <a href="https://github.com/nano-muse/nanoMuse/blob/main/LICENSE"><img src="https://img.shields.io/github/license/nano-muse/nanoMuse" alt="GPL-3.0-or-later"></a>
    <a href="https://github.com/nano-muse/nanoMuse"><img src="https://img.shields.io/github/stars/nano-muse/nanoMuse?style=flat&logo=github" alt="GitHub stars"></a>
  </p>
</div>

nanoMuse is an open-source take on Meta's [Muse](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/): one agent with a name and a face that does things instead of answering questions, keeps working while the app is closed, remembers you, and stops to ask before anything you could not undo. Muse runs in a cloud VM per user; nanoMuse runs **on the phone** — a Linux root file system, a shell, a browser, MCP, skills and scheduled tasks inside the APK, with a model you bring. No server, no account, GPL-3.0.

<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/avatar-moods.png" width="88%" alt="The same red panda in five states: at rest, working, waiting, pleased, sorry">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/screenshots/chat-approval.png" width="23%" alt="Chat: the agent stops before deleting files and asks">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/screenshots/feed.png" width="23%" alt="Feed: posts written for you this morning">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/screenshots/goals.png" width="23%" alt="Goals: tracked on a schedule, with routines">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/screenshots/avatar.png" width="23%" alt="Avatar: describe a face, your image model draws four, pick one">
</p>

## Install

1. Download `nanoMuse-<version>-arm64.apk` from the [latest release](https://github.com/nano-muse/nanoMuse/releases/latest) — Android 8.0 or newer, a 64-bit phone. Verify with `sha256sum -c nanoMuse-<version>-arm64.apk.sha256` if you like.
2. Open it. Android asks once to allow the install; every version is signed with the same key, so updates install over the previous one and keep your data.
3. Add a model: any OpenAI-compatible endpoint with your own key, or one of the OAuth sign-ins the app ships with. The first conversation asks what to call you and lets the agent pick its own name.
4. Optional — *Settings → Image & video models*: an image model (qwen-image-3.0 on Alibaba Cloud Model Studio, gpt-image-1, or any provider with the OpenAI images endpoint) lets the agent change its face and draw pictures; a video model (MiniMax-H3 on Model Studio) makes the face move. Muse has these built in; nanoMuse uses your own, and the agent tells you when one is missing.

The app checks this repository's releases for updates. Release notes for each version are in [docs/releases/](docs/releases/) and the [CHANGELOG](CHANGELOG.md).

## What it does

| | |
|---|---|
| **Does things** | A Linux shell, a browser, MCP servers, skills in the [Agent Skills](https://agentskills.io) format, and the apps on your phone through their screens when there is no API. The agent picks the hand the job needs and shows each step as a card you can open. |
| **Asks first** | A stop before deleting, sending or paying — in the shell and in the browser — with an approval you scope to once, this chat, or always for this recipient, domain or folder, and can revoke under Permissions. Passwords and verification codes are always yours to type. |
| **Keeps going** | Goals are shaped in the chat and checked on a schedule in their own conversation; routines run while the app is closed; the screen stays on while it drives the phone; at 200 steps it asks "continue?" instead of wrapping up early. |
| **Writes you a feed** | Every morning, three to six short posts from what it knows about you and what you asked it to follow, as cards you can like, discuss in a side chat, or delete. One sentence steers it. |
| **Remembers you** | Who it is (`SOUL.md`), what it knows about you (`USER.md`), what it remembers (`GLOBAL.md` and a diary) and when it wakes (`HEARTBEAT.md`) are files you can read and edit in the app. Bring what another assistant knew with *Import memory*. |
| **Has a face** | Describe one in a sentence; your image model draws four; you pick. The app poses it for every state — working, waiting, pleased, sorry — and it breathes, bobs, tilts, pops and shakes with what the agent is doing; with a video model, each state is a short looping clip. The red panda is the default. |
| **Ideas and Library** | Things to ask next, from your goals and memory; and everything it made, with previews. |

Everything above is a Muse screen or behaviour, rebuilt on the phone; the rest of OpenMinis — the terminal, the in-app browser, MCP and skill management, model groups, token usage, the accessibility executor, shared folders — is kept and reachable from the same menus.

## How it works

The app is [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13, modified: a complete on-device agent — Alpine Linux under [proot](https://github.com/nano-muse/proot), a shell, a WebView browser, MCP, skills, scheduled tasks, an accessibility executor, any OpenAI-compatible model — imported into [`android/`](android/) with `git subtree` so upstream releases can still be merged. What nanoMuse adds lives in `io.github.nanomuse.*`:

| Package | What |
|---|---|
| `ui/home`, `ui/header` | The home shell: one main chat, side chats in a drawer, the Feed · Ideas · Goals · Library bar, Muse's header with the face, the name pill and the status line |
| `guard` | `ShellGuard` and `BrowserGuard` classify commands and page actions; `RiskGate` stops the tool call and shows the approval card; grants are remembered per scope |
| `goals`, `ideas`, `library` | Goals as scheduled conversations with a plan and a check-in; ideas from memory and goals; the library of what it wrote |
| `feed`, `sysfiles` | The morning routine that writes ` ```nanomuse-feed ` blocks into `minis-global/nanomuse/feed/`, the cards, the steering sentence; the system-files pages and memory import |
| `avatar`, `ui/avatar` | `ImageGen` on top of OpenMinis' image endpoints (`images/generations`, `images/edits`, DashScope's native edit), the studio, `AvatarStore`, and the animated `AgentAvatar` |
| `status` | The two-level status (tool title under the face, action chips on the cards), `KeepAwake`, the last browser frame per step |

Edits to upstream files are marked `// nanoMuse:`; `scripts/rebrand.py` re-applies the branding after every subtree pull. Building from source: [CONTRIBUTING.md](CONTRIBUTING.md). Your messages go only to the model you configured; files, memory and the avatar's pictures stay under the app's private storage.

## Versions

One small version per stage, each a GitHub release with an APK. The plan and its reasoning: [docs/roadmap.md](docs/roadmap.md).

| Version | Codename | What it added |
|---|---|---|
| [0.1.1](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.1) | Foundation | OpenMinis as nanoMuse: icon, name, brand colours, About / feedback / update source, GPL notices, one signing key |
| [0.1.2](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.2) | Identity | The red panda and a Muse-style header; a first conversation that names the agent; the name and face on every notification |
| [0.1.3](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.3) | Home | Opens on a chat, not a list; side chats in a drawer; Ideas, Goals and Library; goals shaped in the chat and checked on a schedule |
| [0.1.4](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.4) | Guardrails | Approvals with scope before deleting, sending, paying; passwords always yours |
| [0.1.5](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.5) | Memory | The feed; SOUL / USER / MEMORY / HEARTBEAT readable and editable; memory import; the screen stays on; "continue?" |
| [0.1.6](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.6) | Avatar | A face you describe, your image model draws, you choose, posed for every state and animated; pages cross-fade, cards settle, hearts pop |
| [0.1.7](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.7) | Welcome | The first run: a welcome screen with the three steps — provider, the models it serves, meet the agent |
| [0.1.8](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.8) | Polish | The shell level with Muse's: type, the composer pill, only the name under the face, grey bubbles, Muse's settings pages |
| [0.1.9](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.9) | Portrait | The face, Muse's way: "change your avatar to…" in the chat, four takes to pick from, poses, a share card; the agent's page behind the face; five avatar sizes; the name pill re-measured |
| [0.1.10](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.10) | Motion | The three models named — chat, image, video — in Settings → Image & video models and in what the agent knows; with a video model the avatar gets a looping clip per state; pictures and clips on request; the agent explains a missing model instead of a fixed message |
| 0.2.0 | Beta | Polish from the first weeks of use; the first beta |

**Next:** a hosted nanoMuse on a VM of your own, reachable from any browser, with the phone app as its client; then a desktop app, local or attached to that VM. The Python line this project started with — the agent and its Sentinel, the web app, the simulated phone — is frozen at tag [`pre-openminis`](https://github.com/nano-muse/nanoMuse/releases/tag/pre-openminis) with its docs under [docs/](docs/), and is the base of those phases.

## nanoMuse and Meta Muse

| Meta Muse | nanoMuse |
|---|---|
| Runs in a secure cloud VM per user | Runs on the phone, in a proot Linux inside the app; nothing leaves the device but the model calls |
| Sentinel approves sensitive actions | `RiskGate` stops the call: allow once, for this chat, always for this scope, or deny; browser guard for pay and send buttons; never types passwords |
| Remembers you | Markdown files you can read and edit, plus a diary; import from another assistant |
| Works on goals in the background | Goals checked on a schedule in their own conversation; routines as scheduled tasks; notifications for approvals and results |
| A feed written for you | A morning routine that writes cards from your memory, goals and one steering sentence |
| iOS, Android, web, WhatsApp, a Mac app | Android today; the web on a VM of your own and a desktop app next |
| A plush avatar that changes pose while it works | A face your image model draws and poses, a looping clip per state from your video model; the red panda by default |
| Meta's models | Three of your own: any OpenAI-compatible chat model (or the OAuth sign-ins the app ships with), an image model, an optional video model |
| Closed | GPL-3.0-or-later |

## Contribute

Use it for a real task, report what broke, then pick something focused. [CONTRIBUTING.md](CONTRIBUTING.md) has the build setup ([android/BUILDING.md](android/BUILDING.md) and the toolchain scripts in `scripts/android/`), the conventions (`com.openminis.app` stays, new code in `io.github.nanomuse.*`, `// nanoMuse:` on upstream edits, `Signed-off-by` on commits) and how releases are cut. [Issues](https://github.com/nano-muse/nanoMuse/issues) · [Pull requests](https://github.com/nano-muse/nanoMuse/pulls).

## Acknowledgements

nanoMuse stands on other people's work; [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) has the terms.

- [OpenMinis](https://github.com/OpenMinis/OpenMinis) — the on-device agent the app is built on: proot Linux, shell, browser, MCP, skills, scheduled tasks, the accessibility executor.
- [proot](https://github.com/proot-me/proot) (via [nano-muse/proot](https://github.com/nano-muse/proot)) and [Alpine Linux](https://alpinelinux.org/) — the sandbox inside the APK.
- [MobileGym](https://github.com/Purewhiter/mobilegym), [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench), [PhoneHarness](https://github.com/lsdefine/PhoneHarness), [CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse), [Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM), [ClawGUI](https://github.com/ClawGUI/ClawGUI-APP) — the phone operator, the traces and the product ideas of the Python line.

## Disclaimer

nanoMuse is an independent community project. It is not affiliated with, endorsed by, or derived from Meta Platforms, Inc. or its Muse product; Muse is a trademark of Meta Platforms, Inc. The red panda is the project's own.

## License

[GPL-3.0-or-later](LICENSE). The Android app is based on OpenMinis 1.13 (GPL-3.0), modified since 2026-09-24; see [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Earlier versions of the Python line were released under MIT (tag `pre-openminis`).
