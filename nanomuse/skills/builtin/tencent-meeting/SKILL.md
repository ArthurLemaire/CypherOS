---
name: tencent-meeting
description: The user's 腾讯会议 via the official tmeet CLI — upcoming meetings, creating, changing or cancelling one, inviting people, then the recording, minutes, transcript and attendance. Use when the user mentions 腾讯会议, a 会议号, a 会议链接, 纪要 or 录制, or wants a meeting set up or looked up.
channel: cli
metadata:
  author: nanoMuse
  version: "1"
---

# 腾讯会议 through tmeet

腾讯会议 has an open platform, and [`tmeet`](https://github.com/TencentCloud/tencentmeeting-cli) — Tencent's own CLI, installed with `npm i -g @tencentcloud/tmeet` — wraps it. This is done with `shell`, not on the phone's screen. Every command prints JSON; add `--compact` to list and query commands to keep only the fields that matter, and `--format json-pretty` when you want to show the user the raw answer.

## Is it there?

`shell`: `tmeet auth status`. If the command is missing or it says the user is not logged in, say so in one line and stop: logging in is the user's job (`tmeet auth login` opens a browser for a QR code — on the phone, `tmeet auth login --no-browser` prints the link to open). Do not install it or log in for them. In a sandbox on a computer the CLI and its credentials exist only when the user shared them (`sandbox.share_read_only` for the tool, `sandbox.share = ["~/.tmeet"]` for the login); "command not found" then means those two lines are missing.

Times are ISO 8601 with the offset: `2026-09-25T14:00+08:00`. Compute them from the user's words and the current date in the system prompt; when the day is ambiguous (下周三 near a weekend), say the date you took.

## Reading

- What is coming: `tmeet meeting list --compact` — the meetings in progress or about to start, with 会议号 (`meeting_code`), subject, start and end, the join link.
- One meeting: `tmeet meeting get --meeting-id <id> --compact`; by 会议号 or subject: `tmeet meeting search --keyword "周例会" --compact`, with `--start` / `--end` for a window.
- Past meetings: `tmeet meeting list-ended --start … --end … --compact`.
- Who is invited: `tmeet meeting invitees-list --meeting-id <id>`. Who came: `tmeet report participants --meeting-id <id> --compact`.
- After the meeting: `tmeet record list --meeting-id <id>` for the recordings; `tmeet record smart-minutes --record-file-id <id>` for the AI minutes; `tmeet record transcript-search --record-file-id <id> --keyword "预算"` to find where something was said, `transcript-paragraphs` to read around it. `tmeet minutes search --keyword …` finds 元宝纪要 by words.
- A colleague: `tmeet contact search --keyword 张三` (the enterprise directory; only when the user's account is in an enterprise).

Read what the JSON says. A meeting the CLI does not return does not exist for you; do not guess a 会议号.

## Writing

Every write reaches other people's calendars. Before the call, show the exact subject, date, time span and invitees and ask with one `ask_user`; run only what they approved.

- Create: `tmeet meeting create --subject "需求评审" --start 2026-09-25T14:00+08:00 --end 2026-09-25T14:30+08:00`. The answer has the 会议号 and the join link — those are what the user wants to pass on. Recurring meetings and settings (waiting room, mute on entry) are flags of the same command; `tmeet meeting create --help` lists them.
- Change: `tmeet meeting update --meeting-id <id> --subject … --start … --end …`. Cancel: `tmeet meeting cancel --meeting-id <id>` — only when the user said to cancel that very meeting.
- Invite: `tmeet meeting invitees-add --meeting-id <id> --userids …` after `contact search` for the ids; `invitees-remove` the same way.

Never use `tmeet control …` (calling, kicking, the waiting room) unless the user is in the meeting and asks for exactly that; never `tmeet record permission-apply-commit` without the user having seen the `prepare` preview. Sentinel shows every shell command on an approval card; that is expected.

## With the other hands

- 腾讯会议 + 飞书: the meeting's 会议号 and link go to the group or the colleague through lark-cli (the `feishu` skill) — one message, its text approved first. A 飞书 calendar event with the link as the location keeps both sides in step.
- 腾讯会议 + the calendar: check the user's own calendar for the slot before creating (`calendar` action=search); afterwards a reminder ten minutes before, or an alarm through the phone when the phone is there.
- 腾讯会议 + the workspace: the smart minutes and the decisions from the transcript become `meetings/YYYY-MM-DD-<slug>.md`, the way the `meeting-prep` skill keeps a brief.

## Finish

Reply in a few lines: the meeting (subject, time, 会议号, link), or what was read (the next meeting and when; the three points of the minutes). Do not paste whole transcripts into the answer; give the gist and offer the rest. `remember` the user's usual meeting length and who they meet with most, so the next request needs fewer questions.
