---
name: inbox-triage
description: Go through recent mail and sort it into needs-a-reply, waiting-on-others, to-do and can-ignore, with draft replies ready for review. Use when the user asks to triage, sort, catch up on or clear their inbox — never to send anything on its own.
metadata:
  author: OpenMuse
  version: "1"
---

# Inbox triage

Needs the mail connector (`read_emails`). If it is not available, say so and stop.

## Read

- `read_emails` with `unread_only=true` first (up to 50). If there are fewer than 10, read the last 3 days with `unread_only=false` too, so nothing waiting since yesterday is missed.
- For each sender the user has written to before, `contacts` action=search gives the name and company; use names, not addresses, in what you write.
- `recall` "inbox" and "email" for the user's rules: senders that always matter, newsletters they keep, how they like replies to sound.

## Sort

Every message lands in exactly one group:

1. **Reply needed** — someone asked the user something, or is waiting.
2. **Waiting on them** — the user asked, no answer yet; note how long.
3. **To do** — no reply needed, but an action is: pay, book, read a document, show up somewhere.
4. **Read later** — newsletters, notifications, receipts.
5. **Ignore** — clear spam, expired offers, automated noise.

Threads with the same subject count once. Anything that mentions money, a deadline, a contract or health goes to the top of its group.

## Draft, do not send

- For each *Reply needed* mail, write a reply the user could send as is: their voice (from memory), short, answering the actual question. Put all drafts in one file, `mail/drafts-YYYY-MM-DD.md`, one section per thread with *To*, *Subject*, the draft, and a one-line note on what you were unsure about.
- Do not call `send_email` in this job unless the user tells you, mail by mail, to send. A reply the user approves later is a separate step.

## Report

In chat, a short list per group: sender name — subject — what it is about in a few words (groups 4 and 5 as counts only). Then the file with the drafts, and the two or three things that should not wait. Deadlines or events found in the mail: offer to set a `reminders` or draft a `calendar` event; do it only when the user says yes.

If the user corrects a sorting decision ("newsletters from X I read"), `remember` it so the next triage gets it right.
