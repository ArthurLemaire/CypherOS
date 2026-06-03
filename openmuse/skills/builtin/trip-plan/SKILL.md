---
name: trip-plan
description: Plan a trip end to end — itinerary by day, a packing list to tick off, a budget, and the calendar checked for conflicts — as pages in the workspace. Use when the user is going somewhere for more than a day and wants a plan, an itinerary or a packing list.
metadata:
  author: OpenMuse
  version: "1"
---

# Trip plan

Everything goes in `trips/<place>-<yyyy-mm>/` in the workspace: `itinerary.html`, `packing.html`, and `budget.csv` when money is discussed.

## Before anything

- You need: where, the dates (or roughly when and for how long), who is going, and what the trip is for (work, holiday, visiting someone). Ask for what is missing with **one** `ask_user` call — not one question at a time.
- `recall` the user's travel preferences (pace, budget, dietary needs, kids, mobility, what they hated last time). Follow them without asking again.
- `calendar` action=search for the trip dates: anything already on the calendar during the trip is a conflict to mention up front.

## Research

- `web_search` for: how to get there and around, the weather in that season, opening days of the two or three things worth seeing, and anything that must be booked ahead. Two or three searches, then stop; `web_fetch` a page only when the search result is not enough.
- Prices and times only from pages you actually read. If you did not find something, say "check" next to it rather than inventing a figure.

## Itinerary (`itinerary.html`)

- One card per day: date and weekday, the area of town, morning / afternoon / evening, travel time between places, one alternative for bad weather.
- The first day is arrival and settling in; the last day ends when the transport leaves. Do not overfill: two anchors a day and free time.
- A "Before you go" box: bookings, documents, connections to arrange, with dates.
- Self-contained HTML, inline CSS, readable on a phone; no external resources.

## Packing list (`packing.html`)

- Grouped (documents, clothes for the weather you found, tech, toiletries, for the kids…), each item a checkbox that stays ticked when the page is reopened (localStorage).
- Sized to the trip: the number of days, the weather, laundry or not.

## Budget (`budget.csv`, when asked or when the user mentioned money)

- Columns: item, when, estimated, currency, booked (yes/no), note. One row per transport leg, night, and day of food; totals the user can change.

## Finish

- Reply with the shape of the trip in three or four lines and the file names; point out the calendar conflicts and the two things to book first.
- Offer, in one line, to make a goal from the "Before you go" list so the bookings get done and checked in on; if the user agrees, `goals` action=create with those steps and the departure date as the target.
- Never book, pay or send anything yourself; drafting an event with `calendar` action=draft for the departure is fine.
