# Changelog

All notable changes to nanoMuse. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/). Unreleased changes are on `main`.

## [0.1.6] - 2026-09-25 · Avatar

The agent gets a face of your choosing. Describe it in a sentence, your own image model draws four, you pick one, and the app poses it for every state the agent can be in — then the face on the disc breathes, bobs, tilts, pops and shakes with what the agent is doing, the way Muse's does. Around it, the small motions that make an app feel finished: pages that cross-fade, feed cards that settle in, a heart that pops.

### Added

- **Avatar page** (`io.github.nanomuse.avatar`, `ui/avatar`; Settings → Avatar, or tap the face on any header). Muse's layout: the face on its disc with the agent's name and what it is doing right now, the preview cycling through the moods; *Describe a new face* — one sentence, a row of style chips (flat, 3D clay, watercolour, pixel, line art, sticker) and a blue *Draw four*; *Pick one* — a 2×2 grid of candidates with a shimmer while they draw, a check on the chosen one, and *Use this one*. Failed tiles say why and retry on tap. The ⋯ menu holds *Name and style* (the soul editor), *Image model*, *Redraw the moods* and *Back to the red panda*.
- **Bring your own image model.** Generation goes through the providers you already configured — no new key: any enabled OpenAI-compatible, OpenRouter or xAI instance, with the catalogue's image models offered as chips and a sensible default per host (`qwen-image-3.0` on Alibaba Bailian / DashScope, `gpt-image-1` on OpenAI, `grok-2-image` on xAI, `google/gemini-2.5-flash-image` on OpenRouter). Candidates use OpenMinis' `images/generations`; the four moods are image *edits* of the picture you chose — *working* wears headphones at a laptop, *waiting* looks up with a question mark, *happy* hugs a star, *error* has a sweat drop — through `images/edits` on OpenAI-style hosts and DashScope's native `qwen-image-edit-max` on Alibaba hosts, so the character stays the same. Two calls run at a time; rate limits are retried twice with a growing pause.
- **The face moves.** `AgentAvatar` cross-fades between moods (260 ms) and animates them: a slow breath at rest (2.6 s, +1.8 %), a quicker breath and a 2.5 dp bob while working, a ±4° tilt while it waits for you, a spring pop when a turn ends well, a 420 ms shake when it failed. A custom face fills the whole disc; the built-in red panda keeps its inset. The afterglow only reads outcomes from the run that just ended — a plain reply after an old failure smiles — and a run you stopped ends quietly.
- **Pictures stay on the phone**: `minis-global/nanomuse/avatar/{base,working,waiting,happy,error}.png` (512 px), `candidates/0–3.png` and `avatar.json` (prompt, style, model, time). Candidates survive restarts until you draw again; *Back to the red panda* removes the face and its moods but keeps the candidates.
- Motion elsewhere: home pages cross-fade (160 ms in, 120 ms out; the chat underneath fades a touch slower so the switch reads as one), new feed posts settle in and deleted ones fade out (`animateItem`), the like heart pops with a spring and its colour eases.

### Changed

- The header's face opens the avatar page; the name pill still opens the soul settings (name, style).
- Deep link `minis://settings/avatar` (also `/face`).
- versionCode 7.

### Kept, on purpose

- The built-in red panda is still the default and one tap away; the launcher icon is untouched. Provider instances, keys and OAuth are OpenMinis' own — the avatar page only reads what you configured there.

## [0.1.5] - 2026-09-25 · Memory

The agent starts to keep things: a feed it writes for you every morning, the files that make it what it is — who it is, what it knows about you, what it remembers, when it wakes — readable and editable in one place, and a way to bring over what another assistant already knew. Long tasks keep the screen on and ask "continue?" instead of wrapping up early.

### Added

- **Feed tab** (`io.github.nanomuse.feed`, `ui/feed`). A fifth glyph in the bottom bar. A built-in routine — *Write the feed*, daily at 08:00, visible under Goals → Routines with its switch, editor and run records like any other — asks the agent to read GLOBAL.md, the last seven days of diary, USER.md and the goals, and write three to six short posts. Each post is a fenced ` ```nanomuse-feed ` JSON block in the feed's own side chat ("Feed"); the app turns every block into `minis-global/nanomuse/feed/YYYY-MM-DD/NN.md` (front matter: title, type, emoji, source, created, liked) and the tab renders them as Muse's cards on a grey canvas — weekday + part of day as the section title, a 44 dp emoji tile, title, Markdown body, heart · *Discuss* · ⓘ. *Discuss* opens a side chat titled after the post with its text as the opener; ⓘ shows type, time, sources, the file path, and a delete. The first visit shows Muse's *About the feed* card with the steering sentence and *Edit* / *Got it*; the round sliders button at the top right opens the sheet — the sentence (`feed-preferences.md`, quoted in the feed's system prompt), the daily switch, "Daily at 08:00 · tap to change" (opens the routine editor), *Write it now*. Twelve posts a day at most; thirty days are kept.
- **System files** (Settings → System files; also in the ⋯ menu of every tab and the drawer). Muse's list: an `MD` badge, the file name, "MD · 358 B · 03:13", sort by name or by last modified, ⋮ to copy or share. Opening a file gives Muse's page: round back button, the name, a pill with the pencil and ⋯, an italic *About this file* quote, and the file rendered as Markdown. Five files: `SOUL.md` (the persona — saving refreshes the cached soul), `USER.md` (new — what the agent knows about you), `GLOBAL.md` (the memory; ⋯ jumps to OpenMinis' memory pages for the diary), `feed-preferences.md`, and `HEARTBEAT.md` — a read-only view of every routine and goal check with schedule and last run, with a ♥ badge. Edits use a monospace editor with a hint, Cancel and a blue Save.
- **USER.md in the system prompt.** When the file has content it is appended after the memory fragments, with one paragraph telling the model to keep it current from its shell (`/var/minis/memory/USER.md`) and never to put secrets in it. The file lives next to `GLOBAL.md` and `SOUL.md` in `minis-global/memory/` so the agent can reach it — the outline had it one level up.
- **Import memory** (System files → ⋯ → Import memory). One page: the prompt to give your other assistant ("gather everything you remember about me into bullet points…") with a copy button, a *From* field, a paste box, and *Add to memory*, which appends `### <date> · <from>` and the text under a `## 导入` / `## Imported` section at the end of `GLOBAL.md` (created if missing, recognised in either language).
- **Finished browser steps** keep their picture: the last live frame of the in-app browser is remembered per tool block (`BrowserFrames`) and shown when the step saved no screenshot of its own, and the floating status bar reads "Open test page · Done" for a completed `browser_use` step. The two levels of status stay as they were: the running tool's title under the face, the action chips on the cards.
- **Screen stays on** while the agent drives the in-app browser or another app through the accessibility service (`KeepAwake`, hooked in `ChatScreen` next to `isStreaming`; the a11y CLI handler stamps every command). Ordinary chat and shell work let it time out as usual.
- **"Still going after 200 steps".** When the agent loop reaches `MAX_AGENT_TURNS` it no longer writes an error into the chat; a card above the composer asks whether to keep going — *Continue* resumes from where it stopped, *Stop here* leaves OpenMinis' Resume banner in place. The card is cleared when you send, retry, clear the chat or switch sessions.
- `nanomuse-feed` blocks render as a small "Added to the feed" card with an *Open* button in the conversation where they were written.

### Changed

- `nmAfterTurn` also hands every completed turn to the feed parser; `buildSystemPrompt` appends the USER.md paragraph and, in the feed's session only, the feed protocol and a digest of the memory files and goals (≤ 7 000 characters).
- nanoMuse log categories no longer double the `nanoMuse.` prefix.
- versionCode 6.

### Kept, on purpose

- OpenMinis' memory pages (`GLOBAL.md` + diary) and the soul editor are unchanged; the system files pages open them for the parts they cover. The feed routine is an ordinary scheduled task — pause, edit or delete it like any other.

## [0.1.4] - 2026-09-25 · Guardrails

Before it deletes your files, sends something out or pays, the agent stops and asks — in the shell and in the browser. What you approve can be remembered per chat, or for good per recipient / host / folder. Passwords and verification codes are never typed by the agent; the browser is handed to you instead.

### Added

- **Shell guard** (`io.github.nanomuse.guard.ShellGuard`). Every `shell_execute` command is classified before it runs: *destructive* (`rm` outside scratch dirs, `find -delete`, `shred`, `truncate`, `git reset --hard` / `clean -f` / `checkout --` / `branch -D`, `gh repo delete`…), *outbound* (`git push`, `curl`/`wget` with a body or a writing method, `ssh`/`scp`/`rsync`/`nc`, mail clients, `lark-cli` write verbs, `gh` writes, cloud CLIs, package publishing, anything named like a sender), *money* (an outbound command that mentions paying, ordering, transferring…), *install* (`apk`/`apt`/`pip`/`npm i`/`cargo install`…) and *safe*. Pipelines, `&&`/`;` chains, `sudo`/`env`/`nohup` wrappers, heredocs and inline `sh -c` / `python -c` scripts are judged part by part; deleting under `/tmp`, `/var/tmp`, `/dev/shm` is free. Each classification carries an *object*: the folder (`/var/minis/workspace`, `/var/minis/shared`, or the first two path components), the host, the remote, the chat id, the recipient.
- **Approval card** (`RiskApprovalHost`, `RiskApprovalCard`). Destructive, outbound and money commands suspend the tool call and slide a card in above the composer, Muse's way: icon, "Allow Spark to delete in the workspace?", one line of what it means, the command in a grey preview box, and the buttons *Allow once* · *Allow for this chat* · *Always allow for the workspace* · *Deny*. The chat behind it dims; the header status reads *Needs approval*. Alarming shapes — wiping a whole tree, `dd`/`mkfs`, `curl | sh`, `chmod 777`, force push, fork bombs — get a warning card with only *Allow once* and *Deny*. Payments are asked about every time; there are no remembered approvals for money. Three minutes without an answer count as a denial.
- **Remembered approvals** (`Grants`, `minis-global/nanomuse/grants.json`). *Allow for this chat* covers the same class for the rest of that conversation and is dropped when the chat is cleared or deleted; *Always allow* is persisted per class + object. Settings → Permissions gets a *nanoMuse remembered approvals* section listing each standing grant with its date; tapping one revokes it.
- **Browser guard** (`BrowserGuard`). Before `browser_use` clicks or types, the target element is described in-page. A tap whose text or label reads like paying, ordering, sending, deleting, publishing or confirming a purchase asks first — the card shows the button text and the page URL, and *Always allow* binds to the host. Typing into a password field, a one-time-code field (`autocomplete`, name, id, placeholder, label, a numeric 4–8 digit code box, CVV) is refused outright: the tool result tells the model the field is the user's to fill, and the in-app browser is brought to the front on that page.
- **Background approvals.** If the app is in the background when a card is pending, a high-priority notification carries the same title and description with *Allow once* and *Deny* actions; tapping it opens that chat. The notification is cancelled when the card is answered from anywhere.
- **Policy paragraph in the system prompt** (`RiskPolicy`): what the app stops for, that the model should not ask twice, that a denial must not be retried or routed around, that passwords and codes are never typed, and that installs run with a one-line mention afterwards.
- 23 unit tests for the shell and browser classifiers (`app/src/test/java/io/github/nanomuse/guard`).

### Changed

- `executeShellCommand` runs the gate first; a denied command returns the denial to the model as the tool result and marks the tool card failed. Installs run without asking and append a one-line notice to the result.
- versionCode 5.

### Kept, on purpose

- OpenMinis' own confirmation for `minis-config` settings changes (`ConfigConfirmationGate`) and its per-category tool permissions are untouched; nanoMuse's grants sit above them on the Permissions page.

## [0.1.3] - 2026-09-25 · Home

The app opens on a conversation, not a list. One main chat with the face at the top, side chats in a drawer, and a bottom bar with Ideas, Goals and Library — the shape of Muse on a phone. Everything OpenMinis had is still there; it is reached from these pages instead of the old session list.

### Added

- **Home.** In compact windows the start route renders `NanoMuseHome`: a four-tab shell (chat, ideas, goals, library) whose chat pane stays composed under the other tabs, so switching tabs keeps the scroll position, the composer draft and a running stream. Tablet and landscape widths keep OpenMinis' two-pane scaffold unchanged. Deep links and notifications still open a full-screen chat on top.
- **Main chat.** The first session becomes the main chat and is remembered (`nanomuse` prefs); it is what the app opens on and what the chat tab returns to. Its header is Muse's: the face on a pale disc, the name pill hanging off its chin, a round menu button on the left and a round ⋯ on the right. Side chats get the compact header — title, menu, ⋯ — and take their title from the first exchange, as before.
- **The drawer.** Agent name, "Main chat", the side-chat list with search, an archive glyph that opens the full session list (OpenMinis' `SessionListScreen`, now at `nanomuse/all_chats`, handing the pick back to Home), settings, compose. Long-press a side chat to make it the main chat.
- **Goals.** A page with *Tracking* (goals with a checkbox, the latest note, cadence, next check and progress; ⋯ for open conversation / check now / pause / delete), *Routines* (OpenMinis' scheduled tasks — switch, schedule summary, run now, run records, editor, "All routines"), and *Create a goal* with seven categories. Creating one is a conversation: the sheet's "Let's go" sends an opener to the main chat with a two-turn system addendum; the model asks its questions and ends with a fenced ` ```nanomuse-goal ` block that the app turns into a goal card and a `goals.json` entry. Each goal gets its own session and a hidden interval `ScheduledTask` (`hidden`, `goalId`, `intervalMinutes` added to the model) that appends a one-line check to that session; the goal's context and the reporting protocol travel in that session's system prompt, and the model's ` ```nanomuse-goal-update ` block becomes a progress card and updates the row.
- **Ideas.** Twenty-four starters in six sections from `assets/nanomuse/ideas.{zh,en}.json`: emoji, pitch, what it does, and a sheet with one primary action — send to chat, create a routine (prefilled scheduled task, editor opens), or start a goal in a category.
- **Library.** *Artifacts* and *Media* segments listing what the agent wrote under `minis-sessions/*/workspace` and `minis-global/shared`, newest first, with type icons and image thumbnails, the conversation it came from, preview through OpenMinis' file preview, share via the file provider; ⋯ opens shared folders and the main chat's files.
- `nanomuse-*` fenced blocks render as cards in both the streaming and the static Markdown renderers.

### Changed

- The first-conversation and goal hooks now also run after *retry*, *resume* and queued prompts, not only after a plain send.
- The scheduled-task list hides goal checks; they are managed from the Goals page.
- Muse neutrals for nanoMuse pages (`MuseTones`): white surfaces, a warm disc under the face, grey fills — OpenMinis' iOS-grouped scheme is left as it is for its own screens.
- versionCode 4.

### Kept, on purpose

- Session list, scheduled tasks and their editor, shared folders, file browser and preview, terminal, model groups and every settings page are unchanged and reachable from the new pages.

## [0.1.2] - 2026-09-25 · Identity

The agent gets a face and a name, and the first conversation is where you meet it — the shape of Muse's first run, on top of OpenMinis's setup cards, which are unchanged.

### Added

- **The red panda in the chat header.** Above the name, 36 dp, drawn from the same shapes as the logo (`scripts/gen-avatar.py` derives five VectorDrawables from `web/src/components/redPandaShapes.ts`). Its mood follows the session: idle, working (breathing, narrowed eyes) while the model streams, waiting (round mouth) when an approval, a permission or a config confirmation is pending, happy for three seconds after a turn, error for four after a failure. Tap it — or the name pill under it — to open Settings → Soul (`minis://settings/soul`).
- **Muse's header.** The name sits in a capsule under the face; while the agent works the model rows give way to a status line (the running tool's title, "Thinking…", or "Waiting for you" in the accent colour) and come back when it is idle.
- **The first conversation.** With no sessions yet and the default name still in place, the first chat opens with a scripted greeting, how the agent works and "what should I call you?"; the reply is saved as the user's form of address in `GLOBAL.md` (`## About the user`), the model confirms in one sentence and asks for its own name, and a chooser card appears under that message — two suggestions and "Something else…", the composer's placeholder turning into "Write a name here". A pick or a typed name goes straight into `SOUL.md` (no `minis-config` round-trip, no approval gate); the header, the message labels and the placeholder rename at once, and the model's next reply — one line about the name, three concrete things it can do here, "what first?" — is steered by a system-prompt addendum that exists only for those two turns. The opening and the card are virtual UI rows: never in the database, never in the history a provider sees (Anthropic rejects a transcript that opens with the assistant). The opening is drawn again when the first session is reopened.
- **The name everywhere.** Notifications carry the face as their large icon and the Soul name as sender: the foreground service ("<name> is working"), background results, scheduled tasks, alarms, config confirmations, and the notifications the agent sends itself; the browser banner reads "<name> is browsing". Both happen through `scripts/rebrand.py` (`notification_faces`, the `%1$s` placeholder), so an upstream pull keeps them.
- **CI**: `.github/workflows/android.yml` builds a debug arm64 APK on ubuntu-24.04 for pushes and pull requests that touch the Android tree, and uploads it as an artifact. No signing, no secrets.
- `-Pnm.abi=x86_64` builds a chat-only test APK for the x86_64 emulator (the sandbox payloads are arm64-only).

### Changed

- The chat top bar no longer shows the session title; "Rename chat" moved to the ⋮ menu, and the Appearance switch "Show chat title" is gone (its `minis-config` key remains, inert).
- Copy in nanoMuse's voice for the welcome card, the onboarding subtitle and the service notification (en, zh, zh-TW; other locales keep upstream's wording). The Korean locale had 30 strings still reading "Minis" — `rebrand.py` now catches the particle-suffixed form.
- versionCode 3.

### Kept, on purpose

- The provider list and its OAuth sign-ins (Claude, Codex, Kimi, OpenRouter) and the three setup cards stay as in OpenMinis 1.13; there are no vendor presets yet.

## [0.1.1] - 2026-09-25 · Foundation

The first version of the Android line: [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 as nanoMuse, functionally identical to upstream. Pre-release; arm64 APK signed with the project key that every later version will use.

### Changed

- **The app is OpenMinis 1.13, imported with `git subtree` under `android/`** (unsquashed, 38 upstream commits in the history). The iOS half, the iSH submodule and iOS-only scripts are removed; `deps/proot` is a submodule pointing at our fork [nano-muse/proot](https://github.com/nano-muse/proot), whose `loader-info.awk` no longer needs gawk.
- **Identity**: application id `io.github.nanomuse.app` (the Kotlin package stays `com.openminis.app` for upstream merges), name nanoMuse in all 17 locales and in every user-facing string, the agent's default name and 🐾 header, the one-stroke N as adaptive launcher icon (white tile, brand gradient; a dark skin; Android 13 themed-icon layer; a flat status-bar mark for notifications), the brand blue `#015CFB` / `#58A6FF` instead of iOS blue and the teal Material scheme, one accent hue in chat (links, thinking, inline code, blockquotes, the send button, the user bubble).
- **Where things point**: update check on `nano-muse/nanoMuse` releases; About shows the licence, "Based on OpenMinis 1.13" and the Meta trademark note; Feedback opens a pre-filled GitHub issue form; the privacy policy is [docs/privacy.md](docs/privacy.md). The Telegram group and the mailbox are gone.
- **Licence**: the repository is GPL-3.0-or-later ([NOTICE](NOTICE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)); contributions need a DCO sign-off.
- **Build**: `scripts/rebrand.py` and `scripts/gen-android-icons.py` are idempotent and re-run after every upstream pull; `scripts/android/build-natives.sh` builds proot, the Alpine root file system and `rclone.aar`; `scripts/release-apk.sh <version>` builds, signs (`android/keystore.properties`, debug key otherwise), names and publishes. JDK 21, SDK CMake 3.22.1, NDK r27c, Go 1.26.

### Frozen

- The Python line (`nanomuse/`, `web/`, `demo/`, `site/`) at tag `pre-openminis`, the base of the web and desktop phases. Its unreleased changes below stay as the record of what it does.

## [Unreleased]

The first release: an open-source personal AI agent inspired by Meta's Muse. One agent that does the work while a Sentinel decides what may run; it reaches a service through its API, an MCP server, a command-line tool, a browser or — with the *Phone* switch on — the screen of the app on your phone. This release is the first phase of the plan: the phone, with the agent on your own machine and no cloud VM; the web on a per-user VM and the desktop come after ([docs/roadmap.md](docs/roadmap.md)).

### The agent

- **Tools**: web search (DuckDuckGo out of the box; Brave, Tavily or a SearXNG instance with a key or URL), web pages, files and pages in a workspace, shell and Python (each call in its own [bubblewrap](https://github.com/containers/bubblewrap) sandbox on Linux), mail, a browser view with take-over, calendar and contacts connectors, any [MCP](https://modelcontextprotocol.io) server.
- **Memory** you can read, edit and forget; recall by keyword and, with any OpenAI-compatible `/embeddings`, by meaning; a tidy-up with undo.
- **Goals** worked on over weeks while the app is closed, with check-ins on a schedule; **reminders and routines**; **triggers** that start work when mail arrives, an event is near or a webhook fires.
- **Skills** in the [Agent Skills](https://agentskills.io) format (`SKILL.md` folders), eleven built in — among them five for Chinese services that need no screen: `feishu` (飞书 through the official lark-cli: agenda, messages, events, tasks, documents), `tencent-meeting` (腾讯会议 through Tencent's tmeet CLI: meetings, invitations, recordings and minutes), `amap` (高德地图 through its MCP server: places, routes, distance, weather), `kuaidi100` (parcels through the 快递100 MCP server) and `train-tickets` (trains through the community 12306 MCP server — timetable, seats, prices, connections; booking on the phone's screen only when told to). [docs/services.md](docs/services.md) lists what has been run inside the phone's root file system, what has not, and what we will not recommend.
- **MCP servers** take `{{vault:NAME}}` placeholders in `url`, `args` and `env`, resolved at connect time; a call with no arguments sends an empty object (servers built on zod reject a missing one); the **sandbox** has `share` / `share_read_only` so a CLI and its login can be brought into the box (mirrored under the box's `$HOME`) while the rest of home stays out.
- **A feed** written for you from what the agent knows and what you asked it to follow; **ideas**; a **library** of everything it made.
- **Any OpenAI-compatible model**: Chat Completions or the Responses API, streaming, native or prompt-based tool calling; 阿里云百炼, OpenAI, OpenRouter, Ollama, vLLM, a gateway with its own headers. Pictures attached in chat go to models that take images.

### Sentinel

- The agent never touches a tool directly. A policy decides **allow / ask / deny** per call — by risk level, by rules you write, by taint (private data read earlier holds later egress to stricter rules) — and every decision lands in an audit log.
- **Approvals you scope**: once, this task, always; revocable from the app. Sends and payments on the phone are only ever *once*.
- A **credential vault**: secrets referenced as `{{vault:NAME}}` reach the tool, never the model.

### The phone

- **Operating the phone** (`[gui]`, off by default; *Connections → Phone*; `NANOMUSE_GUI_*`). Three tools when it is on: `phone_screen` (the screen as a picture with a caption), `phone_act` (one action by position, with a `label` saying what is under the finger), `phone_task` (a goal for the *phone operator*).
- **The operator** is a port of the `mobile_use` loop from [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench) (MIT): one screenshot per step, coordinates on a 999×999 grid, `Thought` / `Action` / one tool call, the history as one sentence per step, temperature 0. It never types passwords or codes and never confirms a payment it was not told to make; it asks instead. It works from the picture — no per-app integration — so it works in any app; a device that has an accessibility tree (the Android app) sends the elements along as a second input, for small text and for knowing a password field when it sees one.
- **The ladder**: the screen is the fourth rung, after a skill / CLI / MCP server, a fetch with the user's login, and the in-app browser. The system prompt says so, the agent announces a phone step before it takes it and asks first when it is climbing on its own; a skill declares its rung with `channel:` in `SKILL.md` (`api`, `cli`, `web`, `browser`, `gui`, `mixed`) and a `gui` skill is marked *on the phone's screen* in the agent's index; every audited tool call records its `channel`, and the Activity view shows how many of a session's steps were on the screen.
- **Sentinel on the screen**: reading a screen taints the session; a tap whose label names 确认支付, 转账, 提交订单, 发送, 删除 … (`sensitive_words`) or a step that types and submits at once is SENSITIVE with a warning and asks, once.
- **Traces**: every phone task is a JSONL file under `<data_dir>/phone-traces/`; `nanomuse phone traces` lists them, `nanomuse phone trace <id> -o trace.html` renders one with every screen and every tap drawn on it.
- **Devices**: a phone connects over the app's WebSocket, announces its apps and screen size, answers `screen` and `act`; the protocol and the finger-overlay spec are documented for other executors. The first device is the [MobileGym](https://github.com/Purewhiter/mobilegym) simulated phone: in-page screenshots, a ripple for every tap, a caption saying what Muse is doing.
- **Android operates its own screen** (Android 11+): the app's accessibility service takes the screenshot (downscaled to 720 px wide, taps scaled back), performs the gestures, presses Back / Home / Recents, opens apps, types through `ACTION_SET_TEXT` or the clipboard and refuses password fields outright; it sends the element tree with every screen. While a task runs a **capsule** sits over the operated app — the red panda, the current step and a **Stop** button; one tap ends the action in flight (`nanomuse:stop`), the operator finishes with `stopped` and the agent asks what to do instead of carrying on. When the agent needs you the capsule grows into a card with the question and *Open*. The finger is drawn as in the spec (rings, lines, typed text, caption) on a layer the screenshot never sees. *Connections → Phone → This phone* shows whether the service is on, opens the Accessibility settings, and explains Android 13's *Restricted setting* and the service being switched off by the system.

### The apps

- **The web app** (`nanomuse serve`): Chat, Feed, Ideas, Goals, Library, Connections, Permissions, Activity; approval cards and questions as they happen; artifacts with previews; push notifications with the app closed; English and 简体中文.
- **First run and identity**: setup is a three-item checklist — meet your nanoMuse, add a model, connect mail / calendar / contacts (optional) — with *Start* locked until a model is saved and the ticks kept across a reload. The name comes first (1–20 characters, six suggestions, empty means nanoMuse), then the avatar, a tagline, a tone (formal / casual / playful / concise), how much it says (short / detailed / bullet points), anything else in your own words, and what it calls you; each is its own paragraph of the system prompt. The name runs through the app, the approval and permission copy, Settings, the CLI banner and the MobileGym bridge. The model form groups providers by protocol with vendor subtitles — DeepSeek, Kimi, Qwen, GLM, 豆包, MiniMax, OpenAI (Chat Completions and Responses), OpenRouter, Ollama, any OpenAI-compatible endpoint — with a masked key, a *Get a key* link per vendor, `/v1` added to a bare host, no key for local endpoints, and the endpoint's own model list (`POST /api/llm/models`, catalogue fallback, a typed model never replaced). Bring your own key; there is no account with us and no OAuth login.
- **The red panda**: the agent's face is an SVG drawn live that changes pose with its state — idle (breathing, blinking, glancing about), working (typing at a laptop), waiting for you (a raised paw and a "!"), done (a bounce), failed (a shake), offline (asleep). Drawn simplified with soft 2.5D shading above 28 px and flat below (three levels of detail from one geometry, `redPandaShapes.ts`), it is also the logo: the web icon, the README cover, the Android launcher (flat, with a monochrome silhouette for themed icons and the status bar) and the launcher icon of the MobileGym app — all generated, none drawn twice. Six plush dolls and an emoji remain as alternatives.
- **The Android app**, two flavours. `nanomuse.apk` runs nanoMuse **on the phone itself**: a small Alpine Linux with Python, `nanomuse` and Node inside the APK (under 70 MB compressed), unpacked on first start and run under [PRoot](https://github.com/termux/proot) — a user-mode chroot, no root — with the WebView on `127.0.0.1`. A foreground service starts it, restarts it, holds a wake lock only while a task runs, and comes back after a reboot; your data lives outside the root file system and survives updates. `nanomuse-connect.apk` is the remote for a server on your computer: scan the QR code `nanomuse serve` prints, then the same app in a WebView with notifications. Both signed on every release ([docs/local-runtime.md](docs/local-runtime.md), [docs/android.md](docs/android.md)).
- **Keeping it running**: the scheduler and the phone share the schedule. The Python side knows the earliest moment anything is due (`next_wake_at` in `/api/upcoming`, a `schedule` event when it changes) and the local runtime sets one alarm for it — exact when Android allows it, inexact when it does not (Android 14 denies exact alarms to a fresh install), and `POST /api/tick` when it fires. *Settings → Keep it running* shows the battery, overlay and exact-alarm state with a button to Android's own page for each, a *Start after a reboot* switch, and the extra step vendor Android needs (小米, 华为 / 荣耀, OPPO, vivo, 三星, 魅族 — with a shortcut to the auto-start page). Crashes are written to a file on the phone and nowhere else; *Export logs* zips them with the app's recent logcat and the runtime's log for the share sheet.
- **The browser, on either side**: one browser tool with two backends — Chromium through Playwright on the server, with a persistent profile so logins survive a restart, or the phone's own WebView inside the app, offscreen on a private virtual display so pages run at full speed while the app is in the background. Same actions, same numbered elements, same frames in the chat; `mobile` / `desktop` / custom profiles; a `fetch` action that carries the browser's cookies for logged-in requests without a page. *Take over* in the app slides the real page up as a sheet (no reload), **Done** hands it back. A `wait` action for pages that draw themselves after `load`; the browser's own profile files never show up as artifacts. The device protocol is documented for other executors ([docs/browser.md](docs/browser.md)).
- **The phone's own capabilities** ([docs/device.md](docs/device.md)): on the phone the app runs a small MCP server on `127.0.0.1` that `nanomuse serve` picks up as the server `device` with no configuration — clipboard (read only while on screen, as Android has it), notifications, calendars (read, create, update, delete), contacts (read-only), location, alarms and timers through the clock app, photos through the system Photo Picker only. Each tool has its own Sentinel default (`DEVICE_TOOLS`); MCP servers in general take per-tool `tools.<name>` overrides now. Every permission is Android's own dialog — shown at once when the app is on screen, through a notification to tap when it is not — and the model is told whether the user declined or nobody answered. Reading notifications is not offered.
- **The workspace in the Files app** (local build): a `DocumentsProvider` shows the agent's workspace as a root in the system Files app and in open/save dialogs. **Share into nanoMuse**: text, links and files from any app's share sheet become a new conversation with the files uploaded and the text as a draft, waiting for what to do with them.
- **The CLI bridge**: inside the phone's sandbox, `nanomuse-device`, `nanomuse-browser` and `nanomuse-open` let any shell command or script use the phone's capabilities and the in-app browser through the server (`/api/bridge/*`) with a one-command token — as nested tool calls under the same Sentinel, on the same timeline. `nanomuse-open` is the box's `BROWSER`. The Python side knows when it runs on a phone (`nanomuse.runtime`) and describes its sandbox honestly.
- **The showcase** (`demo/showcase/`): a gateway that starts a private nanoMuse per visitor next to the simulated phone, with metered model access and bring-your-own-key; images published from CI.
- **Website**: `site/`, one static page in English and 中文 with the red panda playing a task end to end, published to GitHub Pages from `.github/workflows/pages.yml`.
- **The film**: a 66-second promo (`site/media/nanomuse-promo.mp4`) rendered frame by frame from `site/promo/storyboard.html` with Playwright and ffmpeg — the same markup and mascot as the app, so it can be re-cut by editing HTML.

### Command line

`nanomuse chat`, `run`, `serve`, `daemon`, `goals`, `reminders`, `triggers`, `calendar`, `contacts`, `skills`, `memory`, `vault`, `phone`, `audit`, `config`, `doctor`.
