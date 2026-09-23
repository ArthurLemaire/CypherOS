# The promo video

`storyboard.html` is the film as a web page: eight scenes, the app's own phone header and
approval card, the red panda from `web/src/components/RedPanda.tsx`, the screenshots from
`docs/screenshots/`. `render.py` screenshots it frame by frame at fixed times and hands the
frames to ffmpeg, so a render is identical every time and a re-cut is an HTML edit.

```bash
cd web && npm run site:mascot                 # site/assets: mascot, icons, screenshots
cd .. && python site/promo/render.py          # site/media/nanomuse-promo.mp4 + poster (~4 min)
```

Open `storyboard.html` through any static server (`python3 -m http.server` in `site/`) to
watch it play in real time in a browser; under Playwright the page does not tick on its own.

## Shape

| Time | Scene | What is on screen |
|---|---|---|
| 0:00 | Title | The panda, the wordmark, "An open-source personal AI agent", 中文 line, "Inspired by Meta Muse". |
| 0:05 | Ask → works → asks → done | The phone: the Hangzhou task is typed and sent; 高德 and 12306 chips; the 飞书 approval card, Allow, the message goes out; the result. Captions beside it. |
| 0:24 | One agent, many hands | Eight tiles: web & files, sandboxed shell, MCP · 高德, CLIs · 飞书, skills, browser, the phone screen, all in one task. |
| 0:32 | The screen | A 12306-style train list, a tap on the fastest train, a tap on pay — and the payment approval card that stops it. |
| 0:40 | The screens | Feed, Goals, Library and Chat screenshots slide in. |
| 0:47 | Your machine, any model | A terminal types `uv tool install nanomuse` and `nanomuse serve`; model chips. |
| 0:54 | Where it runs | Phone now, web next, desktop later. |
| 1:00 | End card | The happy panda, the repository, the site. |

There is no soundtrack; the file plays muted in feeds and the README, and a track can be
muxed in later with `ffmpeg -i nanomuse-promo.mp4 -i track.m4a -c copy -shortest out.mp4`.

The 12306 screen and the group name are mock-ups drawn for the film; the app's own showcase
runs the real apps on the simulated phone (`demo/mobilegym/`).
