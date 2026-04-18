# Showcase: seven things a Chinese day asks for

nanoMuse is one agent with several hands. It reads and writes files, searches the web, runs commands, drives a browser; it calls MCP servers and command-line tools; it follows skills; and, when it runs on a phone, it uses the phone's own calendar, clipboard and alarms — and, as the last resort, the apps on the phone's screen. The [ladder](gui.md#the-ladder) says which hand comes first: a skill, a CLI or an MCP server; then a fetch with the user's login; then the in-app browser; only then the screen. Of the seven cases below, one uses the screen. That is the point.

Nothing here spends money: every send, order or payment stops for your approval, and the operator never fills in passwords or codes. Which services stand behind the cases, and which have been run where: [services.md](services.md).

**Traces.** Each case links to what actually happened — the chat's timeline as the app stores it, or a phone trace with every screen and tap. Cases marked *pending* have not been run end to end yet, and the line says what they wait for: the four Tier-1 services need the owner's keys and logins (a 高德 key, a 飞书 and a 腾讯会议 login), and the phone cases need an Android phone with the apps on it. The [launch checklist](launch-checklist.md#9-chinese-services-and-the-showcase-p0) tracks them.

## 1. A business trip in one sentence

> 明天要去上海开会，下午两点在虹桥附近。帮我看看北京到上海上午出发、下午一点前能到虹桥的高铁，挑一班合适的；查一下从家到北京南站几点得出发；把出发时间写进日历，车次发到飞书的「出差」群。另外记住：我坐高铁只坐二等座、靠窗。

| Hand | What it does |
|---|---|
| `skills` | reads `train-tickets`: search through the 12306 server, book on the phone only when told to |
| `remember` | 二等座、靠窗 — a preference, used the next time trains come up |
| `12306__get-current-date` · `get-station-code-of-citys` · `get-station-code-by-names` · `get-tickets` | tomorrow's date from the server, the codes for 北京 and 上海虹桥, the G trains before 13:00 with seats and prices; a second query when the first is sold out |
| `amap__maps_geo` · `maps_direction_transit_integrated` | home (remembered) → 北京南站 at that hour: leave by 06:40 |
| `calendar` | a draft for the departure with 车次 and seat, for you to confirm |
| `shell: lark-cli im +chat-search` · `im +messages-send --idempotency-key …` | the 「出差」 group, the one message — its text on an approval card first |

No screen anywhere. The Sentinel asks once, for the message; everything else is read-only or in your own workspace.

**Trace:** [the train half](traces/case-1-train.md) — recorded on 2026-09-24 in the web app with the 12306 server; the model found every 二等座 before 13:00 sold out, said so, and gave the nearest alternatives instead of pretending. The 高德 route, the calendar draft and the 飞书 message are *pending*: a 高德 key and a 飞书 login on the test machine.

## 2. The morning brief

> 每个工作日早上 7:30 给我一条简报：今天北京的天气、飞书上的日程和没做完的任务、腾讯会议里今天有哪些会，一条通知就好。

| Hand | What it does |
|---|---|
| `reminders` (a routine) | `weekdays 07:30`, delivered as a notification with the app closed — on the phone, the runtime's alarm wakes it for this |
| `amap__maps_weather` | 北京 today: temperature, rain, air |
| `shell: lark-cli calendar +agenda --as user` · `task +get-my-tasks --as user` | the day's events and the open tasks, `--jq` to keep them short |
| `shell: tmeet meeting list --compact` | today's meetings with 会议号 and link |
| the notification | one card; tapping it opens the chat with the full brief |

**Trace:** *pending* — 高德 key, 飞书 and 腾讯会议 logins. The routine and the notification path themselves are exercised by the app's tests and the emulator (the *Keep it running* work in [android.md](android.md#keeping-it-running)).

## 3. Where is my 京东 order

> 我上周在京东买的耳机到哪了？

| Hand | What it does |
|---|---|
| `browser` (the phone's WebView, offscreen) | opens 京东's order page in the background |
| the login wall | the agent stops: *Take over* slides the real page up as a sheet, you log in once, **Done** hands it back — the login persists in the app's own browser profile |
| `browser` `extract` | the order and its tracking number and courier |
| `kuaidi100__query_trace` (when configured) | the parcel's events; otherwise the order page's own tracking list |
| the reply | where it is, when it should arrive |

The second rung — a page with your login, in the app — before any screen: 京东 has no personal API, but its web works without an app. Configured, 快递100 turns the tracking into one tool call.

**Trace:** *pending* — a 京东 login on a phone with the local build. The browser backend, the take-over sheet and the login persisting were verified on the emulator in [browser.md](browser.md).

## 4. A budget table for 成都 over the holiday

> 国庆去成都三晚，住春熙路附近。帮我在去哪儿网上看看每晚 400 元左右、评分 4.5 以上的酒店，挑三家做成预算表存到 trips/chengdu-2026-10/budget.md，只看不订。

| Hand | What it does |
|---|---|
| `browser` (Playwright on the computer, or the phone's WebView) | 去哪儿 hotel search for the dates and the area, filters, three listings read |
| `files` | `trips/chengdu-2026-10/budget.md` — name, location, price per night, three nights, rating |
| Library | the table opens as a page in the app |

Third rung: a public site, no login, browsed in the background while you do something else. The agent does not book; "只看不订" is also what the `browser` tool's Sentinel rules enforce for order and payment buttons.

**Trace:** see the note at the end of this page for the run on 2026-09-24.

## 5. Book a meeting and tell the group

> 下周三下午三点跟设计组开半小时的评审会，用腾讯会议，把会议号发到飞书「设计评审」群。

| Hand | What it does |
|---|---|
| `calendar` | the slot is free |
| `shell: tmeet meeting create --subject 设计评审 --start 2026-09-30T15:00+08:00 --end 2026-09-30T15:30+08:00` | one approval card with the exact command; the answer carries `meeting_code` and `join_url` |
| `shell: lark-cli im +messages-send --chat-id oc_… --text "…"` | the group message with 会议号 and link — its text on a second card |
| `reminders` | ten minutes before |

Two CLIs, two approvals, no app opened. **Trace:** *pending* — 腾讯会议 and 飞书 logins on the test machine (`tmeet auth login`, `lark-cli auth login`).

## 6. Clipboard → calendar + alarm

> （copies a message: 「周五上午10点，海淀区中关村大街1号3层会议室，带上合同」）把剪贴板里的这个安排加到日历，提前一小时给我设个闹钟。

| Hand | What it does |
|---|---|
| `device__clipboard_read` | the text (Android lets an app read the clipboard only while it is on screen; the tool says so when it is not) |
| `device__calendar_create` | Friday 10:00, the address as the location, 「带上合同」 in the notes — Android's own permission dialog the first time |
| `device__alarm_set` | 09:00 Friday through the clock app |
| `amap__maps_geo` (optional) | the address checked, the travel time added to the notes |

The phone's own capabilities as MCP tools ([device.md](device.md)); nothing leaves the phone except the optional geocode. **Trace:** *pending* — the local build on an Android phone (the device server runs only there).

## 7. A 美团 order that stops before payment

> 用美团给我点一份公司附近的麦当劳板烧鸡腿堡套餐，送到公司，到付款前停下来。

| Hand | What it does |
|---|---|
| `phone_task` in 美团 | search, the restaurant, the set meal, the address; the capsule shows the step and **Stop** all the while |
| the Sentinel | the tap on 提交订单 is SENSITIVE (`sensitive_words`): an approval card, once |
| the stop | the operator ends on the payment page and says so; paying is yours, in the app |

The only case on the screen, because 美团 has no personal API and its web needs the app's login. Everything the operator saw and did is in the trace, every tap drawn on its screenshot.

**Trace:** *pending* — an Android phone with 美团 installed (the x86 emulator cannot run it). The executor, the capsule and Stop were verified on the emulator in [gui.md](gui.md).

## Documented, not shown

Four more screen cases are written up in the `train-tickets` and `phone-messages` skills and stop at the same place — the last confirmation is yours:

- 交管12123: look up fines, stop before paying.
- 滴滴: fill in the destination, stop before 呼叫.
- 12306 app: a booking up to 提交订单 (the search itself no longer needs the screen).
- 京东 app: the cart up to 结算.

## Never in public material

The agent can read 微信 on the phone's screen when you ask it to, and some people will. It does not appear in the showcase, the site or the film, nor do 支付宝 statements, 医保 or 个税 — services whose terms forbid automation or whose data should not be in a demo.

## Reading the trail

Every step is a row in the chat — `12306__get-tickets(…)`, `shell: lark-cli calendar +agenda --as user`, `phone_act: tap "提交订单" at (318,742) in 美团` — and every approval card says what will be done and why it asks. `Activity` under the avatar keeps the audit log with the channel of every call; `Permissions` shows the grants, which for phone steps are only ever *once*. On your own server, `nanomuse phone traces` lists every phone task and `nanomuse phone trace <id> -o trace.html` renders one as a page with every screen the operator saw and every tap drawn on it ([gui.md → Traces](gui.md#traces)). The Markdown traces under [`docs/traces/`](traces/) are the same timelines, rendered for reading.

Eleven skills carry these habits — `feishu`, `tencent-meeting`, `amap`, `kuaidi100` and `train-tickets` for the services above, `phone-messages` for the screen, `trip-plan`, `meeting-prep`, `inbox-triage`, `compare-options` and `weekly-review` for the agent's own work. `Skills` in the app lists them; a folder of your own with the same name replaces one. Skills written for other agents in the [Agent Skills](https://agentskills.io) format drop into `<data_dir>/skills` as they are — Larksuite's own `lark-*` skills included.
