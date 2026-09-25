# Phone screenshots for the first round

Ten screenshots, Chinese UI, for the 小红书 cards ([cards/](cards/)) and the posts
([posts.md](posts.md)); redaction, resizing and layout happen here
([cards/redact.py](cards/redact.py) → [cards/shots/](cards/shots/)).

Where things stand: the chat shots (`welcome`, `named`, `approval`, `approval-done`, `memory`)
were taken on the project's test phone over `adb` with a made-up persona (老周 / 小知) in a fresh
install; the settings shots (`computers`, `models`, `sysfiles`, `soul`, `hands-settings`, and
the `en-*` set for the English cards) on an Android 13 emulator with the same build, where the
computer's name is pixelated. Still to take, on the phone only — they run through the agent's
sandbox, which the emulator build does not have: `hands-stage`, `hands-yourturn`, `reach`,
`feed`, `goals`; and `avatar-four` once the 百炼 image route works again (see
[film.md](film.md) §3). The card layout drops or swaps a missing shot, so the deck renders
either way.

The rest of this page is the original brief, kept for whoever takes the remaining shots.

## Before shooting

- System language 简体中文, light theme, 24-hour clock. Battery above 50 %; Wi‑Fi on; no
  headphone or vibrate icons if you can help it. Clear the notification shade.
- A fresh chat for anything that is going to be photographed: the history of a real chat has
  real life in it. Delete the demo chats afterwards if you like.
- Full-resolution PNG, the phone's own screenshot (power + volume down). It works while the
  hands are driving the phone too, and the overlay — glow, ring, capsule — is in the picture.
- Drop the files in `~/Downloads/nanomuse-shots/` with the names below, or paste them into the
  chat. Originals only; the redaction happens here, on a copy.

What gets redacted here, always: order numbers, phone numbers, addresses, account names and
avatars in third-party apps, LAN addresses and usernames on the computer, any key. Say if
something else on a shot is private.

## The ten

| # | File | Where | What must be in the frame | How to get there |
|---|---|---|---|---|
| 1 | `chat.png` | Home, the main chat | The dragon (or your face) with its name under it, one finished task with its step card(s) collapsed, the composer at the bottom | New chat → 「看看今天北京的天气，用三句话告诉我」. Wait for the reply; screenshot with the header, the card and the reply in view. |
| 2 | `approval.png` | The main chat, an approval card up | 「允许 <name> 删除 工作区 里的东西？」 with the command preview and the four buttons 允许一次 / 本次对话都允许 / 对「工作区」总是允许 / 拒绝 | Same chat → 「在工作区建一个 build-old 目录，然后把它删掉」. The `mkdir` runs; the `rm` stops for you. Screenshot before answering; then answer 拒绝 or 允许一次, either is fine. |
| 3 | `feed.png` | 动态 (the Feed tab) | Three or more posts of today, the date header, the like / discuss / delete controls visible on one card | If today's feed is thin, open the slider top‑right → 现在写一版. Pick a day whose posts are about interests, not people; the rest we blur. |
| 4 | `goals.png` | 目标 (the Goals tab) | One goal being tracked with its next check-in, and the 例程 section below | If no goal is running: 「帮我定一个目标：这个月每周跑步三次，每周日晚上问我一次进度」, then open 目标. |
| 5 | `hands-stage.png` | A third-party app while the hands work | The blue glow along the edges, the red dashed ring with an action label such as 点击「搜索」, the capsule with 第 N 步 and 停止 | 设置 → 动手操作屏幕 → 允许操作屏幕 (无障碍服务 and 显示在其他应用上层 both 就绪). New chat → 「用高德地图查一下从北京南站到首都机场怎么走，把方案告诉我」 — landmarks, not your own places. Screenshot while it is tapping. Take two or three; we pick one. |
| 6 | `hands-yourturn.png` | Any app that wants a login while the hands work | The 轮到你了 card: 「这一步请你自己完成，然后点「继续」。」 with 继续 | Optional. Log out of an app you do not mind showing (京东 or 携程, say), then ask for something there: 「在京东搜一下罐装咖啡的价格」. It stops at the login. Screenshot; then 停止. |
| 7 | `computers.png` | 设置 → 电脑 | The 已配对的电脑 list with your computer 在线, and the 配对一台电脑 section with its two steps | Pair first if needed: on the computer `python3 host/nanomuse_host.py`, type the 地址 and 配对码 into the app. |
| 8 | `host-terminal.png` | The computer's terminal | The lines `nanomuse_host.py` prints: the address and the six-digit code | A screenshot of the terminal window on the computer, not the phone. Codes expire in ten minutes, so it does not matter that one is visible; the username and LAN address get blurred anyway. |
| 9 | `reach.png` | The main chat, a computer task done | The step card that names the computer and the result | 「在电脑上看看 ~/Downloads 里最近的三个文件叫什么」 (or a folder of yours that is not personal). Screenshot with the card and the reply. |
| 10 | `models.png` | 设置 → 图像与视频模型 | The three sections 对话模型 / 图像模型 / 视频模型 with a model name in each and 就绪 where it is set | Just open the page. Keys are not on this page; if a provider name is personal, say so. |

Two more, if the budget allows one image call:

| # | File | Where | What must be in the frame | How to get there |
|---|---|---|---|---|
| 11 | `avatar-four.png` | The main chat, four portraits to pick from | The four candidates and 点一个你喜欢的，或者直接告诉我"第二个"。 | 「把你的形象换成一只戴围巾的小企鹅」. Screenshot when the four are up; then 先不换了 — adopting one costs five more images. |
| 12 | `sysfiles.png` | ••• → 系统文件 | The list SOUL / USER / MEMORY / 动态偏好 / HEARTBEAT with modification times | Open the page. (For the 公众号 article, not the cards.) |

## Notes for the layout

- Shots 2, 5, 6 and 9 carry the story; if only four shots arrive, make it those.
- Portrait, uncropped: the cards show the phone whole, status bar included. Do not crop the
  status bar — the layout does.
- One app per Hands shot, and never 微信, 支付宝 statements, 医保 or 个税 (the project's own rule
  for public material; see [../launch-checklist.md](../launch-checklist.md)). A 美团 shot, if you
  prefer it to 高德, stops before payment.
