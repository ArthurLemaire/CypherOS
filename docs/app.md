# The app

`openmuse serve` runs an always-on agent and serves the phone app from the same process. The app is a React single-page app built into `openmuse/server/static/` and shipped inside the Python package; the server is FastAPI with a WebSocket for live events.

```bash
openmuse serve                      # http://127.0.0.1:8787, this machine only
openmuse serve --host 0.0.0.0       # also reachable from your phone on the same network
openmuse serve --port 9000 --no-qr
```

<p align="center">
  <img src="screenshots/chat-research.png" width="19%" alt="Research">
  <img src="screenshots/chat-approval.png" width="19%" alt="Approval">
  <img src="screenshots/goal-detail.png" width="19%" alt="Goal">
  <img src="screenshots/ideas.png" width="19%" alt="Ideas">
  <img src="screenshots/memory.png" width="19%" alt="Memory">
</p>

## Getting it onto your phone

1. Start with `--host 0.0.0.0` (or set `server.host`). The terminal prints a URL and a QR code.
2. Scan the code. The URL contains the access token (`?token=…`); the app stores it and drops it from the address bar.
3. In the browser menu choose *Add to Home Screen*. The app has a manifest and icons, so it opens full-screen like a native app.

The token is generated once and stored in `<data_dir>/server_token`; set `server.token` or `OPENMUSE_SERVER_TOKEN` to choose your own. Keep `server.auth = true` on any network you do not fully control. To reach the app from outside your network, put it behind something you trust (Tailscale, a reverse proxy with TLS) rather than opening the port.

## First run

On a fresh data directory the app opens with setup instead of the chat: your name; the agent's name, avatar, colour and style; the model (pick a provider, paste a key — it goes into the vault on the server and the model never sees it; or keep what `config.toml` already says); optionally your mailbox; then a few things to try. *Skip setup* at any point. Everything here can be changed later under the avatar. Setup does not reappear once finished, or once a conversation exists.

## What is on the screen

Five tabs — Chat, Feed, Ideas, Goals, Library — and a menu behind the avatar.

**Chat.** One main conversation plus side chats (the *Chats* button top right). Messages stream in as they are generated. Tool calls appear as chips: tap one for the arguments and output. Files the agent writes show up as artifact cards that open in the app. When Sentinel needs a decision an approval card appears; when the agent needs information a question card appears. The composer stays open while the agent works; anything you send is folded into the running turn before the next model call.

**Feed.** What happened without you asking: one entry per background pass (its final word, and any file it made), plus every approval or question still waiting for you, in any chat. A *Next up* card says when the next pass runs and which goal is in line. Unseen entries are counted on the tab.

**Ideas.** Five suggestions generated from your goals, memory and recent conversation. Tap one to send it as a message; *Refresh* regenerates.

**Goals.** Goals created by the agent or by you (the `+` button), filed under an area of life — health, finance, career, learning, relationships, family, home, travel, creative — with an optional target date and an optional check-in cadence. Filter chips at the top show one area at a time. Each goal has a plan; steps are pending, in progress, done or blocked, with notes. *Work on it now* runs one background pass on that goal and posts the result to the main chat; *Check in with me now* sends the reminder message right away.

- *Target date.* Cards say "Due in 5 days" / "Was due Sep 12"; overdue goals go first when the background pass picks what to work on, and the agent is told about them.
- *Check-ins.* "Every day at 08:00", "Weekdays at 07:30", "Mondays at 09:00", "Monthly on the 1st": at that time the agent sends one short message — what the goal is about, what the next small step is, how is it going — and does no work. Check-ins arrive at any proactivity level (you asked for them) but wait out quiet hours. The *Upcoming* view lists the next ones.
- *Plan changes.* When the agent learns the plan no longer fits, it does not edit it; it proposes a revised set of remaining steps with a reason. The proposal shows as a card at the top of Goals and inside the goal — *Use Muse's plan* keeps the finished steps and swaps the rest, *Keep my plan* leaves everything as it is. Either way a note lands on the goal.

**Library.** Every file in the agent's workspace, newest first, filtered by kind (pages, documents, images, data, code) and searchable. Files open in the app: pages render live, Markdown is formatted, CSV becomes a table, images and PDFs display inline. A page the agent wrote runs in a sandboxed frame with an opaque origin — it cannot read the access token or call the API — and the server sends `Content-Security-Policy: sandbox` with every HTML file for the same reason.

**Avatar.** The dot shows the state (idle, working, waiting for you); a badge counts approvals waiting anywhere. Tap it for the menu:

- *Approvals* — the queue of cards waiting for you across all chats, answerable right there. Opens first when something is pending.
- *Activity* — the audit trail: every tool call, decision and approval, including refused ones.
- *Permissions* — the Sentinel mode, and every standing permission you granted with a revoke button on each.
- *Upcoming* — the background-work switch, the next pass time, and the goals in line with a *run now* button.
- *Memory* — everything the agent has remembered about you, by category, plus an entry box. *Forget* deletes an item; the agent will not see it again.
- *Connections* — what the agent can reach, plugged in and out from the phone. **Model**: provider presets (DeepSeek, OpenAI, OpenRouter, Ollama, any OpenAI-compatible endpoint), model name, tool-calling mode, and the API key — which is written to the vault as `LLM_API_KEY` and swapped in for every thread on the spot; *Test* asks the model for a one-word reply. **Email**: presets for common providers, address and app password (vault: `EMAIL_ADDRESS`, `EMAIL_PASSWORD`), IMAP/SMTP servers; *Connect* saves and signs in to both servers to prove it works; *Disconnect* removes the credentials and the tools. **Browser**: on/off, with the install hint when Playwright is missing. **MCP servers**: add a server by command (stdio) or URL, choose the risk level of its tools, remove it again; servers from `config.toml` are listed read-only. **Vault**: the names of every stored secret, add or delete one. Only names ever leave the server.
- *Settings* — the agent's name, avatar, colour and personality, and what it calls you; the Sentinel mode (Balanced = `ask`, Cautious = `strict`, Hands-off = `auto`); proactivity (the Off / Low / Default / High dial, the check-in interval, quiet hours — see [Background work](#background-work)); *show thinking*; reply language.

Non-secret choices made in Connections are stored in `<data_dir>/app-settings.json` and layered over `config.toml` on every start — for the CLI too — so a phone-only setup never needs a file edited. Secrets are only ever referenced from there as `{{vault:NAME}}`.

## Background work

Muse "does things on its own, but not too much". The *Proactivity* dial in Settings sets how much:

| Level | Passes | Reaches out |
|---|---|---|
| Off | never | — |
| Low | every 2 × interval | only when a step got finished or it needs you |
| Default | every interval | when there is real progress or something you would want to know |
| High | every ½ interval | always, including "still on track" |

On each pass the service picks one active goal with a pending step, runs it in the main chat with the Sentinel in `auto` mode (explicit deny rules and dangerous-call warnings still apply — those turn into cards in the Feed), and lets the model decide whether the result is worth your attention. A pass with nothing to say begins its summary with `[quiet]`: the chat shows one muted line ("Checked on *goal* — nothing new", tap to expand), the Feed lists it as a one-liner, and nothing is badged. Anything else is a normal message from your Muse.

*Quiet hours* ("22:00–08:00", server local time) hold background work; a pass that would fall inside the window runs when it ends. The *Upcoming* view and the Feed's *Next up* card show the level, the effective interval and the next pass time, or the end of the current quiet window.

Turn the dial to Off for goals that need your judgement at every step, or leave those goals paused.

## API

Everything the app does goes through this API, so another front-end (a Telegram bot, a desktop widget) can drive the same agent. All requests need `Authorization: Bearer <token>` or `?token=` unless `server.auth = false`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness, version |
| GET | `/api/state` | profile, status, threads, pending approvals, goals, settings |
| GET / POST | `/api/threads` | list threads / create one `{title}` |
| PATCH / DELETE | `/api/threads/{id}` | rename / delete |
| POST | `/api/threads/{id}/clear` | clear the conversation |
| GET | `/api/threads/{id}/events?limit=&before=` | timeline events |
| POST | `/api/threads/{id}/send` `{text}` | queue a message; returns immediately |
| POST | `/api/approvals/{id}` `{approved, scope, reason}` | answer a card; `scope` is one of the card's `grant_options` (`once`, `task`, `session`, `24h`, `always`) |
| DELETE | `/api/approvals` | forget every granted permission |
| DELETE | `/api/approvals/grants/{key}` | revoke one permission (`key` as listed by `/api/activity`, e.g. `shell:git`) |
| GET / POST | `/api/goals[?status=&category=]` | list / create `{title, description, steps[], category, due (YYYY-MM-DD), check_in ("daily 08:00", "weekdays 07:30", "weekly mon 09:00", "monthly 1 09:00")}` |
| GET / PATCH / DELETE | `/api/goals/{id}` | read / update `{status, note, step_index (1-based), step_status, step_note, title, description, category, due, check_in}` (`""` clears due / check_in) / delete |
| POST | `/api/goals/{id}/steps` `{title}` | add a step |
| POST | `/api/goals/{id}/advance` | run one background pass now |
| POST | `/api/goals/{id}/check-in` | send the reminder message now |
| POST / DELETE | `/api/goals/{id}/proposal/accept`, `/api/goals/{id}/proposal` | accept / dismiss the agent's proposed plan change |
| GET / POST | `/api/memory` · DELETE `/api/memory/{id}` | list / add `{content, category}` / forget |
| GET | `/api/ideas?refresh=1` | cached or regenerated suggestions |
| GET | `/api/activity` | audit tail, granted permissions (`grants[]` with `key`, `tool`, `target`, `scope`, `expires_at`), taint flag |
| GET | `/api/feed?limit=` | the Feed: `{id, ts, kind (background · artifact · approval · question), title, text, thread, thread_title, path}` newest first |
| GET | `/api/upcoming` | `{proactivity, proactive, interval_minutes, effective_interval_minutes, quiet_hours, quiet_until, next_pass_at, queue[{goal_id, title, category, due, overdue, next_step, progress}], check_ins[{goal_id, title, at, cadence}], busy}` |
| GET | `/api/files` · `/api/files/{path}?download=1` | list / read workspace files (HTML and SVG are served with `Content-Security-Policy: sandbox`) |
| GET / PUT | `/api/settings` | view / change `{profile{name, emoji, color, style, user_name, proactive, goal_interval_minutes}, sentinel_mode, show_thinking, language}`; the view includes `onboarded` and `llm_ready` |
| GET | `/api/connections` | model (`key_source`: vault · config · missing · none), provider presets, email, browser, MCP servers (`connected`, `tools`, `from_app`), vault names, `onboarded` |
| PUT | `/api/connections/llm` `{provider, model, base_url, tool_mode, api_key}` | change the model; `api_key` set → stored in the vault, `""` → no key, omitted → unchanged. Takes effect immediately in every thread |
| POST | `/api/connections/llm/test` | one short round trip to the model: `{ok, reply, ms}` or `{ok: false, error}` |
| PUT / DELETE | `/api/connections/email` | save `{address, password, imap_host, imap_port, smtp_host, smtp_port, smtp_starttls, enabled}` (address and password go to the vault) / disconnect and forget the credentials |
| POST | `/api/connections/email/test` | sign in to IMAP and SMTP: `{ok, inbox}` or `{ok: false, error}` |
| PUT | `/api/connections/browser` `{enabled}` | turn the browser tool on or off |
| POST · DELETE | `/api/connections/mcp` `{name, command, args[], env{}, url, risk}` · `/api/connections/mcp/{name}` | connect a server now (502 if it does not come up) / disconnect and remove one added from the app |
| GET · PUT · DELETE | `/api/vault` · `/api/vault/{name}` `{value}` | list secret names / store / delete. Values are never returned |
| POST | `/api/onboarded` `{done}` | mark first-run setup as finished |
| WS | `/ws?token=` | live events |

### WebSocket

On connect the server sends `{"kind": "hello", "state": …}` (the same payload as `/api/state`). Then:

| Server → client | Meaning |
|---|---|
| `event` | a new timeline event (`user`, `assistant`, `tool`, `approval`, `question`, `artifact`, `notice`). An `approval` carries `summary`, `purpose` (what you asked for), `target`, `grant_key`, `grant_options`, `risk`, `warnings`, `args`. Events produced during a background pass carry `source: "background"` and `about` (the pass label) |
| `update` | fields changed on an existing event (a tool finished, an approval was decided) |
| `stream_start` / `delta` / `stream_end` | the assistant reply being generated |
| `status` | idle / working / waiting, with a short detail line |
| `thread`, `thread_cleared`, `thread_deleted` | thread list changes |
| `goals`, `memory`, `ideas`, `profile`, `settings`, `connections`, `approvals_reset` | refresh hints for the tabs |
| `error`, `pong` | replies to client messages |

Client → server: `{"kind": "send", "thread": "main", "text": "…"}`, `{"kind": "approval", "id": "…", "approved": true, "scope": "once"}`, `{"kind": "ping"}`.

Timeline events are persisted per thread in `<data_dir>/threads/<id>.json`, so the history survives restarts.

## Developing the front-end

```bash
cd web && npm install
npm run dev          # Vite on http://localhost:5173, proxied to the server on 8787
npm run build        # writes openmuse/server/static/ — commit the result
```

Add `cors_origins = ["http://localhost:5173"]` to `[server]` while using the dev server. The app is plain React + TypeScript + Tailwind with no state library; `web/src/store.tsx` holds the reducer and the WebSocket client, `web/src/screens/` one file per tab.
