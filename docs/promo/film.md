# The launch film

One 16:9 film of about ninety seconds, silent, with the copy on screen — Chinese and English
cuts of the same footage — plus a vertical clip per scene and a six-second GIF for the README.
Everything in it is the app doing the thing on a phone; nothing is mocked up, sped up or
re-enacted. The footage, the cut and the copy all live in [film/](film/).

The film says the same thing as the README's first sentence and the four rows under "Why
nanoMuse", in this order: it is a Muse-style agent (a name, a first conversation, a memory,
a question before anything irreversible); it is fully open (the memory is a file you can open);
it can use apps that have no API (the hands); it reaches your other devices (the computer).

## 1. Scenes

| # | Scene | From | On screen | Copy (zh) | Status |
|---|---|---|---|---|---|
| 0 | Title | rendered | The dragon; the positioning sentence | 完全开源的 Muse 式个人智能体，装在你自己的手机上。 | done |
| 1 | `name` | `02-name.mp4` | The three proposed names; 小知 is chosen; the header renames itself; 「好嘞老周，我就是小知了」 | 它问你怎么称呼，再给自己起名字。 | shot (phone) |
| 2 | `approval` | `03-approval.mp4` | 「好，现在把 build-old 整个删掉」; the shell card; the sheet 允许 小知 删除 工作区 里的东西？ with `rm -rf …` and the four buttons; 允许一次; 「搞定，build-old 目录已删除」 | 删之前，先停下来问你。 | shot (phone) |
| 3 | `memory` | `04-memory.mp4` | 「记一下：我在北京做 Android 开发…」; the card 记录老周的个人背景信息; 「记下了，老周」 | 随口一句，它记进 USER.md。 | shot (phone) |
| 4 | `pair` | `06-pair.mp4` | 设置 → 电脑: address and six-digit code typed, 配对, the computer appears under 已配对的电脑 | 电脑上跑一个 Python 文件，手机上填六位码。 | shot (emulator; the computer's name is pixelated) |
| 5 | `hands` | `07-hands.mp4` | 「打开时钟 App 帮我设一个明早 7:30 的闹钟，周一到周五」; the glow along the edges, the ring where it taps, the capsule with 停止; the alarm exists | 没有 API 的 App，它自己看屏幕点。 | to shoot (phone only — see §3) |
| 6 | `reach` | `08-reach.mp4` | 「在电脑上看看 ~/Downloads 里最近的三个文件叫什么」; the step card naming the computer; the answer | 手机上说一句，电脑上干完。 | to shoot (phone only) |
| 7 | `feed` | `09-feed.mp4` | The 动态 tab, 「现在就写一版」, three posts appear | 每天早上几条短帖，来自它对你的了解。 | to shoot (phone) |
| 8 | End | rendered | nanomuse.cn (zh) / the GitHub URL (en); the Meta and GPL lines | 下载、源码和每一版的说明都在这里。 | done |

The cut keeps the model's real pauses. A scene is fourteen to twenty-two seconds; the four
shot so far make an 83-second film with the title and end cards. Scenes 5–7 will take it to
about two and a half minutes, which is long for X and fine for B站 and YouTube; for X and the
public accounts, post the vertical clips one at a time instead.

The people in the footage are made up: the user is 老周, an Android developer in Beijing who
likes Rust, cycling to 妙峰山, and a cat called 年糕; the agent named itself 小知. Nothing on
screen belongs to a real person. Whatever the host prints about the computer (its hostname,
LAN address) is pixelated in the cut (`PAIR_BLUR` in build.py); if a new take moves those
lines, move the rectangles.

## 2. Recording

`film/record.py` records the phone with the real frame times: the scrcpy server on the phone
sends a frame only when the screen changes, stamped with its presentation time; the script
keeps those times, so a two-second wait for the model is two seconds in the film and typing
looks like typing. ColorOS's own `screenrecord` crashes on start, which is how this came about.

```bash
pip install --user av                                   # once; PyAV keeps the timestamps
curl -LO https://github.com/Genymobile/scrcpy/releases/download/v4.1/scrcpy-server-v4.1
adb push scrcpy-server-v4.1 /data/local/tmp/scrcpy-server.jar

python3 docs/promo/film/record.py --statusbar on        # 09:41, full battery, Wi‑Fi, no notifications
python3 docs/promo/film/record.py 03-approval           # Ctrl-C when the scene is over → ~/nm-rec/03-approval.mp4
python3 docs/promo/film/record.py --statusbar off
```

Before a take: system language 简体中文, light theme; a fresh chat with the made-up persona
(the first message of `02-name` is 「我叫老周」 and the agent's proposals follow); the model
the film uses is whatever is configured — the footage shows `qwen3.7-plus` on 阿里云百炼 and
the cards say so. Type with the phone's keyboard or an ADB keyboard; the film does not show the
keyboard, only the composer filling. Do not touch the notification shade. Never type a key on
camera; the provider is configured before recording starts.

Scenes are recorded long and cut short: leave the recorder running through the whole exchange
and pick the seconds afterwards. To find them, a contact sheet is quicker than scrubbing:

```bash
ffmpeg -i ~/nm-rec/03-approval.mp4 -vf "fps=1/4,scale=135:-1,drawtext=text='%{pts\:hms}':x=4:y=4:fontsize=14:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=12x6" -frames:v 1 sheet.png
```

## 3. What still has to be shot, and how

The three remaining scenes run through the agent's sandbox (`nanomuse-hands`, `nanomuse-pc`,
the feed writer), which the x86_64 emulator build does not have — they need the phone with USB
debugging allowed.

- **`07-hands`.** 设置 → 动手操作屏幕: 无障碍服务 and 显示在其他应用上层 both 就绪, 允许操作屏幕 on.
  The phone used for the footage has no third-party apps, so the scene uses the system clock:
  「打开时钟 App 帮我设一个明早 7:30 的闹钟，周一到周五」. Name the app in the sentence — a
  bare alarm request goes to the scheduler tool instead of the screen. Let it run to the end;
  the cut is the first twenty seconds of the stage (glow, ring, capsule), then the result. If a
  third-party app is used instead, one app per take, landmarks not home addresses, stop before
  any payment, and never 微信.
- **`08-reach`.** On the computer `python3 host/nanomuse_host.py`; pair (the emulator take of
  the pairing already exists, so this scene is only the task): 「在电脑上看看 ~/Downloads 里最近的
  三个文件叫什么」 against a folder with nothing personal in it. The step card names the
  computer — the cut pixelates it.
- **`09-feed`.** 动态 tab → the slider → 现在就写一版. Pick a day whose posts are about
  interests, not people.
- Optional **`10-avatar`**: 设置 → 形象, a one-line description, 画四张, pick one. This needs
  the image model to answer; at the time of writing the 百炼 image route in the app returns
  HTTP 404 (`/compatible-mode/v1/images/generations` does not exist on DashScope; the native
  `multimodal-generation` endpoint does), so the scene waits for that fix.

Add each new file to `SCENES` in build.py (the entries are already there with placeholder
ranges), run the contact sheet, set the ranges, rebuild.

## 4. Cutting

```bash
python3 docs/promo/film/build.py --raw ~/nm-rec --list      # which scenes have footage
python3 docs/promo/film/build.py --raw ~/nm-rec             # everything into docs/promo/film/out/
```

Outputs: `nanomuse-launch-zh.mp4` and `nanomuse-launch-en.mp4` (1920 × 1080, 30 fps, H.264,
silent), `vertical/<scene>.mp4` (1080 × 1920, Chinese copy), `nanomuse-approval.gif` (400 px,
12 fps, six seconds of the approval sheet — copied to [film/approval.gif](film/approval.gif) for
the README), and `stills/` with the first frame of every kept range for thumbnails. `out/` is
git-ignored; the film is published as a release asset and on the platforms, not in the repo.

Layout: the phone in a dark rounded bezel on the right, the copy on the left — kicker in the
site's blue, a two-line title, one or two lines of caption, the brand at the bottom. Type is
Noto Sans CJK; colours are nanomuse.cn's (`#f5f5f7`, `#1d1d1f`, `#6e6e73`, `#0a66e4`). Fades
of 0.4 s between scenes; no other transitions. The English cut is the same footage with the
English copy — the UI in the footage is Chinese, and the English film says so on the approval
scene rather than pretending otherwise.

## 5. Sound

Delivered silent. No narration, no TTS — the copy is on screen. Music, if any, goes on at
upload time from the platform's licensed library (B站, 视频号 and YouTube all have one), which
is simpler than clearing a track for four platforms. If a track is mixed into the file instead,
use CC0 only (FreePD.com is CC0) and add the title and source to `NOTICES`.

## 6. Where each output goes

| Output | Where | Notes |
|---|---|---|
| `nanomuse-launch-zh.mp4` | B站 (with the 5–8 minute explainer later), 知乎, 公众号 (as the video in the article) | Title and description in [posts.md](posts.md) § B站 |
| `nanomuse-launch-en.mp4` | YouTube, the X thread, Product Hunt | [international.md](international.md) |
| `vertical/*.mp4` | 视频号, 抖音, 小红书 video posts, X | One scene per post; the vertical cut carries its own title |
| `approval.gif` | README (both languages), GitHub social preview, Show HN comment | 721 KB |
| `stills/*.png` | Thumbnails, the 公众号 header, the B站 cover | Pixelate anything that names a person or a machine |

## 7. Before publishing

- Watch it once at full size. Anything that names a real person, machine, network or account
  is pixelated; there is no key, no order number, no phone number anywhere in the frame.
- The footage is the shipped 0.1.15 build; the copy says 0.1.15 and never says "demo".
- The end card carries the Meta trademark line and the OpenMinis / GPL line in both cuts.
- Third-party apps, if any appear, are functional demonstration only.
