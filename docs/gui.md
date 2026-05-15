# Operating the phone

Muse's abilities in the West come from services with APIs. Most of what a person in China does on a phone — 12306, WeChat, Alipay, Meituan — has no API a personal agent may call. nanoMuse therefore has a second pair of hands: with the *Phone* switch on, the agent can read the phone's screen and tap, type and swipe in its apps, the way a person would. It is the same agent with the same Sentinel in front of it; GUI steps are just more tool calls.

Off by default. Nothing about the phone reaches the model until you turn it on.

## What it looks like

Ask "帮我看看明天北京到上海最早的高铁" and the agent opens 12306 on the phone, sets the stations and the date, presses 查询 and reads the list back to you. Ask it to reply to someone on WeChat and it opens the chat, types the text, and **stops at the send button until you approve**. Ask for something that mixes both worlds — research on the web, a ticket in 12306, an event in your calendar — and it moves between its native tools and the screen as it goes.

In the chat every GUI step shows up as a row such as `phone_act: tap [19] "发送" in 微信 (wechat)`, so you can see what it did.

## Turning it on

In the app: *Connections → Phone*, flip the switch. In `config.toml`:

```toml
[gui]
enabled = true
```

or `NANOMUSE_GUI_ENABLED=1`. When the switch is on the agent gets three more tools (see below) and a paragraph in its system prompt about the phone that is connected. When it is off, the tools do not exist.

### The model that moves the finger

Reading a screen every step is many small calls, so the operator can use its own, cheaper model, separate from the main one:

```toml
[gui]
enabled  = true
provider = "openai"                                   # or openai_responses
model    = "qwen3.8-27b"                              # a fast model that reads well is enough
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key  = "{{vault:GUI_API_KEY}}"
```

Leave `model` empty and the main model does both. The key goes into the vault like any other (`nanomuse vault set GUI_API_KEY`, or type it into the Phone card). `nanoMuse` sends the operator screenshots when the model takes images; otherwise it works from the element list alone, which is enough for MobileGym and for Android's accessibility tree.

Environment overrides: `NANOMUSE_GUI_ENABLED`, `NANOMUSE_GUI_PROVIDER`, `NANOMUSE_GUI_MODEL`, `NANOMUSE_GUI_BASE_URL`, `NANOMUSE_GUI_API_KEY`.

Other settings: `max_steps` (default 30, the most a single `phone_task` may take), `device_timeout_s` (default 20, how long to wait for the phone to answer one request), `sensitive_words` (the list below).

## Connecting a phone

The agent does not run on the phone. A *device* connects to the nanoMuse server over the same WebSocket the app uses, announces itself and then answers requests for the screen and for actions. Two devices exist:

- **MobileGym** — the simulated phone at [mobilegym.dev](https://mobilegym.dev/), with Chinese apps (微信, 支付宝, 铁路12306, 地图, 小红书 …) as React apps in the browser. The nanoMuse module for it (`demo/mobilegym/`) has the switch *Let nanoMuse operate this phone* on its setup page. This is the showcase environment: nothing real is touched.
- **Android** — the nanoMuse app, through an accessibility service (in progress). Same protocol, real apps.

*Connections → Phone* shows which device is connected and how many apps it lists. `GET /api/phone` returns the same plus the last screen read.

## The tools

| Tool | Risk | What it does |
|---|---|---|
| `phone_screen` | SAFE, reads private data | The current screen as text: the app, the route, and every visible element as `[id] role "text" {flags} @(x,y)` |
| `phone_act` | MODERATE, or SENSITIVE (see below) | One action: `tap`, `long_press`, `double_tap`, `type`, `swipe`, `enter`, `back`, `home`, `recents`, `open_app`, `wait`. Returns the screen after the action |
| `phone_task` | as its steps | Hands a goal to the *phone operator*: a loop with its own model that looks, acts and looks again until the goal is met, it needs you, or it gives up. Each of its steps is a `phone_act` and goes through Sentinel like any other |

The main agent uses `phone_task` for anything that takes more than a step or two ("open 12306, find the earliest train tomorrow from 北京 to 上海, report the first three"), and `phone_screen` / `phone_act` when it wants to look or do one thing itself. Both patterns are fine; the operator keeps the main model's context small.

The operator never types passwords, PINs or codes, and stops with an `ask` before a payment or a transfer it was not explicitly given; the main agent then asks you and only continues with your answer.

## What Sentinel does with it

Everything read from the screen is private data: the session is *tainted* after the first `phone_screen`, so later steps that send data elsewhere are held to the stricter rules (see [sentinel.md](sentinel.md)).

A `phone_act` is MODERATE — allowed on its own in the default mode — except when it looks like it commits to something, in which case it is SENSITIVE with a warning, and a warning always means **ask, once**:

- a tap on an element whose label contains one of `sensitive_words` — 确认支付, 立即付款, 转账, 提交订单, 立即购买, 发送, 删除, 注销, pay now, place order, send, delete … (an app named 支付宝 is not a payment step; app names are exempt)
- a blind tap by coordinates on a screen that shows one of those words
- `enter` on a screen that shows one of those words
- `type` with `submit` — typing and submitting in one step, which the operator never does: it types, then taps the send button on the next step, so that step can be checked against the screen with the text in

The default list is Chinese and English; edit `[gui] sensitive_words` for other apps or languages. Approvals granted here are *once* only: sending one message never turns into sending the next without asking.

## The device protocol

For anyone writing another executor. Messages ride on the app's WebSocket (`/ws?token=…`).

The device announces itself once:

```json
{"kind": "device", "name": "MobileGym", "platform": "mobilegym", "gui": true,
 "apps": [{"id": "wechat", "name": "微信"}, {"id": "railway12306", "name": "铁路12306"}],
 "screen": {"width": 360, "height": 800}}
```

and gets `{"kind": "device_ack", "phone": {…}}` back. The server then asks, one request at a time:

```json
{"kind": "device_request", "id": "r1", "op": "screen", "params": {}}
{"kind": "device_request", "id": "r2", "op": "act", "params": {"action": "tap", "x": 180, "y": 209, "element": 6, "label": "blank."}}
```

and the device answers `{"kind": "device_result", "id": "r1", "ok": true, "result": …}` or `{"kind": "device_result", "id": "r1", "ok": false, "error": "…"}`.

A `screen` result:

```json
{"app": "wechat", "app_name": "微信", "route": "/chat/wxid_blank_001",
 "width": 360, "height": 800, "keyboard": false,
 "elements": [{"id": 6, "role": "button", "text": "blank. 14:32 你好", "desc": "",
               "bounds": [3, 172, 360, 246], "clickable": true, "editable": false,
               "scrollable": false, "focused": false, "checked": null, "value": ""}],
 "image": "<base64 JPEG or PNG, optional>", "note": "optional"}
```

Coordinates are in the phone's own pixels (`width` × `height`), top-left origin. Ids are per screen; the server resolves an `element` id from the last screen into `x`/`y` before it sends an `act`, so a device only ever needs to handle points. An `act` result is `{"note": "opened wechat", "screen": {…}}` — the screen as it looks once the action has settled.

Actions a device must handle: `tap`, `double_tap`, `long_press` (`x`, `y`); `type` (`text`, `clear`, `submit`, and `x`/`y` of the field when known); `swipe` (`direction`, `distance` as a fraction of the screen, optional `x`/`y` to start from); `enter`, `back`, `home`, `recents`; `open_app` (`app`, an id or a name); `wait` (`seconds`).

The MobileGym executor (`demo/mobilegym/apps/nanoMuse/gui.ts`) is a readable example: it walks the simulator's DOM into that element list — buttons, fields, text, what is scrollable, what the keyboard covers — and drives MobileGym's own input API for the actions.

## Limits

- One phone at a time: the most recently connected device with `gui: true` is the one the agent operates.
- The operator sees what the device reports. On MobileGym that is the DOM; unlabelled icons are described by position (`icon, top right`) or by the simulator's action id (`stationSelect.from`). On Android it will be the accessibility tree, which is only as good as the app's labels.
- No screenshots from MobileGym yet; the element list is the whole observation there.
- Sentinel judges by labels and words on screen. An app that hides "pay" behind an icon with no label will not trip the word list — which is why payment steps are also covered by the operator's own rule to stop and ask before paying, and why grants are once-only.
