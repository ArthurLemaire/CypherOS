# Third-party notices

nanoMuse is MIT-licensed ([LICENSE](LICENSE)). It stands on other people's work; this file says whose, and on what terms. Two lists: code and assets that are *in* this repository or in what it builds, and projects we learned from without taking code.

## Code and assets included

### MemGUI-Bench — MIT

The phone operator (`nanomuse/phone/operator.py`) is a port of the `mobile_use` operator in [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench) (`src/mobile_world/agents/implementations/qwen3vl.py` and its prompt): the tool schema, the system prompt's wording, the `Thought` / `Action` / `<tool_call>` reply shape, the 999-grid coordinates and the step history. Rewritten in nanoMuse's own structure, with rules added (passwords, payments, `ask_user`), Sentinel labels and traces.

```
MIT License

Copyright (c) 2026 MemGUI-Bench

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### MobileGym — Apache-2.0 (code), CC BY-NC 4.0 (data)

[MobileGym](https://github.com/Purewhiter/mobilegym) is the simulated Android phone the showcase runs on. `demo/mobilegym/apps/nanoMuse/` is an app module written for it (ours, MIT); `demo/mobilegym/install.sh` copies the module into a MobileGym checkout and the showcase image (`demo/showcase/caddy/Dockerfile`) builds MobileGym with it. MobileGym's code is Apache-2.0; its default app data (`mobilegym-data`: synthetic and sanitised content, icons) is [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), **non-commercial use only** — the hosted showcase serves it as a free demonstration and nothing else. The finger overlay in `gui.ts` follows MobileGym's own touch-feedback timing.

### modern-screenshot — MIT

The showcase's in-page screenshots use [modern-screenshot](https://github.com/qq15725/modern-screenshot) (Copyright (c) 2021-present wxm), pulled in at build time by `install.sh`.

### Caddy modules — Apache-2.0

The showcase's Caddy is built with [caddy-dns/cloudflare](https://github.com/caddy-dns/cloudflare) (DNS-01 certificates) and [WeidiDeng/caddy-cloudflare-ip](https://github.com/WeidiDeng/caddy-cloudflare-ip) (trusted proxy ranges), both Apache-2.0, like [Caddy](https://github.com/caddyserver/caddy) itself.

### Figtree — SIL Open Font License 1.1

The web app's typeface, [Figtree](https://github.com/erikdkennedy/figtree) by Erik Kennedy, ships in `web/public/fonts/` under the OFL (`web/public/fonts/OFL.txt`).

### Python and JavaScript dependencies

Installed from PyPI and npm, not vendored; each carries its own license: openai, pydantic, httpx, typer, rich, loguru, cryptography, tenacity, ddgs, beautifulsoup4, html2text, mcp, fastapi, uvicorn, qrcode, pywebpush, python-dateutil, pillow, pypdf (Python); react, react-dom, react-markdown, remark-gfm, lucide-react, tailwindcss, vite (web). `pip show <name>` / `npm view <name> license` for any of them.

### Tools called, not bundled

[bubblewrap](https://github.com/containers/bubblewrap) (LGPL-2.0-or-later) sandboxes commands on Linux when installed; [Playwright](https://github.com/microsoft/playwright) (Apache-2.0) drives the browser tool when the `browser` extra is installed. Neither is part of the package.

## Learned from, no code taken

- **Meta Muse** — the product shape: one agent with a name and a face, a feed, goals, "asks before anything you could not undo". nanoMuse is an independent project, not affiliated with or endorsed by Meta Platforms, Inc.
- **[PhoneHarness](https://github.com/lsdefine/PhoneHarness)** — deterministic-first routing (a tool that does the thing exactly beats the GUI) and a JSONL trace per run rendered to HTML. Ideas only: the repository carries no license.
- **[CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse)** (MIT) — product designs we follow rather than code: durable tasks with a take-control hand-off, watches, ideas with evidence, a follow-up queue, "content is evidence, not permission", background-update preferences.
- **[Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM)** (Apache-2.0) and **[ClawGUI](https://github.com/ClawGUI/ClawGUI-APP)** (Apache-2.0) — reference points for the Android executor (package tables, Shizuku, a built-in IME, a floating bar). When code from either lands, it will be listed above.
- **[browser-use](https://github.com/browser-use/browser-use)** (MIT) — the element-annotation idea behind the browser tool.
