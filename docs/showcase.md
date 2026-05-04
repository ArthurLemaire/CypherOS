# Showcase: what to ask it

nanoMuse is one agent with several hands. It reads and writes files, searches the web, runs commands, drives a browser; it calls MCP servers and command-line tools; it follows skills; and, when a phone is connected, it operates the apps on the phone's screen. The screen is the hand of last resort — for 12306, 微信 and 支付宝, which have no API a personal agent may use — not the point of the project. Many things in a Chinese day need no screen at all: 飞书 has a CLI, 高德 has an MCP server, and the agent uses those the way it uses any tool, with the Sentinel between it and anything irreversible.

Five kinds of asks below, because those hands belong to one agent: some need only the phone, some a CLI or an MCP server, some none of it, and the interesting ones mix them. Nothing here spends money: every send, order or payment step stops for your approval, and the operator does not fill in passwords or codes.

The phone asks are written for the apps on the [simulated phone](../demo/mobilegym/README.md) — 微信, 支付宝, 铁路12306, 地图, 天气, 哔哩哔哩, 小红书, 腾讯会议, 微信读书 and the system apps — and work the same on a real phone with the Android app's executor. They want the *Phone* switch on and a phone connected (`Connections → Phone` shows "MobileGym connected").

## Through a CLI: 飞书 (Feishu / Lark)

[lark-cli](https://github.com/larksuite/cli) is the official command-line tool for 飞书; the built-in `feishu` skill teaches the agent its shape (`lark-cli calendar +agenda`, `im +messages-send`, `task +create`, `docs +fetch`, JSON in, JSON out). Install it (`npm i -g @larksuite/cli`), log in once (`lark-cli auth login`), and — if the [sandbox](sentinel.md#the-sandbox) is on — share the tool and its login with the box:

```toml
[sandbox]
share_read_only = ["~/.nvm"]                          # node and lark-cli live here (or wherever `which lark-cli` points)
share = ["~/.lark-cli", "~/.local/share/lark-cli"]    # its config and encrypted tokens
```

The rest of your home directory stays invisible to commands. Every `lark-cli` call is a `shell` call, so it shows on an approval card in `ask` mode with the full command on it — reading your agenda is one tap, and a message to a colleague shows its exact text before it goes.

| Ask | What happens |
|---|---|
| 我今天飞书上有什么安排 | `lark-cli calendar +agenda --as user`; the events in a few lines, with what is next and how soon. |
| 项目群里今天上午聊了什么，给我三句话总结 | `im +chat-search` for the group, `im +chat-messages-list` for the window, then a summary — the messages themselves stay out of the answer unless you ask. |
| 帮我给王芳发一条飞书：周报我下午三点前发出来 | Finds her `open_id`, shows you the text on a card, `im +messages-send --user-id ou_… --text …` once you approve, with an idempotency key so a retry cannot send twice. |
| 明天下午两点跟张三、李四开个 30 分钟的需求评审会，写到飞书日历里 | `contact +search-user` for both, `calendar +create` with attendees; the title, time and attendees read back to you. |
| 把 workspace 里的 headphones.md 建成一份飞书文档发我 | `docs +create --markdown @headphones.md`; the link comes back in chat. |
| 我这周飞书上还有哪些任务没做完 | `task +get-my-tasks`, grouped by due date. |

## Through an MCP server: 高德地图 (Amap)

高德 runs an [MCP server](https://lbs.amap.com/api/mcp-server/summary) — geocoding, places, driving / transit / cycling / walking routes, distance, weather. Add it to `config.toml` with a free Web 服务 key from [console.amap.com](https://console.amap.com) kept in the vault (`nanomuse vault set AMAP_KEY`), and its twelve tools show up to the agent as `amap__maps_*`; the built-in `amap` skill knows which to call for what:

```toml
[[mcp.servers]]
name = "amap"
url = "https://mcp.amap.com/mcp?key={{vault:AMAP_KEY}}"
risk = "safe"
```

No browser, no phone, no screenshots: a question about a place is one or two tool calls, listed in the chat like any other.

| Ask | What happens |
|---|---|
| 从北京南站到国贸开车要多久，地铁呢 | `maps_geo` for both ends, `maps_direction_driving` and `maps_direction_transit_integrated`; a line each, and which it would take at that hour. |
| 国贸附近评分高的川菜馆，走过去十分钟以内的 | `maps_around_search` with a radius, `maps_search_detail` for the top few; three places, not a list. |
| 这周六杭州的天气适合爬山吗 | `maps_weather` for 杭州; yes or no, and why. |
| 上海市浦东新区世纪大道100号在哪个区，离虹桥机场多远 | `maps_geo`, `maps_regeocode`, `maps_distance`. |

## On the phone only

For apps with no API. One app:

| Ask | What happens |
|---|---|
| 打开微信，看看最上面三个聊天是谁、最后一条说了什么 | Opens 微信, reads the chat list, comes back with names, previews and times. Nothing is tapped inside a chat. |
| 给 blank. 回一句「好的，那明天见」 | Reads the chat first, types the text, and stops at 发送 — an approval card, once; then confirms the bubble is there. |
| 用 12306 查一下后天上海到杭州最早的三班高铁，二等座多少钱 | Sets 出发 / 到达 and the date, presses 查询车票, ticks 只看高铁/动车 when the list mixes in slow trains, reads the first three back. Search only. |
| 支付宝里我这个月的账单大概花了多少 | 支付宝: reads the bill page and sums it up; never taps 付款 or 转账. |
| 明天北京的天气怎么样，要带伞吗 | 天气 app: the forecast for tomorrow, in a sentence. (With the 高德 server configured it does not need the phone for this, and says so.) |

Across apps:

| Ask | What happens |
|---|---|
| 查一下明天北京到上海最早的高铁，然后把车次和时间发给 Boss | 12306 for the search, 微信 for the message; the send waits for your approval with the exact text on the card. |
| 看看小红书上「杭州两日游」最热的一篇笔记讲了什么，把要点记到笔记 app 里 | 小红书 to read, 笔记 to write. |
| 腾讯会议里下一个会是几点，提前十分钟在时钟里设个闹钟 | 腾讯会议 for the time, 时钟 for the alarm. |

## Without any of it

The agent as itself: the web, the workspace, commands, goals, routines, memory.

| Ask | What happens |
|---|---|
| 比较一下 Sony WH-1000XM6 和 Bose QuietComfort Ultra 哪个更适合长途飞行，写一份简短对比存到 headphones.md | `web_search`, `web_fetch`, a file in the workspace, a preview in Library. |
| 帮我看看这台机器还剩多少磁盘空间 | `shell` — stops on an approval card because it is a shell command. |
| 定一个目标：12 月去京都前把日语会话练起来，每天 30 分钟 | A goal with steps and a daily check-in, worked on in the background. |
| 每个工作日早上 7:30 给我一行今天的天气 | A routine; the message arrives as a notification with the app closed. |
| 记住我坐高铁只坐靠窗、不坐一等座 | Memory; used the next time trains come up. |

## Mixed

The reason the hands belong to one agent.

| Ask | What happens |
|---|---|
| 下周三去上海开会，帮我做个行程：查网上有什么值得顺路去的地方，用 12306 看看早上的高铁，把出发时间写进日历 | Web research for the plan, 12306 on the phone for real trains and prices (search only), a calendar draft for the departure, `trips/…/itinerary.html` in the workspace — the `trip-plan` skill. |
| 明天早上去北京南站坐 8 点的高铁，我几点得从家出发？把出发时间和车次发到飞书的「出差」群 | 高德 for the route from home (remembered) to the station at that hour, 12306 on the phone for the train, and one 飞书 message once you approve its text — MCP, screen and CLI in one run. |
| 看看飞书上下午那个会的地点，从公司过去怎么走，顺便查一下会不会下雨 | `calendar +agenda` for the place, 高德 for the route and the weather; a plan in three lines. |
| 看看微信里王芳最后说了什么，如果她问周末的事，查一下周六的天气再回她 | Reads the chat on the phone, decides what she asked, gets the forecast (高德, or the 天气 app), drafts a reply for you to confirm, sends it once you do. |
| 帮我查明天北京到上海的高铁，选一班上午 9 点前出发的，订好后提醒我付款 | 12306 to the order screen (you approve 提交订单), then a reminder to pay in the app within its time limit; the payment stays yours. |
| 把 Boss 刚发我的那条消息里的时间和地点整理进日历，再用高德看看要提前多久出发 | Reads the message on the phone, creates the event, checks the route. |

## Reading the trail

Every step is a row in the chat — `shell: lark-cli calendar +agenda --as user`, `mcp:amap.maps_direction_driving(…)`, `phone_act: tap "发送" at (318,742) in 微信 (wechat)` — and every approval card says what will be done and why it asks; on the phone itself a ripple marks the tap and a caption says what the agent is doing. `Activity` under the avatar keeps the audit log; `Permissions` shows the grants, which for phone steps are only ever *once*. On your own server, `nanomuse phone traces` lists every phone task and `nanomuse phone trace <id> -o trace.html` renders one as a page with every screen the operator saw and every tap drawn on it ([gui.md → Traces](gui.md#traces)).

Four built-in skills carry these habits — `feishu` and `amap` for the two services above, `train-tickets` and `phone-messages` for the phone — and `trip-plan` knows to look in 12306 when a phone is there and in 高德 when the server is. `Skills` in the app lists them; a folder of your own with the same name replaces one. Skills written for other agents in the [Agent Skills](https://agentskills.io) format drop into `<data_dir>/skills` as they are — Larksuite's own `lark-*` skills included.
