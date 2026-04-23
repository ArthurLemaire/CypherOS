# The phone's own capabilities

On a phone, nanoMuse can reach what is on it: the clipboard, the calendar, the contacts, where the phone is, the clock's alarms and timers, the notification shade, and the photo library through the system picker. This page is about how that works, what each tool may do, what it asks the user, and what it deliberately cannot do.

The rule of the design: **the model gets tools, the user gets Android's own dialogs.** nanoMuse never grants itself anything. Every permission is asked for by the platform's dialog, the photo library is only ever seen through the platform's picker, and alarms are handed to the clock app the user already has. The Python brain does not change to run on a phone; the Kotlin side is a small tool host.

```
 nanomuse serve (Python, in PRoot)                 the app (Kotlin)
 ┌──────────────────────────────┐   HTTP, 127.0.0.1    ┌───────────────────────────────┐
 │ MCP client  ── device__* ────┼──────────────────────►│ McpEndpoint  (Streamable HTTP) │
 │ Sentinel: per-tool defaults  │   Bearer / ?token=    │  DeviceTools: 13 tools         │
 │ nanomuse-device (CLI bridge) │◄──────────────────────┤  Ask: Android's dialogs        │
 └──────────────────────────────┘   SSE + heartbeats    │  DeviceAskActivity (invisible) │
                                                        └───────────────────────────────┘
```

## How the tools reach the model

The app starts an MCP server on `127.0.0.1` (a random port, a random token, both handed to the runtime as `NANOMUSE_HOST_URL` and `NANOMUSE_HOST_TOKEN`). `nanomuse serve` sees them and adds the server as `device` — no configuration, nothing to install — so the tools appear like any other MCP server's, named `device__<tool>` (`device__calendar_list`, `device__clipboard_read` …). The system prompt gets a short *This phone* section listing them, with the ground rules the model has to know: the first use of a capability makes Android ask the user, and the clipboard can only be read while the app is on screen.

The endpoint speaks [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports): `POST /mcp` with JSON-RPC; `tools/call` answers as an SSE stream with a `: keep-alive` line every 8 s, because a call may wait minutes for the user to answer a dialog; `GET /mcp` is `405`; the token is a `Bearer` header or `?token=`; the `Mcp-Session-Id` header is issued on `initialize` and the client's `protocolVersion` is echoed back. Only `/mcp` exists. It is bound to the loopback interface and refuses anything without the token (compared in constant time).

Scripts the agent runs inside the sandbox reach the same tools through the CLI bridge ([local-runtime.md](local-runtime.md#the-python-side-on-a-phone)): `nanomuse-device clipboard read`, `nanomuse-device calendar list from=2026-09-24`, `nanomuse-device alarm set hour=7 minute=30 message=Train`, `nanomuse-device notify title=Done body=Booked`, `nanomuse-device location`, `nanomuse-device photo pick`; `nanomuse-device list` shows what the phone has. Each goes through the same Sentinel as a model call.

## The tools

| tool | does | arguments | Android permission | risk | asks in `ask` mode? |
| --- | --- | --- | --- | --- | --- |
| `clipboard_read` | the clipboard's text | — | none, but **only while the app is on screen** (Android 10+) | moderate, private | no |
| `clipboard_write` | put text on the clipboard | `text` | none | safe | no |
| `notify` | post a notification; tapping it opens the chat | `title`, `body`, `thread` | `POST_NOTIFICATIONS` (13+) | safe | no |
| `calendars` | the calendars on the phone | — | `READ_CALENDAR` | moderate, private | no |
| `calendar_list` | events in a range, optional word filter | `from`, `to`, `query`, `calendar_id`, `limit` | `READ_CALENDAR` | moderate, private | no |
| `calendar_create` | add an event; all-day takes dates | `title`, `start`, `end`, `all_day`, `location`, `description`, `calendar_id`, `reminder_minutes` | `WRITE_CALENDAR` | moderate | no |
| `calendar_update` | change the fields given | `id`, `title`, `start`, `end`, `all_day`, `location`, `description` | `WRITE_CALENDAR` | moderate | no |
| `calendar_delete` | delete an event | `id` | `WRITE_CALENDAR` | **sensitive** | **yes** |
| `contacts_search` | people by name, number or e-mail; read-only | `query`, `limit` | `READ_CONTACTS` | moderate, private | no |
| `location` | coordinates, accuracy, address when it can be looked up | `accuracy` (`fine`/`coarse`), `max_age_seconds` | `ACCESS_FINE_LOCATION` / `ACCESS_COARSE_LOCATION` | moderate, private | no |
| `alarm_set` | an alarm in the clock app | `hour`, `minute`, `message`, `days`, `vibrate` | `SET_ALARM` (granted at install) | moderate | no |
| `timer_set` | a countdown in the clock app | `seconds` or `minutes`, `message` | `SET_ALARM` | moderate | no |
| `photo_pick` | the user chooses photos in the system picker; copies land in the workspace | `max` (≤ 10), `why` | none — the Photo Picker needs no permission | safe, private | no |

*Risk* and *private* are the Sentinel defaults from `DEVICE_TOOLS` in `nanomuse/runtime.py`, applied per tool through the `tools` map of the MCP server entry ([configuration.md](configuration.md#mcp-servers)). "Asks" is the `ask` mode column of [sentinel.md](sentinel.md); in `strict` mode every moderate tool asks too. *Private* tools taint the session: after `contacts_search` or `location`, anything that sends data to an unknown host asks. Times are phone-local (`YYYY-MM-DD HH:MM`, or a date for all-day); the end of an all-day event is shown as its last day. The address in `location` comes from the platform geocoder when the phone has one; without it the tool returns coordinates only.

The Kotlin list (`DeviceTools.kt`) and the Python table (`DEVICE_TOOLS`) must agree; `tests/test_bridge.py` checks the names and the defaults.

## What the user sees

Everything the tools need from the user is an Android dialog, opened by an invisible activity of the app (`DeviceAskActivity`) so it can appear from wherever the agent is running. Android 10+ does not let a background app start an activity, so there are two routes:

- **The app is on screen** → the dialog appears right away over it.
- **The app is in the background** → a notification (*nanoMuse needs a permission* / *nanoMuse wants to read the clipboard* / *… wants a photo*) with one line on why; tapping it brings up the dialog. The tool call waits in the meantime (2 min for a permission, 1.5 min for the clipboard, 4 min for photos), the model is told what happened either way.

Three outcomes reach the model, in words it can pass on: granted (the tool runs); *the user did not allow it — do not ask again now, it can be allowed later in Android's settings*; *nobody answered — ask the user to open nanoMuse and try again*.

Specific rules, each from the platform rather than from us:

- **Clipboard.** Since Android 10 only the app with the focus may read the clipboard. `clipboard_read` from the background therefore goes through the notification route; the read happens the moment the user taps it. Writing works any time.
- **Alarms and timers.** They are handed to the clock app with the standard `AlarmClock` intents, skipping its UI (the alarm appears in the clock as if set by hand). From the foreground — or when the app has the *display over other apps* permission — the hand-off is immediate; from the background Android forbids starting another app, so a notification is posted and the alarm is set when the user taps it. The clock app is the one the user has; on a phone without one the tool says so.
- **Photos.** Only the [Photo Picker](https://developer.android.com/training/data-storage/shared/photopicker): the user picks, the app receives exactly those items, copies them into `workspace/attachments/<date>/` and returns the paths. Nothing else in the library is readable, no `READ_MEDIA_IMAGES` is requested, and the picker itself says so on screen.
- **Location.** Uses the platform `LocationManager`, no Play services; the last known fix when it is fresh enough (`max_age_seconds`, default 2 min), otherwise a new one with up to 25 s to arrive. `coarse` asks for the approximate permission only.
- **Contacts** are read-only. **Calendars** are read and written through the platform provider; deleting is the one action that always asks.
- **Notifications** posted by `notify` go to the normal channel; tapping opens the thread. Reading the notification shade is **not offered**: it needs the notification-listener special access, which Android treats as a device-wide privilege; if it comes (P2), it will be its own switch, off by default, with its own row in the Sentinel table.

## The workspace in the Files app

The local build registers a `DocumentsProvider`: the agent's workspace appears as a root named after the agent in the system Files app and in every open/save dialog on the phone (Storage Access Framework). Files the agent made are ordinary files; a file dropped there is in the workspace. Hidden entries and the browser profile are not shown. The connect build has no workspace on the phone and shows no root.

## Sharing into nanoMuse

nanoMuse is in the system share sheet for text, links and files. A share becomes a **new conversation**: files are uploaded to the workspace (`attachments/<date>/…`), the thread is named after the subject or the first file, and the chat opens with the shared text as a draft and the files as attachment chips, waiting for what to do with them — nothing is sent to the model until the user says so. Both builds do this (the connect build uploads to the computer).

## Connect mode

The connect build (the phone as a remote for `nanomuse serve` on a computer) has the same Kotlin tools but the server cannot reach `127.0.0.1` on the phone; it would need a relay over the phone's WebSocket. That is planned (P1, [launch-checklist.md](launch-checklist.md)); until then the device tools are a feature of running on the phone.

## Testing without a phone

The emulator (x86_64) cannot run the arm64 PRoot runtime, but the tool host can be exercised directly: the connect **debug** build starts the MCP server on its own and logs `device MCP (debug): http://127.0.0.1:<port>/mcp token=<token>`. Then:

```bash
adb forward tcp:9410 tcp:<port>
# any MCP client, e.g. the reference Python one:
#   streamable_http_client("http://127.0.0.1:9410/mcp?token=<token>")
```

`adb shell pm revoke <app id> android.permission.READ_CALENDAR` brings the permission dialogs back; `adb shell input keyevent KEYCODE_HOME` exercises the notification route; `adb emu geo fix <lon> <lat>` feeds `location`. `McpEndpointTest` covers the transport itself on the JVM (initialize, `tools/list`, an SSE call with heartbeats, a failing tool as `isError`, bad token and method).

## Not in this release

Reading notifications, writing contacts, the whole photo library, SMS and call logs, and the connect-mode relay. Each is a switch of its own when it comes, off by default.
