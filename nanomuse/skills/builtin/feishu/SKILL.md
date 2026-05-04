---
name: feishu
description: The user's 飞书 / Lark through its command-line tool (lark-cli) — agenda, people and groups, reading and sending messages, events, tasks, documents — with no app open. Use when the user mentions 飞书, Lark, a 群, a 日程 or a 飞书文档, or wants a colleague told something.
metadata:
  author: nanoMuse
  version: "1"
---

# 飞书 (Feishu / Lark) through lark-cli

飞书 has an API, and `lark-cli` (the official CLI from Larksuite) wraps it; this is done with `shell`, not on the phone's screen. Every call prints JSON: `ok` says whether it worked, `data` holds the result, `error.message` says what went wrong. Read the JSON, never the user's screen.

## Is it there?

`shell`: `lark-cli auth status` — `identities.user.available` must be true for anything done in the user's name (their agenda, their messages). If the command is missing or the user identity is not logged in, say so in one line and stop; logging in is the user's job (`lark-cli auth login` opens a browser). Do not try to install it or to log in for them. In a sandbox the CLI and its login only exist when the user shared them (`sandbox.share_read_only` / `sandbox.share` in config.toml); the error then says "command not found" — tell the user which two lines to add.

## Reading

- Today's schedule: `lark-cli calendar +agenda --as user` (a date: `--date 2026-09-25`; a range with `--start` / `--end`).
- Free time for a meeting: `lark-cli calendar +freebusy --user-ids ou_… --start … --end …`.
- A person: `lark-cli contact +search-user --query 张三 --as user` → their `open_id` (`ou_…`). A group: `lark-cli im +chat-search --query 项目群 --as user` → `chat_id` (`oc_…`). Take the one match; with several, ask the user which with one `ask_user`, do not guess.
- What was said: `lark-cli im +chat-messages-list --chat-id oc_… --as user` (a DM: `--user-id ou_…`; `--start-time` / `--end-time` for a window). `lark-cli im +messages-search --query 周报 --as user` across chats.
- Tasks: `lark-cli task +get-my-tasks --as user`. A document: `lark-cli docs +fetch --doc <url or token>` gives its text.
- Add `--jq '<expr>'` to keep the output small (`--jq '.data[] | {summary, start_time}'`), and `--format table` when you want to show a list to the user as is.

## Writing

Every write is something the user says to other people. Before the call, show the exact text and the recipient and ask with one `ask_user`; send only what they approved, word for word.

- A message: `lark-cli im +messages-send --chat-id oc_… --text "…" --as user` (a DM: `--user-id ou_…`; longer or formatted: `--markdown "…"`). Add `--idempotency-key <something unique>` so a retried command cannot send twice.
- A reply in a thread: `lark-cli im +messages-reply --message-id om_… --text "…" --as user`.
- An event: `lark-cli calendar +create --summary "…" --start 2026-09-25T14:00:00+08:00 --end 2026-09-25T15:00:00+08:00 --attendee-ids ou_a,ou_b --as user`.
- A task: `lark-cli task +create --summary "…" --due 2026-09-26 --assignee ou_… --as user`.
- A document: `lark-cli docs +create --title "…" --markdown @notes.md --as user` from a file in the workspace.

Commands the CLI marks *high-risk-write* (deleting an event, removing members, anything with `--yes`) refuse to run without `--yes`; add it only after the user has said yes to that very action, and never to a command that was not asked for. Sentinel will show the shell command on an approval card; that is expected.

## With the other hands

- 飞书 + 高德: plan the route or check the weather with the `amap` skill, then put the result in a message or an event description.
- 飞书 + the phone: apps that have no API (12306, 微信, 支付宝) are done with `phone_task`; the outcome — the train, the payment made — goes to the colleague through lark-cli.
- 飞书 + the workspace: a brief, a comparison, a page you wrote becomes a document with `docs +create` or an attachment with `im +messages-send --file`.

## Finish

Reply with what was read or done in a few lines: the messages sent (to whom, first words), the event (title, time, attendees), the task (title, due). Do not paste whole chat histories into the answer; give the gist and offer the rest. `remember` who the user writes to most and which groups matter, so that next time the search is shorter.
