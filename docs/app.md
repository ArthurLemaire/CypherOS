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

## What is on the screen

Five tabs — Chat, Feed, Ideas, Goals, Library — and a menu behind the avatar.

**Chat.** One main conversation plus side chats (the *Chats* button top right). Messages stream in as they are generated. Tool calls appear as chips: tap one for the arguments and output. Files the agent writes show up as artifact cards that open in the app. When Sentinel needs a decision an approval card appears; when the agent needs information a question card appears. The composer stays open while the agent works; anything you send is folded into the running turn before the next model call.

**Feed.** What happened without you asking: one entry per background pass (its final word, and any file it made), plus every approval or question still waiting for you, in any chat. A *Next up* card says when the next pass runs and which goal is in line. Unseen entries are counted on the tab.

**Ideas.** Five suggestions generated from your goals, memory and recent conversation. Tap one to send it as a message; *Refresh* regenerates.

**Goals.** Goals created by the agent or by you (the `+` button). Each has a plan; steps are pending, in progress, done or blocked, with notes. *Work on it now* runs one background pass on that goal and posts the result to the main chat.

**Library.** Every file in the agent's workspace, newest first, filtered by kind (pages, documents, images, data, code) and searchable. Files open in the app: pages render live, Markdown is formatted, CSV becomes a table, images and PDFs display inline. A page the agent wrote runs in a sandboxed frame with an opaque origin — it cannot read the access token or call the API — and the server sends `Content-Security-Policy: sandbox` with every HTML file for the same reason.

**Avatar.** The dot shows the state (idle, working, waiting for you); a badge counts approvals waiting anywhere. Tap it for the menu:

- *Approvals* — the queue of cards waiting for you across all chats, answerable right there. Opens first when something is pending.
- *Activity* — the audit trail: every tool call, decision and approval, including refused ones.
- *Permissions* — the Sentinel mode, and every standing permission you granted with a revoke button on each.
- *Upcoming* — the background-work switch, the next pass time, and the goals in line with a *run now* button.
- *Memory* — everything the agent has remembered about you, by category, plus an entry box. *Forget* deletes an item; the agent will not see it again.
- *Settings* — the agent's name, avatar, colour and personality; the Sentinel mode (Balanced = `ask`, Cautious = `strict`, Hands-off = `auto`); background work (advance one active goal every N minutes while the app is closed); *show thinking*; reply language.

## Background work

With *Keep working on goals while I'm away* on, the service picks one active goal every `goal_interval_minutes`, runs it with Sentinel in `auto` mode in its own thread, and posts a short update to the main chat. Explicit deny rules still apply. Turn it off for goals that need your judgement at every step, or leave those goals paused.

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
| GET / POST | `/api/goals` | list / create `{title, description, steps[]}` |
| GET / PATCH / DELETE | `/api/goals/{id}` | read / update `{status, note, step_index (1-based), step_status, step_note}` / delete |
| POST | `/api/goals/{id}/steps` `{title}` | add a step |
| POST | `/api/goals/{id}/advance` | run one background pass now |
| GET / POST | `/api/memory` · DELETE `/api/memory/{id}` | list / add `{content, category}` / forget |
| GET | `/api/ideas?refresh=1` | cached or regenerated suggestions |
| GET | `/api/activity` | audit tail, granted permissions (`grants[]` with `key`, `tool`, `target`, `scope`, `expires_at`), taint flag |
| GET | `/api/feed?limit=` | the Feed: `{id, ts, kind (background · artifact · approval · question), title, text, thread, thread_title, path}` newest first |
| GET | `/api/upcoming` | `{proactive, interval_minutes, next_pass_at, queue[{goal_id, title, next_step, progress}], busy}` |
| GET | `/api/files` · `/api/files/{path}?download=1` | list / read workspace files (HTML and SVG are served with `Content-Security-Policy: sandbox`) |
| GET / PUT | `/api/settings` | view / change `{profile, sentinel_mode, show_thinking, language}` |
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
| `goals`, `memory`, `ideas`, `profile`, `settings`, `approvals_reset` | refresh hints for the tabs |
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
