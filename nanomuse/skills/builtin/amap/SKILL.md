---
name: amap
description: Places, routes, travel times, distances and weather in China through the 高德地图 (Amap) MCP server. Use when the user asks how far, how long, how to get somewhere (car, transit, bike, foot), what is near a place, or about the weather in a Chinese city.
metadata:
  author: nanoMuse
  version: "1"
---

# 高德地图 (Amap) through MCP

高德 publishes an MCP server with twelve tools; configured, they appear to you as `amap__maps_*`. No browser, no phone, no screenshots: a question about a place is one or two tool calls.

## Is it there?

Look for `amap__maps_geo` in your tools. If it is not there, say so in one line and give the user the four lines to add to `config.toml`, then stop:

```toml
[[mcp.servers]]
name = "amap"
url = "https://mcp.amap.com/mcp?key={{vault:AMAP_KEY}}"   # a free Web 服务 key from console.amap.com
risk = "safe"
```

and `nanomuse vault set AMAP_KEY`. Without Node, the hosted URL is the way; with it, `command = "npx"`, `args = ["-y", "@amap/amap-maps-mcp-server"]`, `env = { AMAP_MAPS_API_KEY = "{{vault:AMAP_KEY}}" }` does the same.

## The tools

- `amap__maps_geo` — an address or a landmark (`北京南站`, `上海市浦东新区世纪大道100号`) → coordinates `lng,lat`; `amap__maps_regeocode` the other way round. Almost everything else wants coordinates, so this comes first.
- `amap__maps_text_search` — places by keyword (`咖啡`, `汉庭酒店`) in a `city`; `amap__maps_around_search` — the same within `radius` metres of a `location`; `amap__maps_search_detail` — one place's details by its `id` (opening hours, rating, phone, address).
- `amap__maps_direction_driving`, `amap__maps_direction_walking`, `amap__maps_bicycling` — a route between two coordinates with distance, duration and the steps; `amap__maps_direction_transit_integrated` — bus, metro and train together, and across cities with `city` and `cityd`.
- `amap__maps_distance` — just the distance and time between points (`type` 1 = driving, 3 = straight line).
- `amap__maps_weather` — today and the next few days for a `city` name or adcode.

Coordinates are `经度,纬度` (longitude first, GCJ-02). Durations come in seconds and distances in metres: say them as minutes and kilometres.

## How to answer

- Resolve both ends first, then one route call per mode the user cares about. When they did not say how they travel, compare transit and driving in one line each and say which you would take at that hour.
- A "what's near" question: geocode the centre, one `around_search`, then give three places at most with what makes each worth it (rating, distance, open now), not the whole list.
- Travel time is an estimate for now; for a departure later or tomorrow say so, and for a real day-of-travel plan add slack.
- Weather goes into plans the user is making — an outdoor day, a trip — without being asked when it changes the plan (rain on the day of the hike).

## With the other hands

- 高德 + 12306: the route to the station (this skill) and the train itself (the `train-tickets` skill on the phone) make one plan: leave home at 07:10, G1 at 08:00.
- 高德 + 飞书: a route or an address the user wants to share goes to a colleague with the `feishu` skill; a meeting's location is checked before the event is created.
- 高德 + the workspace: a day's itinerary with places, times and the routes between them is a page in `trips/`, written with the `trip-plan` skill; the coordinates and distances come from here.

## Finish

A few lines: where, how far, how long, by what, and the weather when it matters. Save nothing unless asked. `remember` the user's home and workplace once they name them, so that the next "how long to get to …" needs no question.
