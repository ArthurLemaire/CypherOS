---
name: train-tickets
description: Trains in China through the 12306 MCP server — routes, dates, options, connections and stops with no screen; booking only on the user's word, in the 12306 app on their phone, stopping before payment. Use when the user asks about 火车票 / 高铁 / 12306 or a train between two cities.
channel: mixed
metadata:
  author: nanoMuse
  version: "2"
---

# Train tickets (12306)

Two hands, in this order. **Searching** is done with the `12306__*` tools — a community MCP server ([12306-mcp](https://github.com/Joooook/12306-mcp)) that reads 12306's public timetable and seat counts; no login, no browser, no phone, nothing typed into an app. **Booking** has no API a personal agent may use; it happens on the phone's screen with `phone_task`, and only when the user has picked a train and said to book it.

## Is the server there?

Look for `12306__get-tickets` in your tools. If it is not there, say so in one line, give the user the lines to add to `config.toml`, and — when a phone is connected — offer the search on the phone's screen instead (the old way, below); otherwise stop:

```toml
[[mcp.servers]]
name = "12306"
command = "npx"
args = ["-y", "12306-mcp"]
risk = "safe"
egress = true
```

Node is needed for `npx`; the phone's own runtime has it.

## What you need

- From, to, the date, and whether it must be 高铁/动车 (G/D) or any train. The user's habits from `recall` (preferred stations, morning or evening, seat class, who travels) count as answers. Ask for the rest with **one** `ask_user` call.
- Passengers, seat class and budget only matter for booking; do not ask for them to run a search.

## Searching

1. `12306__get-current-date` first whenever the user said 明天 / 后天 / 下周三 — the server's date is the one that counts, not yours.
2. `12306__get-station-code-of-citys` with `citys` = `北京|上海` gives the code that stands for a whole city (every station in it). A specific station (`北京南`, `上海虹桥`): `12306__get-station-code-by-names`. All the stations of a city: `12306__get-stations-code-in-city`.
3. `12306__get-tickets` with `date`, `fromStation`, `toStation` (names or codes), and the filters that fit: `trainFilterFlags` (`G` 高铁/城际, `D` 动车, `GD` both, `Z`/`T`/`K` the slow ones, `F` 复兴号), `earliestStartTime` / `latestStartTime` (hours, 0–24), `sortFlag` (`startTime`, `arriveTime`, `duration`), `limitedNum` (ask for 5–8, not the whole day). One call; a second only if the first came back empty (widen the hours or drop the flag).
4. No direct train: `12306__get-interline-tickets` with the same arguments, `middleStation` optional — the first ten connections. Where a train stops and when: `12306__get-train-route-stations` with `trainCode` and `departDate`.

Then, in your own words, the options that fit — three at most: 车次, 出发站 and time, 到达站 and time, 历时, the seat the user wants with its price and whether there are seats left (剩余 N 张 / 有 / 无). Say which you would take and why (earliest, shortest, cheapest that still has seats). Seat counts move by the minute; say so when the number is small.

## Booking

Only when the user has picked a train **and** said to book it — and only with a phone connected (the system prompt says whether one is). Without a phone, say the train, date and price and that the booking is theirs to make in the app; offer a reminder for when sales open or a calendar entry.

- `phone_task`, `app` = `铁路12306`: open the chosen train on the chosen date, pick the seat class and the passengers the user named, and stop on the order confirmation screen — read back the train, date, passengers, seats, total. The goal must say: 停在提交订单页，不要点「提交订单」或任何支付按钮。
- Show the user that summary and ask whether to place the order. Only with a yes, one more `phone_task` for 提交订单 — Sentinel will ask the user again for that tap; that is expected, not an error. Payment (支付) is the user's: say the order is placed and waiting to be paid in the app, and stop.
- Never enter a password, a verification code or an ID number; when the app asks for one, stop with what the screen says and let the user do it.

## Searching on the screen (fallback)

Only when the server is not configured and a phone is connected. One `phone_task`, `app` = `铁路12306`, with a goal like:

> 在 12306 首页把出发地设为「北京」、目的地设为「上海」、日期设为 9月25日，点「查询车票」。在结果页读出按发车时间最早的前 5 班：车次、发车站和发车时间、到达站和到达时间、历时、二等座价格和余票。只查询，不要点任何车次进入下单。

Rules for the operator you can put in `context`: the left station is 出发, the right one 到达, the swap icon sits between them; the date is picked on a calendar page; 筛选 / 只看高铁 narrow the list; the results list scrolls. Prices on the list page are the lowest class ("¥xxx 起"); say so.

## With the other hands

- 12306 + 高德: the route to the station at that hour (the `amap` skill) and the train make one plan: leave home at 07:10, G1 at 08:00.
- 12306 + 飞书 / 腾讯会议: the train that fits a meeting's time; the chosen 车次 and times go to the colleague or the group through lark-cli, once the user approves the text.
- 12306 + the calendar and reminders: an event for the departure (station, 车次, seat), a reminder to pay within the app's time limit after 提交订单.

## Finish

- Reply with the trains or the order in a few lines: train, date, times, price, state (查询 / 已提交待支付). Save nothing unless asked; if the user wants it kept, `trips/<route>-<date>.md` in the workspace.
- `remember` the stations and times the user keeps choosing, so the next search needs no question.
