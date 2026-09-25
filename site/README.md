# The landing page (legacy)

The nanoMuse homepage now lives in [nano-muse/nano-muse.github.io](https://github.com/nano-muse/nano-muse.github.io)
and is served at <https://nanomuse.cn/>, with a GitHub Pages copy at <https://nano-muse.github.io/>.
`site/index.html` here is a redirect to it;
the page below — the Python line's site with the promo film — is kept as `legacy.html` and
still published by `.github/workflows/pages.yml` under `https://nano-muse.github.io/nanoMuse/legacy.html`.

`legacy.html` is one static page, no framework, English and 中文 in the same file (the toggle
in the top right, `?lang=zh` or `?lang=en` in the URL).

## Preview

The page uses the same red panda as the app, rendered once per mood to plain SVG, plus the
app's screenshots. Those files are generated, not committed:

```bash
cd web && npm ci && npm run site:mascot     # writes site/assets/
cd ../site && python3 -m http.server 8000   # http://localhost:8000
```

## What is where

| File | Purpose |
|---|---|
| `legacy.html` | The earlier page. Every string appears twice, in `<span class="en">` and `<span class="zh">`. |
| `style.css` | Colours, type and radii copied from `web/src/index.css`; light and dark. |
| `site.js` | The language toggle and the phone in the hero, which plays one task end to end. |
| `assets/` (generated) | `mascot.js` + `mascot.css` from `web/src/components/RedPanda.tsx`, icons, fonts, `screens/` from `docs/screenshots/`, `cover.png`. |
| `media/` | The promo video and its poster, rendered from `promo/storyboard.html` by `promo/render.py` (see `promo/README.md`). Committed: 1.7 MB. |

The phone mock in the hero is not a video: it is the app's own markup and the mascot's own
stylesheet, so when the panda or the approval card changes in the app, `npm run site:mascot`
brings the page along.

## Domain

`nanomuse.cn` is served by the showcase server, which pulls the homepage repository every minute
(`demo/showcase/README.md`, "Other sites on the same Caddy"); GitHub Pages publishes the same
repository at `nano-muse.github.io`. One push to that repository's `main` updates both.
