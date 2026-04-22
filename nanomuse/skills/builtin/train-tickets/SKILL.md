---
name: train-tickets
description: Look up and book trains in the 12306 app on the user's phone — search a route and date, compare the options, take a booking to the order screen and stop before it is placed or paid. Use when the user asks about 火车票 / 高铁 / 12306 or a train between two cities.
channel: gui
metadata:
  author: nanoMuse
  version: "1"
---

# Train tickets (12306 on the phone)

12306 has no API a personal agent may use; this is done on the phone's screen with `phone_task`. If no phone is connected (the system prompt says so), say that in one line and offer the web instead of pretending.

## What you need

- From, to, the date, and whether it must be 高铁/动车 (G/D) or any train. The user's habits from `recall` (preferred stations, morning or evening, seat class, who travels) count as answers. Ask for the rest with **one** `ask_user` call.
- Passengers, seat class and budget only matter for booking; do not ask for them to run a search.

## Searching

One `phone_task`, `app` = `铁路12306`, with a goal like:

> 在 12306 首页把出发地设为「北京」、目的地设为「上海」、日期设为 9月25日，点「查询车票」。在结果页读出按发车时间最早的前 5 班：车次、发车站和发车时间、到达站和到达时间、历时、二等座价格和余票。只查询，不要点任何车次进入下单。

Then, in your own words, give the user the options that fit (time, price, direct or not), three at most, and say which you would take and why. Prices on the list page are the lowest class ("¥xxx 起"); say so.

Rules for the operator you can put in `context`: the left station is 出发, the right one 到达, the swap icon sits between them; the date is picked on a calendar page; 筛选 / 只看高铁 narrow the list; the results list scrolls.

## Booking

Only when the user has picked a train **and** said to book it.

- `phone_task` again: open the chosen train, pick the seat class and the passengers the user named, and stop on the order confirmation screen — read back the train, date, passengers, seats, total. The goal must say: 停在提交订单页，不要点「提交订单」或任何支付按钮。
- Show the user that summary and ask whether to place the order. Only with a yes, one more `phone_task` for 提交订单 — Sentinel will ask the user again for that tap; that is expected, not an error. Payment (支付) is the user's: say the order is placed and waiting to be paid in the app, and stop.
- Never enter a password, a verification code or an ID number; when the app asks for one, stop with what the screen says and let the user do it.

## Finish

- Reply with the trains or the order in a few lines: train, date, times, price, state (查询 / 已提交待支付). Save nothing unless asked; if the user wants it kept, `trips/<route>-<date>.md` in the workspace.
- If the trip is part of a plan, offer a `calendar` draft for the departure and a reminder to pay within the app's time limit.
