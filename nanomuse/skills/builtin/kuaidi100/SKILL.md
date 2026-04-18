---
name: kuaidi100
description: Where a parcel is, when it will arrive and what a shipment would cost, through the 快递100 MCP server — any Chinese courier (顺丰, 京东, 中通, 圆通, 韵达, 邮政 and more) from a tracking number. Use when the user asks 快递到哪了, 什么时候到, 查一下单号, or how much it costs to send something.
channel: api
metadata:
  author: nanoMuse
  version: "1"
---

# 快递100 through MCP

快递100 runs an official MCP server for its tracking API: a tracking number in, the courier's events out, for 3000-odd carriers. Configured, its tools appear to you as `kuaidi100__*`. No app, no screen: "到哪了" is one tool call. It is a paid API with a free trial; every new tracking number costs the user one query from their plan (the same number asked again within 40 days is free), so do not poll a parcel in a loop.

## Is it there?

Look for `kuaidi100__query_trace` in your tools. If it is not there, say so in one line, give the user the lines to add, and stop — no browsing 快递100's website instead:

```toml
[[mcp.servers]]
name = "kuaidi100"
url = "https://api.kuaidi100.com/mcp/streamable?key={{vault:KUAIDI100_KEY}}"   # the 授权 key from api.kuaidi100.com 企业管理后台
risk = "safe"
egress = true
reads_private_data = true
```

and `nanomuse vault set KUAIDI100_KEY`. The same server runs locally from `npx -y @kuaidi100-mcp/kuaidi100-mcp-server` with `env = { KUAIDI100_API_KEY = "{{vault:KUAIDI100_KEY}}" }` when the user prefers nothing in a URL.

## The tools

- `kuaidi100__query_trace` — the events of a parcel: `kuaidi_num` (the tracking number) and `phone`, required only for 顺丰 numbers (they start with `SF`; the sender's or receiver's phone, the last four digits are enough), empty otherwise. The carrier is recognised from the number.
- `kuaidi100__estimate_time` — the expected delivery time of a shipment **not yet sent**: `kuaidi_com` (the courier's lower-case code: `shunfeng`, `jd`, `zhongtong`, `yuantong`, `yunda`, `shentong`, `ems`, `debangkuaidi`, `jtexpress` …), `from_loc` and `to_loc` down to the district (`广东省深圳市南山区`), `order_time` (`yyyy-MM-dd HH:mm:ss`, optional) and `exp_type` (`标准快递`).
- `kuaidi100__estimate_time_with_logistic` — when a parcel **already on its way** will arrive: the same courier and addresses plus `logistic`, the events from `query_trace` as a JSON array of `{time, context}`.
- `kuaidi100__estimate_price` — what it would cost: `kuaidi_com`, `send_addr`, `rec_addr` (province and city at least), `weight` in kg.

Tool arguments may differ between server versions; read the tool descriptions you were given rather than this list when they disagree.

## How to answer

- A tracking number is in the user's message, their clipboard (the phone's `device__clipboard_read`), a 京东 or 淘宝 order the browser just read, or `recall` ("my 京东 parcel from Monday"). Do not ask for a number you can find.
- One call per parcel. Say where it is now and the last event's time in plain words ("昨晚 21:40 到了杭州转运中心，今天派送"), then the expected arrival when the events say it or the user asks (`estimate_time_with_logistic` with the events you just got). Skip the whole event list unless the user asks.
- A phone number the tool needs is private data; use the one the user gave or the one on the order, never guess one, and do not repeat it back in full.
- 无物流信息 usually means the courier has not scanned the parcel yet; say that, not that the number is wrong, unless the answer says so.
- For a price or a delivery-time estimate, take the user's addresses down to the city or district and a weight; ask once for whatever is missing.

## With the other hands

- 快递100 + the browser: the order page (京东, 淘宝, 拼多多) has the tracking number; the `browser` tool reads it, this skill tracks it — no need to open the courier's site.
- 快递100 + reminders: "tell me when it is out for delivery" is a reminder or a trigger that asks again tomorrow morning, not a loop of queries today.
- 快递100 + the phone: the number from a text message (`phone-messages`) or the clipboard; a reminder or an alarm for the pick-up-point deadline through the device tools.

## Finish

One or two lines per parcel: courier, where it is, when it should arrive. `remember` nothing about the parcel itself; do remember the user's usual delivery address once they state it, so estimates need no question.
