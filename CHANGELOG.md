# Changelog

All notable changes to OpenMuse. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/). Unreleased changes are on `main`.

## [Unreleased]

### Added

- **Calendar connector.** Any calendar with a private iCalendar link — Google, Outlook, iCloud, Fastmail, Nextcloud — or an `.ics` file on disk, added from *Connections → Calendar* (the screen says where each provider hides the link) or `openmuse calendar add NAME URL`; the link is kept in the vault. Feeds are read on the spot and refreshed in the background; recurring events, exceptions and moved instances are expanded per RFC 5545. The agent gets a `calendar` tool — agenda, search, free time inside working hours — and *draft*: an event it proposes is written as an `.ics` file and shown as a card with *Add to calendar*; it never writes to the calendar itself. Today's and tomorrow's events are in the system prompt; the Feed shows them under *Today*. `openmuse calendar agenda | free | feeds | add | remove`; `openmuse doctor` reports the feeds.
- **Memory that stays tidy.** A fact that changed is updated in place (`remember` takes `replaces=<id>`, and a line that says the same thing in other words replaces the old one on its own) instead of piling up next to the old version. A periodic tidy-up — after every eight new lines or weekly, and *Memory → Tidy up* on demand, `openmuse memory tidy [--dry-run]` from the CLI — merges lines that say the same thing, keeps the newer fact when two contradict, and drops one-off requests that were never facts about the user. The model proposes; OpenMuse checks: a merged line may add no words that were not there (checked by character for Chinese), nothing the user wrote themselves is dropped, at most a fifth of the store changes per pass. Every merge, drop and update is logged with the text it replaced — *Memory → Recent changes* and `openmuse memory changes` show them, each with an undo (`memory restore <id>`). A tidy-up that changed something is one line in the Feed and the chat.
- Recall weighs rare words: a word that is in half the memories no longer decides which one is meant.

### Fixed

- A reasoning model that spends the whole `max_tokens` thinking and returns nothing is asked once more with four times the budget — in the agent loop, for Ideas and for the memory tidy-up. The Responses API's "incomplete" is reported as the same `length` finish as the Chat API's.
- A file the agent made is tappable in a reply even when it is named in plain prose ("saved as packing-list.html"), not only in backticks or a link.
- A tool call whose arguments were cut off in transit is shown as such ("files: arguments cut off (4120 chars)") and handed straight back as a failure, instead of appearing as `files. .` and going through Sentinel — where a `files.write` with no path could even ask for approval.
- The 简体中文 app translates the labels the server puts on background work (*Working on your goal*, *Check-in*, *Reminder*, *Routine*, *Tidied memory*) in the Feed and on quiet lines; the memory tidy-up's chat summary is written in 中文 when that is the reply language, or when the memories themselves are.

## [0.2.0] — 2026-09-23

The first release meant for other people's phones: the Muse-style app with Feed, Ideas, Goals and Library, scoped approvals, artifacts, push notifications, a browser view with take-over, reminders and routines, the app in 简体中文, `tool_mode = "auto"` so small local models work, and `openmuse doctor`. Verified end to end with DeepSeek V4.1 Flash and with `qwen3:8b`, `llama3.2:3b` and `gemma3:4b` on Ollama; CI on Linux, macOS and Windows.

### Added

- **Approvals are scoped capabilities.** An approval is bound to a tool and a target (`shell:git`, `send_email:alice@example.com`, `web_fetch:api.github.com`) and lasts once, for this task, this session, 24 hours or always. Cards show the purpose; a Permissions list revokes any grant. Calls with warnings (a `rm -rf`, a `curl | sh`) are never covered by a grant.
- **Muse-style app shell**: Chat · Feed · Ideas · Goals · Library tabs, an avatar menu with Approvals, Activity, Permissions, Upcoming, Memory, Connections and Settings.
- **Artifacts**: the agent is asked to answer with files (HTML pages, Markdown, CSV) when the result has a shape; every file any tool writes shows up as a card that opens in a sandboxed in-app viewer. The Library lists them.
- **Connections** screen and first-run setup: model and API key (straight into the vault), email (IMAP/SMTP), browser, MCP servers; connection tests; `app-settings.json` layered over `config.toml`.
- **Proactivity** dial (Off / Low / Default / High), quiet passes (a background pass with nothing to say is one muted line, not a message) and quiet hours.
- **Goals** with categories, target dates and an overdue flag, check-in reminders (`daily 08:00`, `weekly mon 09:00`, …) delivered as short messages, and plan proposals the agent makes and the user accepts or dismisses instead of silent rewrites.
- Sentinel hardening: subprocesses get a scrubbed environment (no API keys or tokens); `python_execute` reads the code and escalates to SENSITIVE for network, processes, environment access, deletion or paths outside the workspace; `web_fetch` follows redirects itself and refuses hops into private networks; any call with warnings asks even in `auto` mode unless an explicit `allow` rule applies; `agent.extra_roots` for files outside the workspace.
- `SECURITY.md` with the threat model and reporting process; `CODE_OF_CONDUCT.md`; issue and pull request templates; Dependabot.
- CLI: `/permissions`, `/revoke <key>`; `goals add --category/--due/--check-in`, `goals list --category`.
- **Reminders and routines.** "Remind me at six to call mum" and "every weekday at 07:30 summarise my unread mail": a `reminders` tool, an *Upcoming → Reminders & routines* section in the app (add, run now, cancel), `openmuse reminders list | add | cancel`, and `GET/POST /api/reminders`. A reminder is one short message at that time in the chat it was set from; a routine is a background run with tools. A named time is kept whatever the proactivity level or the quiet hours.
- **Web Push notifications and an app badge.** The phone buzzes when your Muse needs an approval, has a question, finished a background pass worth surfacing or it is check-in time — standard Web Push (VAPID) through the browser's own push service, no account with anyone; the icon shows how many cards are waiting. Needs `https://` or `localhost`.
- **Browser view.** When the agent browses, one card per run shows the page after every step, with what just happened ("Clicked 'Sign in'"). Tap it for the full view; *Take over* puts you at the controls (tap to click, type, Enter, open a URL) and *Hand back* returns the page to the agent, which is told what you did. That is how a login happens without a password passing through the model. The `-browser` image tags (`docker build --build-arg WITH_BROWSER=1`) bundle Chromium.
- **A file named in a reply opens on tap.** Inline code and relative links that name a file made in the chat render as a chip that opens the in-app viewer, so "saved it to `kyoto-notes/packing-list.html`" is the link.
- **OpenMuse on a simulated phone**: `demo/mobilegym/` installs OpenMuse as a native app on [MobileGym](https://github.com/Purewhiter/mobilegym), a browser-hosted Android simulator — launcher icon, setup page, and a bridge that turns approvals, questions and background results into notifications in the shade. `docs/demo.gif` shows one real task start to finish.
- `?tab=goals` (feed, ideas, library, connections) opens that tab directly, like `?thread=` opens a chat.
- **The app in 简体中文.** *Settings → App language*: Auto (follows the browser), English or 简体中文, per device; dates and relative times follow. Separate from the agent's reply language. No i18n library: the English text is the key, `web/src/i18n/zh-CN.ts` the translation, and a unit test fails when a string in the app has no translation — adding a language is one dictionary file.
- `openmuse doctor`: config file, data dir, model and key state, tools, connectors and one call to the model on one screen — the thing to run first and to paste into a bug report. `openmuse --version`.
- `tool_mode = "auto"` (the new default): the API's function calling, and when the endpoint rejects the `tools` field — Ollama for a model without a tool template, vLLM without a tool parser — tools are described in the prompt for the rest of the run. Prompt mode also accepts the ```` ```tool_call ```` / ```` ```json ```` fences small models emit instead of the tags.
- `scripts/provider_check.py`: five everyday tasks against any model, one line each; results for Ollama models in `docs/configuration.md`.
- Small-model repairs: a reply that is a bare JSON object naming a tool counts as a tool call in native mode too (Llama 3.x); JSON arguments may contain real newlines; `files.write` turns a one-line text with spelled-out `\n` into lines. `qwen3:8b`, `llama3.2:3b` and `gemma3:4b` all pass the provider check.
- CI runs on Ubuntu (Python 3.11–3.13), macOS and Windows, type-checks with mypy, lints and unit-tests the web app (ESLint, Vitest), and publishes `ghcr.io/openmuseagent/openmuse` for amd64 and arm64.

### Changed

- Sessions are repaired on load: tool calls that never got a result (the app restarted mid-call) get a placeholder result so providers accept the history; stale approval and question cards are marked expired. A tool call whose arguments were cut off in transit stays in the history as `{}` instead of poisoning every later request.
- *For this task* on `shell` covers the tool for the rest of the run, not only the programs in the current command — one decision instead of three for `git clone`, then `ls | wc`, then `sort | head`. Recipients and hosts stay bound; warnings still stop every call.
- A background run is pushed once, after its last word (`final: true` on the timeline event), not once per narration step.
- The system prompt asks the agent to look in the workspace before searching the machine, to quote file contents only from tool output it actually received, and to answer with a file when the result has a shape.
- The web app no longer flashes the empty-chat prompts before the thread's history has loaded; no scrollbar gutters at phone widths; Feed previews strip Markdown.

### Fixed

- Relative paths are POSIX-style on every platform (the same file was `notes/plan.md` on one machine and `notes\plan.md` on another); Windows CI is green.
- `python_execute` no longer stops for approval when the code spells out an absolute path that is inside the workspace.
- Artifacts appear when the workspace lives inside the data directory (`~/.openmuse/workspace`).
- A page written in parts (write, then append) keeps one card and stays "new"; a streamed reply that turned out to be a tool call no longer leaves an empty bubble; a one-line reply delivered through `terminate` right after a text reply is shown again instead of being taken for a repeat.
- A macOS-only test race in the server suite.
- Ideas: one malformed item in the model's list (a missing colon, a real newline in a string, a reply cut off at `max_tokens`) no longer throws the whole list away and shows the starter ideas instead.

## [0.1.0] — 2026-09-22

First public release.

- Agent loop with native and prompt-based tool calling; OpenAI-compatible Chat Completions and Responses providers (DeepSeek, OpenAI, OpenRouter, Ollama, any compatible endpoint); streaming with `<think>` handling.
- Sentinel gatekeeper: risk levels, `strict` / `ask` / `auto` modes, egress allowlists, taint tracking (after private data, new destinations need approval), audit log.
- Credential vault with `{{vault:NAME}}` placeholders; secrets never reach the model.
- Long-term memory and goals in SQLite; `openmuse daemon` / `goals run` keep working on goals in the background.
- Tools: files, shell, Python, web search and fetch, memory, goals, email (IMAP/SMTP), browser (Playwright, optional), MCP servers.
- `openmuse serve`: the always-on server behind the phone app — threads, live WebSocket events, approval cards, questions, artifacts, goals / memory / ideas / settings API, token auth.
- Mobile-first web app built with React, Vite and Tailwind, shipped inside the package.
- Docker image and Compose file; GitHub Actions CI; PyPI publishing through Trusted Publishing.

[Unreleased]: https://github.com/OpenMuseAgent/OpenMuse/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/OpenMuseAgent/OpenMuse/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/OpenMuseAgent/OpenMuse/releases/tag/v0.1.0
