---
name: weekly-review
description: Look back at the past week and set up the next one — calendar, mail, goals and files in one page, with a short plan. Use when the user asks for a weekly review, a week in review, "how did my week go" or to plan next week.
metadata:
  author: OpenMuse
  version: "1"
---

# Weekly review

One page, `reviews/YYYY-Www.html` in the workspace (ISO week), and a five-line summary in chat. Overwrite the page if it exists for the same week.

## Gather (all read-only)

1. **Calendar** — `calendar` action=agenda for the past 7 days, then for the next 7. Note what took the most time, what repeats, and anything next week that needs preparing.
2. **Goals** — `goals` action=list; for each active goal, `get` it and read the notes on steps done this week and the next step.
3. **Mail** (only if `read_emails` is available) — the last 7 days, `unread_only=false`; look for threads that are waiting on the user and threads the user is waiting on. Never quote a whole mail; a line per thread is enough.
4. **Files** — `files` action=list on the workspace; the ones modified this week are what got made.
5. **Memory** — `recall` "weekly review" for how the user liked past reviews (length, tone, what to leave out).

Do not ask the user questions before gathering. Missing connectors are not a problem: leave that section out and say so in one line.

## Write

The page has these sections, in this order, with nothing else:

- **The week in one line.**
- **Done** — what got finished (goal steps, files made, meetings that mattered). Bullet points, past tense, no praise.
- **Still open** — waiting on the user / waiting on others, with the person's name from `contacts` when there is one.
- **Next week** — the calendar's fixed points, then the two or three things that would matter most, as checkboxes. Prefer the goals' next steps.
- **Goals** — one line per goal: progress and the next step; flag anything overdue.

Self-contained HTML, inline CSS, readable on a phone, no external resources. Dates as "Mon 3 Mar", not ISO, in the body.

## Finish

Reply with the one-line summary, the three "next week" items, and the page's name. Then ask one question at most — usually whether to turn the "next week" items into a goal or reminders. If the user says the review should be different next time, `remember` that.
