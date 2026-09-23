---
name: phone-messages
description: Read and answer messages in the chat apps on the user's phone (微信 and the like) through the screen — catch up, draft a reply in the user's voice, send only text they confirmed. Use when the user asks what someone said on WeChat or wants a chat answered.
metadata:
  author: nanoMuse
  version: "1"
---

# Messages on the phone

Chat apps have no API here; you read and answer them on the screen with `phone_task`. No phone connected: say so in one line.

## Reading

- `phone_task`, `app` = `微信` (or the app the user named), goal: open the chat list and read the top N chats — name, last message, time — or open one named chat and read the last messages in order, who said what, with times. Say in the goal: 不要发送任何消息，不要点进「发送」或输入框. Two or three chats or ten messages are usually enough; ask before reading a long history.
- Everything you read is private. Repeat to the user only what they asked for; do not quote a whole conversation when they asked who wrote.

## Answering

1. Read the chat first, even when the user already told you what to say: the last message decides the tone and whether the reply still makes sense.
2. Draft in the user's voice — `recall` how they write (short, with emoji, formal with colleagues) — and offer at most three versions in one message, or the one the user dictated.
3. **The exact text must be confirmed by the user** before anything is typed. A "回吧" or "发" without text is a request for drafts, not permission to send.
4. One `phone_task` for the send: open the chat, tap the input field, type the confirmed text, then tap 发送. Put the text in the goal verbatim in quotes; add 只发这一条，发送后读一遍确认它出现在对话里. Sentinel asks the user before the 发送 tap — expected, and it protects them; do not try to get around it (no typing-and-enter in one step).
5. If the input field already shows text on the screen, tell the operator to clear it first (the `type` action's `clear`), and mention it to the user.

## Do not

- Send anything the user did not confirm word for word; never send "test" text or a second message to check.
- Delete, recall (撤回) or forward messages, change settings, add or remove contacts, transfer money or send red packets. If that is what the user wants, describe the screen and let them do it.
- Guess a contact when two match; ask.

## Finish

- Tell the user what was read and what was sent, with the time you saw on screen. If a reply came in while you were there, say so rather than answering it.
