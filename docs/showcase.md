# Showcase: what to ask it

Things to try, written for the apps on the [simulated phone](../demo/mobilegym/README.md) — 微信, 支付宝, 铁路12306, 地图, 天气, 哔哩哔哩, 小红书, 腾讯会议, 微信读书 and the system apps — but the same asks work on a real phone once the Android executor lands. Three kinds, because Muse's own abilities and the phone's screen are one agent: some tasks need only the phone, some need none of it, and the interesting ones need both.

All of them work with the *Phone* switch on and a phone connected (`Connections → Phone` shows "MobileGym connected"). Nothing here spends money: every send, order or payment step stops for your approval, and the operator does not fill in passwords or codes.

## On the phone only

One app:

| Ask | What happens |
|---|---|
| 打开微信，看看最上面三个聊天是谁、最后一条说了什么 | Opens 微信, reads the chat list, comes back with names, previews and times. Nothing is tapped inside a chat. |
| 给 blank. 回一句「好的，那明天见」 | Reads the chat first, types the text, and stops at 发送 — an approval card, once; then confirms the bubble is there. |
| 用 12306 查一下后天上海到杭州最早的三班高铁，二等座多少钱 | Sets 出发 / 到达 and the date, presses 查询车票, ticks 只看高铁/动车 when the list mixes in slow trains, reads the first three back. Search only. |
| 明天北京的天气怎么样，要带伞吗 | 天气 app: the forecast for tomorrow, in a sentence. |
| 在地图里搜一下从北京南站到国贸怎么走，大概多久 | 地图: a route and its duration. |
| 支付宝里我这个月的账单大概花了多少 | 支付宝: reads the bill page and sums it up; never taps 付款 or 转账. |

Across apps:

| Ask | What happens |
|---|---|
| 查一下明天北京到上海最早的高铁，然后把车次和时间发给 Boss | 12306 for the search, 微信 for the message; the send waits for your approval with the exact text on the card. |
| 看看小红书上「杭州两日游」最热的一篇笔记讲了什么，把要点记到笔记 app 里 | 小红书 to read, 笔记 to write. |
| 腾讯会议里下一个会是几点，提前十分钟在时钟里设个闹钟 | 腾讯会议 for the time, 时钟 for the alarm. |

## Without the phone

Muse as Muse: these never touch the screen.

| Ask | What happens |
|---|---|
| 比较一下 Sony WH-1000XM6 和 Bose QuietComfort Ultra 哪个更适合长途飞行，写一份简短对比存到 headphones.md | `web_search`, `web_fetch`, a file in the workspace, a preview in Library. |
| 帮我看看这台机器还剩多少磁盘空间 | `shell` — stops on an approval card because it is a shell command. |
| 定一个目标：12 月去京都前把日语会话练起来，每天 30 分钟 | A goal with steps and a daily check-in, worked on in the background. |
| 每个工作日早上 7:30 给我一行今天的天气 | A routine; the message arrives as a notification with the app closed. |
| 记住我坐高铁只坐靠窗、不坐一等座 | Memory; used the next time trains come up. |

## Both

The reason the two live in one agent.

| Ask | What happens |
|---|---|
| 下周三去上海开会，帮我做个行程：查网上有什么值得顺路去的地方，用 12306 看看早上的高铁，把出发时间写进日历 | Web research for the plan, 12306 on the phone for real trains and prices (search only), a calendar draft for the departure, `trips/…/itinerary.html` in the workspace — the `trip-plan` skill. |
| 看看微信里王芳最后说了什么，如果她问周末的事，查一下周六的天气再回她 | Reads the chat, decides what she asked, gets the forecast (web or the 天气 app), drafts a reply for you to confirm, sends it once you do. |
| 帮我查明天北京到上海的高铁，选一班上午 9 点前出发的，订好后提醒我付款 | 12306 to the order screen (you approve 提交订单), then a reminder to pay in the app within its time limit; the payment stays yours. |
| 把 Boss 刚发我的那条消息里的时间和地点整理进日历 | Reads the message on the phone, creates the event with the calendar tool. |

## Reading the trail

Every phone step is a row in the chat — `phone_act: tap "发送" at (318,742) in 微信 (wechat)` — and every approval card says what will be tapped and why it asks; on the phone itself a ripple marks the tap and a caption says what Muse is doing. `Activity` under the avatar keeps the audit log; `Permissions` shows the grants, which for phone steps are only ever *once*. On your own server, `nanomuse phone traces` lists every phone task and `nanomuse phone trace <id> -o trace.html` renders one as a page with every screen the operator saw and every tap drawn on it ([gui.md → Traces](gui.md#traces)).

Two built-in skills carry the phone habits — `train-tickets` and `phone-messages` — and `trip-plan` knows to look in 12306 when a phone is there. `Skills` in the app lists them; a folder of your own with the same name replaces one.
