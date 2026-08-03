# Changelog

All notable changes to OpenMuse. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/). Unreleased changes are on `main`.

## [Unreleased]

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

### Changed

- Sessions are repaired on load: tool calls that never got a result (the app restarted mid-call) get a placeholder result so providers accept the history; stale approval and question cards are marked expired.
- The web app no longer flashes the empty-chat prompts before the thread's history has loaded.
- Feed previews strip Markdown.

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

[Unreleased]: https://github.com/OpenMuseAgent/OpenMuse/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OpenMuseAgent/OpenMuse/releases/tag/v0.1.0
