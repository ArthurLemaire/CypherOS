# Operating the phone

Muse's abilities in the West come from services with APIs. Most of what a person in China does on a phone — 12306, 微信, 支付宝, 美团 — has no API a personal agent may call. nanoMuse therefore has a second pair of hands: with the *Phone* switch on, the agent can look at the phone's screen and tap, type and swipe in its apps, the way a person would. It is the same agent with the same Sentinel in front of it; GUI steps are just more tool calls.

Three things decide how this part is built:

- **Local.** The brain runs where you run it — your machine, or the phone itself in the Android build — and the screen goes to the model you configured, nobody else.
- **China first.** The default model is on 阿里云百炼, the sample tasks are 12306 and 微信, the sensitive-word list is Chinese first.
- **Any app.** The operator sees the screen as a picture and taps by position. It does not need an accessibility tree, labelled buttons or a per-app integration, so a new app costs nothing — the same loop that books a train reads a chat. When the device *has* a tree (the Android app), it is sent along as a second input — small text becomes readable and a password field is known to be one — but nothing depends on it.
- **Last resort.** The screen is the fourth rung of a ladder (below): a skill, a command-line tool or an MCP server that does the thing exactly comes first, then a page fetched with the user's login, then the in-app browser. Every screen step is a model call and a picture; the agent climbs only when the rung below cannot do it, and says so before it starts.

Off by default. Nothing about the phone reaches the model until you turn it on.

## The ladder

There are four ways to reach a service, and they are tried lowest first:

| rung | how | when |
|---|---|---|
| 1 | a **skill**, a **CLI** or an **MCP server** — `feishu` through lark-cli, `amap` through its MCP server, mail, the calendar, files | whenever one exists: exact, instant, no screen |
| 2 | a **fetch with the user's login** — `browser` action=fetch, `web_fetch` | a page that shows the answer once you are signed in |
| 3 | the **in-app browser**, page by page | a site that needs clicking through, but is a site |
| 4 | the **phone's screen** — `phone_task` | what lives in an app and nowhere else: a 微信 chat, 12306's real seats, an order in 美团, a payment |

A skill says which rung it works on with `channel:` in its front matter — `api`, `cli`, `web`, `browser`, `gui` or `mixed` (`app-only` and `phone` are accepted for `gui`). A `gui` skill shows up in the agent's skill index as *[on the phone's screen]*, so the agent knows a rung-4 job when it sees one; `train-tickets` and `phone-messages` are the built-in examples. Before the first step on the screen the agent says in one line what it is about to do on the phone; if you did not ask for the phone yourself — it is climbing because the lower rungs failed — it asks first. The Activity view counts how many of a session's steps were on the screen, so you can see the ladder being kept.

## What it looks like

Ask "帮我看看明天北京到上海最早的高铁" and the agent opens 12306 on the phone, sets the stations and the date, presses 查询车票, filters 只看高铁 and reads the list back to you. Ask it to reply to someone on 微信 and it opens the chat, types the text, and **stops at the send button until you approve**. Ask for something that mixes both worlds — research on the web, a ticket in 12306, an event in your calendar — and it moves between its native tools and the screen as it goes.

In the chat every GUI step shows up as a row such as `phone_act: tap "发送" at (318,742) in 微信 (wechat)`, so you can see what it did; on the phone a ripple marks where the finger landed and a caption says what Muse is doing (see [Showing the finger](#showing-the-finger)). Afterwards `nanomuse phone traces` lists every task and `nanomuse phone trace <id> -o trace.html` renders one as a page with every screen and every tap drawn on it.

## Turning it on

In the app: *Connections → Phone*, flip the switch. In `config.toml`:

```toml
[gui]
enabled = true
```

or `NANOMUSE_GUI_ENABLED=1`. When the switch is on the agent gets three more tools (see below) and a paragraph in its system prompt about the phone that is connected. When it is off, the tools do not exist.

### The model that moves the finger

Reading a screen every step is many small calls, each with a picture in it, so the operator can use its own model, separate from the main one:

```toml
[gui]
enabled  = true
provider = "openai"                                   # or openai_responses
model    = "qwen3.8-27b"                              # must take images; a fast one that reads well is enough
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key  = "{{vault:GUI_API_KEY}}"
```

Leave `model` empty and the main model does both. The key goes into the vault like any other (`nanomuse vault set GUI_API_KEY`, or type it into the Phone card). The operator's model **must accept images**: a screenshot is the whole observation. The operator calls it at temperature 0 — grounding wants the model's first choice, not a sample.

Environment overrides: `NANOMUSE_GUI_ENABLED`, `NANOMUSE_GUI_PROVIDER`, `NANOMUSE_GUI_MODEL`, `NANOMUSE_GUI_BASE_URL`, `NANOMUSE_GUI_API_KEY`.

Other settings: `max_steps` (default 30, the most a single `phone_task` may take), `device_timeout_s` (default 20, how long to wait for the phone to answer one request), `sensitive_words` (the list below).

## Connecting a phone

The agent does not have to run on the phone. A *device* connects to the nanoMuse server over the same WebSocket the app uses, announces itself and then answers requests for the screen and for actions. Two devices exist:

- **MobileGym** — the simulated phone at [mobilegym.dev](https://mobilegym.dev/), with Chinese apps (微信, 支付宝, 铁路12306, 地图, 小红书 …) as React apps in the browser. The nanoMuse module for it (`demo/mobilegym/`) has the switch *Let nanoMuse operate this phone* on its setup page. This is the showcase environment: nothing real is touched.
- **Android** — the nanoMuse app, through its own accessibility service: `takeScreenshot()` for the picture, `dispatchGesture()` for the finger, the accessibility tree for the element list, `performGlobalAction` for Back / Home / Recents, and the app's own list of launchable apps for `open_app`. Same protocol, real apps. It needs **Android 11 or newer** (that is where an accessibility service may take screenshots) and the service switched on:

  1. *Connections → Phone → This phone → Open Accessibility settings*, find **nanoMuse** under *Downloaded apps* and turn it on. Android explains what the service can do — see the screen, perform gestures — and asks you to confirm.
  2. On Android 13 and newer an app installed from a download (not a store) gets the switch greyed out with *Restricted setting*. Open the app's page in Settings (*App settings* on the same card), tap ⋮ → **Allow restricted settings**, then go back to step 1.
  3. Android turns accessibility services off on its own now and then — after an update, after an aggressive battery clean-up, on some phones after a reboot. The Phone card shows *Ready* / *Not yet* live; if the phone stops answering, look there first. The app announces the change to the server the moment the service comes or goes, so *Connections → Phone* is never stale.

  The service does nothing on its own: it takes a screen only when a `phone_*` tool asks for one, and every task shows a capsule at the top of the screen — the red panda, the step in progress and a **Stop** button (see below).

*Connections → Phone* shows which device is connected and how many apps it lists. `GET /api/phone` returns the same plus the last screen read.

## The tools

| Tool | Risk | What it does |
|---|---|---|
| `phone_screen` | SAFE, reads private data | The current screen: a screenshot for the model to look at, with a caption — `铁路12306 (railway12306) · /station-select · 360×800 · keyboard hidden` |
| `phone_act` | MODERATE, or SENSITIVE (see below) | One action by position: `tap`, `long_press`, `double_tap` at `x`/`y` with a `label`; `swipe` to `x2`/`y2` or by `direction`; `type`, `enter`, `back`, `home`, `recents`, `open_app`, `wait`. Returns the screen after the action |
| `phone_task` | as its steps | Hands a goal to the *phone operator*: a loop with its own model that looks, acts and looks again until the goal is met, it needs you, or it gives up. Each of its steps is a `phone_act` and goes through Sentinel like any other |

**The screen is the last rung.** Search, a web page, mail, the calendar, files, a connector — when one of those gives the answer instantly and precisely, the agent uses it; the phone is for what only the user's own apps and accounts can do: 12306's real seats and prices, a 微信 chat, an order in 美团, a payment that needs their account. The phone is slower than a tool and every step is a model call, so the agent does not open 12306 to learn how far 北京 is from 上海 (see [The ladder](#the-ladder)).

The main agent uses `phone_task` for anything that takes more than a step or two ("open 12306, find the earliest train tomorrow from 北京 to 上海, report the first three"), and `phone_screen` / `phone_act` when it wants to look or do one thing itself. Both patterns are fine; the operator keeps the main model's context small.

## The operator

`phone_task(goal, app?, max_steps?)` runs an inner loop, ported from the `mobile_use` operator in [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench) (MIT):

1. **Look.** Take the screen. The operator's model gets one picture — the current screen — plus the goal and the list of what it has done so far, each earlier step as one sentence (`Step 3: 点击「查询车站」按钮。; Result: …`). When the device sent an element list, up to 60 of its lines follow, fields first, each with its words, kind, flags and centre on the same 999 grid the model answers in (`- "密码" · EditText [editable, password] @ 500,375`): a second input for reading small text and aiming, never the first.
2. **Decide.** The model answers in a fixed shape: a `Thought:` line, an `Action:` sentence in the user's language, and one `<tool_call>` calling `mobile_use` — `click`, `long_press`, `swipe`, `type`, `open`, `system_button` (Back, Home, Menu, Enter), `wait`, `answer`, `ask_user` or `terminate`. Coordinates come back on a 999×999 grid and are scaled to the phone's pixels. A reply in the wrong shape is sent back once with a reminder, three times at most.
3. **Act.** The step becomes a `phone_act`, with the Action sentence as its `label` — that sentence is what Sentinel reads, what the approval card shows, and what the trace keeps. Then back to 1.

It stops with `done` and the model's `answer` (the text it read off the screen goes there), with `ask` when the model calls `ask_user` or Sentinel wants a decision (the main agent asks you and continues with your answer), with `blocked` after two refusals, with `stopped` when you press **Stop** on the phone, with `failed` on `terminate(failure)`, after `max_steps`, or when the phone stops answering. The same action three times in a row gets a note in the history so the model changes tack.

On a device with a capsule the operator also tells the phone when a task **begins** (the capsule appears with the goal), when it **ends** (the capsule goes), and when it **needs you** — an `ask` or a `blocked` becomes a card on the phone with the question and an *Open* button into the chat, because you are looking at 微信 at that moment, not at nanoMuse.

The operator's own rules, in its prompt: never type passwords, PINs, card numbers or one-time codes — `ask_user` first; never confirm a payment or a transfer it was not explicitly told to make; do only what the query asks, and when the query is "look this up", read and `answer` without pressing further.

## What Sentinel does with it

Everything read from the screen is private data: the session is *tainted* after the first `phone_screen`, so later steps that send data elsewhere are held to the stricter rules (see [sentinel.md](sentinel.md)).

A `phone_act` is MODERATE — allowed on its own in the default mode — except when it looks like it commits to something, in which case it is SENSITIVE with a warning, and a warning always means **ask, once**:

- a `tap`, `long_press`, `double_tap` or `enter` whose `label` contains one of `sensitive_words` — 确认支付, 立即付款, 转账, 提交订单, 立即购买, 发送, 删除, 注销, pay now, place order, send, delete … (an app's name is exempt: tapping the 支付宝 icon is not a payment step)
- `type` with `submit` — typing and submitting in one step, which the operator never does: it types, then taps the send button on the next step, so that step can be checked with the text in the field

A pointed action **must** carry a `label` — the words under the finger, as the screen shows them; the operator supplies its Action sentence. A tap without one still runs but carries a warning ("nothing says what is under the finger"), and a point outside the screen is refused before it reaches the phone.

The default word list is Chinese and English; edit `[gui] sensitive_words` for other apps or languages. Approvals granted here are *once* only: sending one message never turns into sending the next without asking.

Since the observation is a picture, Sentinel judges by the *label* — the model's own words for what it is about to press — not by text it found in a tree. That is honest about what the operator knows, and it is why the label is required, why payment steps are also covered by the operator's own rule to stop and ask, and why grants are once-only.

## Traces

Every `phone_task` writes a JSONL trace under `<data_dir>/phone-traces/pt-<timestamp>-<id>.jsonl`: a `task` record (goal, app, context), one `step` record per iteration (the screen's app and route, the screenshot's path, the model's thought and Action sentence, the tool call, the device action actually sent, latency, any error) and an `end` record (status, message, steps, seconds). The last 200 traces and the last 400 screenshots are kept.

```
nanomuse phone traces                    # newest first: id, when, status, steps, goal
nanomuse phone trace pt-20260923-230710-5be7
nanomuse phone trace pt-20260923-230710-5be7 -o trace.html
```

The HTML page is self-contained — every screenshot inlined, the tap drawn as a ring and the swipe as a line on the very screen the model saw — so a run can be sent around or attached to an issue as one file.

## The device protocol

For anyone writing another executor. Messages ride on the app's WebSocket (`/ws?token=…`).

The device announces itself once:

```json
{"kind": "device", "name": "MobileGym", "platform": "mobilegym", "gui": true,
 "apps": [{"id": "wechat", "name": "微信"}, {"id": "railway12306", "name": "铁路12306"}],
 "screen": {"width": 360, "height": 800}}
```

and gets `{"kind": "device_ack", "phone": {…}}` back. A device may announce again on the same connection when something changed (the Android app does when its accessibility service is switched on or off; `gui` flips); the server keeps the connection's time of arrival and updates the rest. `"capsule": true` says the device shows a step capsule with a Stop button and wants the `task` requests below. The server then asks, one request at a time:

```json
{"kind": "device_request", "id": "r1", "op": "screen", "params": {}}
{"kind": "device_request", "id": "r2", "op": "act", "params": {"action": "tap", "x": 68.5, "y": 447.6, "label": "点击热门车站中的「北京」。"}}
```

and the device answers `{"kind": "device_result", "id": "r1", "ok": true, "result": …}` or `{"kind": "device_result", "id": "r1", "ok": false, "error": "…"}`.

A `screen` result is a picture and a few facts about it:

```json
{"app": "railway12306", "app_name": "铁路12306", "route": "/station-select",
 "width": 360, "height": 800, "keyboard": false,
 "screenshot": "<base64 PNG or JPEG>", "note": "optional"}
```

`screenshot` is the whole screen, `width` × `height` pixels — the same space the device takes its taps in, so a point in the picture is a point on the screen with no conversion; when a device sends no size at all the server reads it off the picture. (`image` is accepted as an older name for the same field.) The model reads the picture, and coordinates are pixels in it, top-left origin. `app`, `app_name`, `route` and `keyboard` are optional but make the captions, Sentinel's summaries and the traces better.

A device that has an accessibility tree may add `nodes` — the elements that say or do something, flattened, at most 120, in the picture's pixel space:

```json
{"nodes": [
  {"id": "0.3.1", "class": "Button", "text": "查询车票", "cx": 180, "cy": 612, "box": [24, 588, 336, 636], "clickable": true},
  {"id": "0.2.0", "class": "EditText", "hint": "密码", "cx": 180, "cy": 400, "editable": true, "password": true}
]}
```

`id` is a stable index path into the tree, `text` / `desc` / `hint` the element's words, `res` its resource id; flags are `clickable`, `long_clickable`, `editable`, `password`, `checked`, `scrollable`, `focused`, `selected`, `disabled`. The server keeps the first 120, shows the operator the 60 most useful (fields first), and never requires the list — a WebView, a Flutter app, a game or a `FLAG_SECURE` screen has none, and the loop is the same without it. The Android app downscales the screenshot to 720 px wide before sending and scales the coordinates it receives back up, so the space the model sees is the space it taps in.

An `act` result is `{"note": "…", "screen": {…}}` — the screen as it looks once the action has settled, so a step costs one round trip.

Actions a device must handle:

| action | params |
|---|---|
| `tap`, `double_tap` | `x`, `y` |
| `long_press` | `x`, `y`, `seconds` (≤ 5) |
| `swipe` | `x`, `y`, `x2`, `y2` — or `direction` up/down/left/right with `distance` as a fraction of the screen and an optional start point |
| `type` | `text`, `clear` (empty the field first), `submit` (press enter afterwards); `x`, `y` of the field when known |
| `enter`, `back`, `home`, `recents` | — |
| `open_app` | `app` — an id or a name from the announce list |
| `wait` | `seconds` (≤ 10) |

Every pointed action also carries `label`: the executor should show it (see below) and may log it; it needs nothing else from it.

A device that announced `"capsule": true` also gets `task` requests — `{"op": "task", "params": {"event": "begin", "text": "<goal>"}}`, `"end"`, and `"notice"` with the question the agent has for the user — and answers them with an empty `ok`; they are best effort, and a device that does not answer in 3 s is not waited for.

**Stop.** When the user presses Stop on the device, the device fails the request in flight (and every one after it until the next `task begin`) with an error that contains the marker `nanomuse:stop`. The server turns that into a `stopped` outcome: the operator ends its loop, `phone_act` reports it in plain words, and the main agent is told not to go on operating the phone but to ask what to do next. A device without a capsule never needs to send the marker.

The MobileGym executor (`demo/mobilegym/apps/nanoMuse/gui.ts`) is a readable example: it renders the simulator's DOM to a PNG in the page (`modern-screenshot`, with the phone's CSS transform neutralised and the finger overlay left out), reads the app and route off the simulator's OS object, and drives MobileGym's own input API for the actions so a tap lands the way a finger would.

## Showing the finger

An executor that moves in silence is unnerving to watch and impossible to follow. Devices should draw what Muse does, in the phone's own coordinate space, on a layer that is **excluded from the screenshot** (the model must not see the marks). The MobileGym module is the reference; the Android app follows the same spec with two accessibility overlay windows — an untouchable full-screen layer for the marks, and the capsule — both hidden for the instant a screenshot is taken.

| what | how it shows | timing |
|---|---|---|
| `tap`, `double_tap` | a ring that expands from the point and fades | 520 ms |
| `long_press` | a ring that holds, then fades | `seconds`, then 300 ms fade |
| `swipe` | a line drawn from start to end with a ring at the end | the swipe's own duration (320 ms), then fade |
| `type` | characters appear one by one | 40 ms per character |
| every action | a caption at the bottom: `Muse · <label>` (or `输入 “…”`, `打开 <app>`, `滑动 up`) | 2.6 s, replaced by the next |

After an action the executor waits for the UI to settle (650 ms on MobileGym; on Android until the accessibility events go quiet for 450 ms, 3 s at most) before it takes the screen it returns. The wait is part of the action, so a `screen` read never lands mid-transition.

### The capsule

On Android a task is never silent: a pill at the top of the screen shows the red panda, the step in progress (*Muse · 点击「查询车票」*) and a **Stop** button, over whatever app is being operated. It appears on `task begin`, follows every step, and goes on `task end`; it is not part of the screenshot. Stop is the user's brake — no long press, no menu: one tap, the action in flight fails with `nanomuse:stop`, the pill says *Stopped* and hides itself, and the agent asks what to do next instead of carrying on. When the agent needs the user (`ask`, `blocked`) the pill grows into a card with the question and an *Open* button that brings nanoMuse to the front; it stays a minute, then folds away.

## Limits

- One phone at a time: the most recently connected device with `gui: true` is the one the agent operates.
- The operator sees exactly what the device draws. Text it cannot read in the picture it cannot act on: a low-resolution screenshot is the first thing to check when it taps beside a target. The picture and the tap space are the same `width` × `height`, so a sharper picture means a device that announces — and taps in — a larger one.
- Apps rendered in an iframe inside MobileGym (nanoMuse itself, for one) are blank in an in-page screenshot; the operator is told the screen was dark rather than shown something wrong.
- Sentinel judges by the operator's words for what it presses. A screen that hides "pay" behind an icon with no words will not trip the list — which is why payment steps are also covered by the operator's own rule to stop and ask before paying, and why grants are once-only.
- On Android: the executor needs Android 11+; a `FLAG_SECURE` screen (banking apps, a payment sheet, a password manager) comes back black and the operator is told so; the Android executor refuses to `type` into a password field at all, whatever the label says; and Android may quietly refuse an `open_app` from the background — the executor then says so and asks the user to press Home and the icon (the *display over other apps* permission helps before Android 14). Text goes in through `ACTION_SET_TEXT` where the field allows it, otherwise through the clipboard and a paste.
