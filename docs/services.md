# Chinese services: what the agent can reach without a screen

The [ladder](gui.md#the-ladder) puts the phone's screen last. For that to mean anything, the first rung has to be real: the services a Chinese day runs on need a CLI or an MCP server the agent can actually call. This page is the list — what has been run, what has not, what we will not recommend — and the rule that keeps it honest:

> **Nothing enters the [showcase](showcase.md) until it has run inside the phone's root file system and left a trace.** A package that installs is not a service that works. "Runs" means the tool was called and answered; the transcript is at the bottom of this page.

The root file system is the Alpine Linux the local Android build unpacks on the phone ([local-runtime.md](local-runtime.md)), with Node 22 and Python 3.12 in it. Everything below was exercised in that image on an arm64 emulator (QEMU user-mode on the build machine) on 2026-09-24; PRoot itself and the phone's network are the two things the emulator does not exercise, and the checklist keeps a line for them.

## Tier 1 — verified

Run inside the rootfs, answered, in the showcase.

| Service | Through | Verified | Needs from the user | Skill |
|---|---|---|---|---|
| **12306** (trains) | [12306-mcp](https://github.com/Joooook/12306-mcp), a community MCP server over 12306's public timetable — `npx -y 12306-mcp`, stdio | Installed in the rootfs; a live query for 北京 → 上海 the next morning came back in 1.0 s with trains, seats and prices. Query only: the server cannot book | Nothing — no key, no login | `train-tickets` (searches here; books on the phone only when told to) |
| **飞书 / Lark** | [lark-cli](https://github.com/larksuite/cli), the official CLI — `npm i -g @larksuite/cli` | Installed and runs in the rootfs (1.0.96); on the build machine a configured install answers `lark-cli auth status` with its identities. Login is the owner's step: `lark-cli config init --new` once, then `lark-cli auth login`, both through a link in a browser | A 飞书 account; the two login steps, once | `feishu` |
| **高德地图** (maps, weather) | [高德 MCP Server](https://lbs.amap.com/api/mcp-server/summary), official — hosted at `https://mcp.amap.com/mcp?key=…`, or `npx -y @amap/amap-maps-mcp-server` | The package runs in the rootfs and lists its twelve tools; live calls go through the hosted URL with a key. No key was available on the build machine, so the live geocode and route calls are the owner's line in the checklist | A free Web 服务 key from console.amap.com, in the vault as `AMAP_KEY` | `amap` |
| **腾讯会议** | [tmeet](https://github.com/TencentCloud/tencentmeeting-cli), Tencent's official CLI (a Go binary, `npm i -g @tencentcloud/tmeet`) | Installed and runs in the rootfs (v1.0.18); `tmeet auth status` and `tmeet meeting create --help` answer. Login is an OAuth device flow the owner clicks through once (`tmeet auth login --no-browser` prints the link on the phone) | A 腾讯会议 account; the login, once | `tencent-meeting` |

The `device` MCP server (the phone's own clipboard, calendar, contacts, alarms, location, notifications, photos — [device.md](device.md)) is not a third-party service and is not listed; it is verified with the Android app.

## Tier 2 — to be run one by one

A server exists; it has not run inside the rootfs with a real key, or it has no skill yet. In the order we would try them.

| Service | Through | State | Why not yet |
|---|---|---|---|
| **快递100** (parcels) | [快递100 MCP Server](https://github.com/kuaidi100-api/kuaidi100-MCP), official — hosted (`https://api.kuaidi100.com/mcp/streamable?key=…`) or `npx -y @kuaidi100-mcp/kuaidi100-mcp-server` | The package runs in the rootfs and lists its four tools (`query_trace`, `estimate_time`, `estimate_time_with_logistic`, `estimate_price`); the `kuaidi100` skill is written against them. A live query needs an account: paid per tracking number, free trial on sign-up | No key on the build machine. Moves to tier 1 with one traced `query_trace` |
| **百度地图** | [@baidumap/mcp-server-baidu-map](https://lbsyun.baidu.com/faq/api?title=mcpserver/base), official (1.0.5 on npm) | Not run. Same shape as 高德; a second map only matters where one of them is wrong | Needs a key; 高德 covers the showcase |
| **腾讯位置服务** | [Official MCP Server](https://lbs.qq.com/service/MCPServer/MCPServerGuide/overview), hosted (`https://mcp.map.qq.com/sse?key=…`, also Streamable HTTP) — geocoder, place search, routes, IP location, weather | Not run | Needs a key with WebServiceAPI enabled; same reason as 百度 |
| **和风天气** | Community servers over the QWeather API (`hefeng-weather-mcp` on PyPI, others); no official server found | Not run. 高德's `maps_weather` gives the showcase its forecast; 和风 is for people who want hourly or air-quality data | Needs a project, a key id and an Ed25519 private key — a heavier setup than the others |
| **钉钉** | `dingtalk-mcp-server` (community, messages / todos / calendar); DingTalk's own agent platform is not an MCP server | Not run | Enterprise account and app registration; no showcase case needs it |
| **语雀** | `yuque-mcp-server` (community) over the 语雀 open API | Not run | Personal token; would slot into the `feishu`-style skill pattern in an afternoon |
| **百度网盘** | Announced MCP support; no package or endpoint we could confirm | Not run | Nothing to run yet |
| **携程 / 飞猪 / 饿了么** | Servers in the [阿里云百炼 MCP market](https://bailian.console.aliyun.com), hosted behind a 百炼 account | Not run. The showcase's hotel-budget case browses 携程 in the in-app browser instead — the third rung — because that works for anyone without an account with 百炼 | Requires a 百炼 account and the market's per-call billing; worth it for a hosted demo, not for the personal build |

## Tier 3 — not recommended

Listed so nobody asks.

| Service | Why |
|---|---|
| **微信** — any automation of it, including community "wechat MCP" servers | Against the terms of use; accounts get restricted. The agent reads and replies to 微信 on the phone's screen only when the user asks for exactly that, and none of it appears in public material |
| **小红书 MCP servers** | Community servers scrape a logged-in session; 小红书 bans the account. The screen does the same job when asked |
| **支付宝 / 微信支付** MCP servers | They exist for merchants (payments, refunds), not for a person's own account. Paying is the user's; the agent stops before it |
| Anything that needs the user's **password** in a config file | The vault holds keys and tokens; a login the tool cannot do itself with a device flow or a QR code is not a login the agent should hold |

## Adding one

An MCP server: a `[[mcp.servers]]` block in `config.toml` (or *Connections → MCP servers* in the app), key in the vault as `{{vault:NAME}}`, `risk` and `egress` set honestly, `reads_private_data = true` when the arguments carry the user's data (a tracking number, a phone number). A CLI: install it in the rootfs or share it with the sandbox on a computer (`sandbox.share_read_only` for the program, `share` for its login), then a skill that says which commands to run and what to ask before writes. `config/config.example.toml` has the blocks for 高德, 12306 and 快递100; [configuration.md](configuration.md#mcp-servers) explains the fields.

When it has run inside the rootfs and answered once, add the transcript below and move it up a tier.

## Verification log

Inside `nanomuse-rootfs:aarch64` (Alpine 3.21.8, Node 22.23.2, npm 10.9.1, Python 3.12.14, nanomuse 0.1.0), QEMU user-mode on x86_64, 2026-09-24. Mirrors switched with `nanomuse-mirror cn`. The probe is a 60-line Python script over the `mcp` client the agent itself uses: connect, `tools/list`, a few `tools/call`.

```
$ npm i -g 12306-mcp @larksuite/cli @tencentcloud/tmeet @amap/amap-maps-mcp-server @kuaidi100-mcp/kuaidi100-mcp-server
added 386 packages in 2m            (136 s under emulation; a phone is faster)
/usr/local/bin: 12306-mcp kuaidi100-mcp lark-cli mcp-amap tmeet …

== 12306-mcp (stdio)
connected in 15.5s · 8 tools
  get-current-date, get-stations-code-in-city, get-station-code-of-citys, get-station-code-by-names,
  get-station-by-telecode, get-tickets, get-interline-tickets, get-train-route-stations
$ get-current-date {}                                        (0.1s) → 2026-09-24
$ get-station-code-of-citys {"citys": "北京|上海"}            (0.1s) → {"北京":{"station_code":"BJP",…},"上海":{"station_code":"SHH",…}}
$ get-tickets {"date":"2026-09-25","fromStation":"北京","toStation":"上海","trainFilterFlags":"G",
               "earliestStartTime":7,"latestStartTime":9,"sortFlag":"startTime","limitedNum":3}   (1.0s)
G565 北京南 -> 上海虹桥 07:07 -> 13:12 历时：06:05   商务座: 无票 2156元 · 一等座: 无票 967元 · 二等座: 无票 576元
G549 北京南 -> 上海虹桥 07:13 -> 13:03 历时：05:50   商务座: 剩余16张票 2315元 · 一等座: 无票 967元 · 二等座: 无票 598元
G5   北京   -> 上海     07:40 -> 12:32 历时：04:52   商务座: 无票 2350元 · 一等座: 无票 1075元 · 二等座: 无票 672元 · 无座: 剩余19张票

== lark-cli
lark-cli version 1.0.96
$ lark-cli auth status → {"ok": false, "error": {"type": "config", "subtype": "not_configured",
   "hint": "run `lark-cli config init --new` … open it in a browser to complete setup."}}      (the owner's step)

== tmeet
tmeet version v1.0.18
$ tmeet auth status → Not logged in. Please use 'tmeet auth login' to authenticate.            (the owner's step)
$ tmeet meeting create --help → --subject, --start, --end (ISO 8601), --invitees, --password, --waiting-room,
   --meeting-type / --recurring-type / --until-type / --until-count / --until-date, --join-type, --auto-record-type, --auto-asr …

== @amap/amap-maps-mcp-server (stdio, AMAP_MAPS_API_KEY set to a placeholder — tools only)
connected · 12 tools: maps_regeocode, maps_geo, maps_ip_location, maps_weather, maps_search_detail, maps_bicycling,
  maps_direction_walking, maps_direction_driving, maps_direction_transit_integrated, maps_distance, maps_text_search, maps_around_search

== @kuaidi100-mcp/kuaidi100-mcp-server (stdio, KUAIDI100_API_KEY set to a placeholder — tools only)
connected in 4.1s · 4 tools: query_trace, estimate_time, estimate_time_with_logistic, estimate_price
  (the server prints one non-JSON line, "MCP server is running…", on stdout first; the client logs it and carries on)
```

On the build machine itself (x86_64, Node 20) the same 12306 query answered in 3.5 s including `npx` start-up, and `lark-cli auth status` on the configured install reported the bot identity ready and the user identity due for a refresh — which is what the `feishu` skill checks for before doing anything in the user's name.
