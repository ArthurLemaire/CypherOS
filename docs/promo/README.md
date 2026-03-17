# Launch material

Everything the project says about itself in public, in one place, so every post on every
platform tells the same story: **a fully open-source, Muse-style personal agent for every device
you own — Android today**, defined by four things that are all in the app — Muse-style · fully
open · any app, API or not · every device. The wording of record is the README (both languages)
and [nanomuse.cn](https://nanomuse.cn/); the copy here paraphrases it and never goes past it.

## What is here

| File | What | For |
|---|---|---|
| [xiaohongshu.md](xiaohongshu.md) | Titles, the post, tags, pinned comment, profile, timing | 小红书 first post |
| [posts.md](posts.md) | The same story for 即刻, V2EX 分享创造, 酷安, 知乎, B站, 少数派; reply lines for comments | Second-wave Chinese posts |
| [wechat.md](wechat.md) | The long article in eight sections, with every picture named; layout and publishing notes | 微信公众号, re-cut for 知乎 and 少数派 |
| [international.md](international.md) | Long post, Show HN, X thread, three Reddit versions, Product Hunt | English-language launch |
| [film.md](film.md) | The launch film: scenes, recording, cutting, sound, what still has to be shot | B站, YouTube, 视频号, the README GIF |
| [shots.md](shots.md) | The screenshot brief and which shots exist | Whoever takes the remaining shots |
| [cards/](cards/) | `cards.html` (nine 3:4 cards, Chinese), `cards-en.html` (seven 16:10 cards, English), `render.py`, `redact.py`, `shots/` | Pictures for every post |
| [film/](film/) | `record.py` (phone recording with real timing), `build.py` (the cut), `approval.gif` | The film and the GIF |

Rendered pictures and video are not committed (`cards/out/`, `cards/out-en/`, `film/out/` are
ignored); regenerate them:

```bash
pip install --user playwright pillow av && playwright install chromium
python3 docs/promo/cards/render.py                                                   # cards/out/01..09-*.png
python3 docs/promo/cards/render.py --html docs/promo/cards/cards-en.html --out docs/promo/cards/out-en
python3 docs/promo/film/build.py --raw ~/nm-rec                                      # film/out/…
```

The raw recordings (`~/nm-rec/*.mp4`, from `film/record.py`) are kept off the repository: a
few hundred MB, and they contain the whole take, not just the seconds the cut uses.

## Order and cadence

1. **First round, pictures only.** 小红书 on a weekday noon (Tue–Thu); 即刻 the same evening;
   V2EX and 酷安 the next morning; 知乎 answers over the following week. GitHub topics and the
   social preview go up first, since every post lands there.
2. **Second round, with the film.** Once `07-hands` and `08-reach` are shot ([film.md](film.md)
   §3): the 公众号 article, B站, 少数派; a second 小红书 post about the hands (title 3 in
   xiaohongshu.md); the vertical clips on 视频号 and 抖音, one scene per post.
3. **English.** The long post, then Show HN (Tue–Thu, 8–10 a.m. Eastern), the X thread the same
   day, Reddit across the following days, Product Hunt last.

Answer comments for the first two hours of every post, in the project's voice
([posts.md](posts.md) § 评论回复的口径). Whatever gets asked twice goes into a `faq.md` here and
from there back into the README and the site.

Measure with what exists: GitHub stars, release downloads
(`gh api repos/nano-muse/nanoMuse/releases --jq '.[].assets[].download_count'`), issues opened.
The site has no analytics.

## Before anything goes out

- Positioning first: the sentence and the four things, in that order; features after.
- Hands (0.1.12) and Reach (0.1.13) are shipped and were tried on a phone. Never "demo",
  "preview", "coming soon". The version is 0.1.15; fifteen releases since 2026-09-24; "continue?"
  at 200 steps.
- Every piece carries: independent community project, not affiliated with Meta; Muse is a
  trademark of Meta Platforms, Inc.; based on OpenMinis 1.13 (GPL-3.0); the whole repository
  GPL-3.0-or-later; the dragon is the project's own.
- Screenshots and footage: no key, no real name, no hostname, no LAN address, no order or phone
  number; third-party apps only as functional demonstration, one app per shot, never 微信,
  支付宝 statements, 医保 or 税务; anything with a payment stops before it. The people in the
  footage (老周, 小知) are invented.
- Permissions are explained where they are mentioned: the accessibility service takes
  screenshots and injects gestures, does not read the screen; the overlay shows the capsule with
  Stop; both are needed only with Hands on. The account-risk line for automating third-party
  apps stays in.
- Cost is stated honestly: the app is free; the user's own key pays for the model; screen
  driving is the expensive part.
- Chinese copy reads like Chinese: no 「颠覆」「王炸」「保姆级」「一键」「赋能」, no
  three-part parallel slogans, no literal translations. English copy: plain, specific, no
  superlatives.
- 小红书 only: no QR code, no "GitHub" or "download" in the picture or the text — write
  「搜 nanomuse.cn」.

## Facts the copy relies on

| Fact | Source |
|---|---|
| Positioning sentence and the four things | `README.md` / `README_zh.md` "Why nanoMuse"; nanomuse.cn |
| Muse: cloud VM per user, thin clients, Sentinel, September 2026 | README comparison table; `docs/roadmap.md` |
| OpenMinis 1.13 subtree since 2026-09-24; GPL-3.0-or-later | `docs/roadmap.md`, `NOTICE`, release notes |
| Approval scopes; passwords never typed | `docs/releases/v0.1.4.md`; `ShellGuard.kt` |
| Hands: screenshots not the tree; the ladder; off by default; Android 11+ | `docs/releases/v0.1.12.md` |
| Stage: glow, ring, ripple, capsule | `docs/releases/v0.1.15.md` |
| Reach: one stdlib file, six-digit code for ten minutes and one phone, hash-only on the host, no TLS, one way | `host/nanomuse_host.py`, `docs/releases/v0.1.13.md` |
| Three models; one Model Studio key | `docs/releases/v0.1.10.md`, `v0.1.11.md`; Settings → 图像与视频模型 |
| Feed 3–6 posts; goals checked in their own conversation; 200 steps | README "能做什么" |
| Versions and codenames | `docs/roadmap.md` Phase 1 table |
