---
name: meeting-prep
description: Prepare for a meeting — who is in it, what was last said with them, what the user owes them and wants from them — as a one-page brief. Use when the user asks to prepare for or get ready for a meeting, a call or a visit; a trigger can run it before every meeting with a client.
metadata:
  author: OpenMuse
  version: "1"
---

# Meeting prep

A brief at `meetings/YYYY-MM-DD-<slug>.md` in the workspace, and its gist in chat. Works with any of the connectors; the more are there, the fuller the brief.

## Find the meeting

- If the user named it, `calendar` action=search for it; otherwise `calendar` action=agenda for today and tomorrow and take the next one that has other people in it. If nothing fits, ask with one `ask_user`: which meeting, and with whom.
- A trigger (kind=event) gives you the event as context: use it as is, do not search again.

## The people

- Each attendee: `contacts` action=search by name or address — company, role, how the user knows them. Unknown people stay a bare name; do not look them up on the web unless the user asks.
- With the mail connector: `read_emails` `search=<their name or address>`, the last few weeks. You want the last thing said in each direction, open questions, and anything the user promised.
- `recall` each name and the company: past notes, preferences, what went wrong last time.

## The matter

- Related files in the workspace: `files` action=search for the company, the project or the meeting's title; list the two or three that matter with a one-line note.
- Active `goals` that mention the people or the topic: the current step is what the user probably wants out of the meeting.

## The brief (Markdown)

1. **When and where** — from the event: time, place or link, duration.
2. **Who** — one line per person: name, role, company, the relationship in a few words.
3. **Where things stand** — the last exchange, the open questions, promises made (by whom, when).
4. **What you want from it** — two or three outcomes, drawn from goals and the last exchange; phrase them as sentences the user could say.
5. **To bring / to have read** — files, numbers, decisions.
6. **Watch out** — anything from memory or mail that would embarrass (a missed deadline, a name they get wrong).

A page, not a report. Nothing the sources did not say; a section with nothing in it is left out.

## Finish

Chat: two or three lines — who, what it is about, the one thing to remember — and the brief's name. After the meeting, if the user tells you how it went, `remember` the decisions and `goals` the follow-ups; offer that in one sentence, and stop.
