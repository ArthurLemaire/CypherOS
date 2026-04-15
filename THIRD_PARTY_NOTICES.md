# Third-party notices

nanoMuse is licensed under the GNU General Public License, version 3 or later ([LICENSE](LICENSE), [NOTICE](NOTICE)). It stands on other people's work; this file says whose, and on what terms. Three lists: what the Android app is built from, what the frozen Python line includes, and projects we learned from without taking code.

## The Android app (`android/`)

### OpenMinis — GPL-3.0

The app is a modified copy of [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 (tag `1.13`, commit `4ef2900`), Copyright (C) the OpenMinis authors, imported with `git subtree` so that its history is in ours. Modifications since 2026-09-24 are recorded in `git log -- android/`, and every edit inside an upstream file carries a `// nanoMuse:` comment. The OpenMinis name and logo are theirs and are not used for this application. What follows is OpenMinis's own third-party list, kept to the parts that remain in this tree (the iOS half was removed).

### Native code (`android/deps/`)

| Component | Source | License | Notes |
|---|---|---|---|
| [proot](https://github.com/nano-muse/proot) | git submodule `android/deps/proot` — our fork of [OpenMinis/proot](https://github.com/OpenMinis/proot), itself a fork of [termux/proot](https://github.com/termux/proot) | **GPL-2.0** | The Linux sandbox. Runs as a separate program (`assets/proot-aarch64`; also shipped as `lib/arm64-v8a/libproot.so` and the two loaders so the installer places them where Android lets them execute). Built by `android/deps/build_proot.sh`. |
| [talloc](https://talloc.samba.org) (Samba) | vendored at `android/deps/talloc` | **LGPL-3.0-or-later** | Memory allocator proot is statically linked against |
| [cppjieba](https://github.com/yanyiwu/cppjieba) | vendored in `jieba_jni` | **MIT** | Chinese word segmentation (header-only + dictionaries) |
| [rclone](https://github.com/rclone/rclone) | `android/deps/rclone-mobile`, built into `rclone.aar` by `android/deps/build_rclone_android.sh` with [gomobile](https://pkg.go.dev/golang.org/x/mobile) (BSD-3-Clause) | **MIT** | Remote destinations for backup (SMB / WebDAV / SFTP / S3 / FTP) |
| Alpine Linux minirootfs | downloaded at build time by `android/scripts/prepare_android_sandbox.sh` | Aggregate of package licenses (musl **MIT**, BusyBox **GPL-2.0**, …) | Not stored in this repository; bundled into the APK as the default root file system |

### Gradle dependencies

| Library | Version | License |
|---|---|---|
| AndroidX / Jetpack (Compose BOM 2025.09.00, core-ktx, lifecycle, activity, navigation, Room, DataStore, security-crypto, browser, webkit, exifinterface, material3-adaptive) | see `android/src/android/app/build.gradle.kts` | **Apache-2.0** (Google / AOSP) |
| OkHttp + okhttp-sse | 4.12.0 | **Apache-2.0** |
| kotlinx-serialization-json | 1.7.3 | **Apache-2.0** |
| kotlinx-coroutines-android | 1.9.0 | **Apache-2.0** |
| Coil (coil-compose) | 2.7.0 | **Apache-2.0** |
| multiplatform-markdown-renderer (+ m3) — mikepenz | 0.33.0 | **Apache-2.0** |
| Reorderable (sh.calvin.reorderable) | 2.4.0 | **Apache-2.0** |
| ACRA (acra-core) | 5.12.0 | **Apache-2.0** |
| Shizuku API + provider (dev.rikka.shizuku) | 13.1.5 | **MIT** |
| RealTimeCutVADLibraryForAndroid (JitPack) | see build file | **MIT** (Silero VAD **MIT**, ONNX Runtime **MIT**, WebRTC APM **BSD-3-Clause**) |

Test-only: JUnit 4.13.2 (**EPL-1.0**), MockWebServer 4.12.0 (**Apache-2.0**), kotlinx-coroutines-test 1.9.0 (**Apache-2.0**), org.json 20231013 (**Public Domain / JSON License**).

### Bundled assets

| Asset | Location | License |
|---|---|---|
| KaTeX | `app/src/main/assets/katex/` | **MIT** |
| jieba dictionaries | `app/src/main/assets/jieba/` | **MIT** (cppjieba distribution) |
| models.dev registry snapshot | `app/src/main/assets/models-dev-api.json` | **MIT** ([models.dev](https://models.dev)) |

### The nanoMuse mark

The name nanoMuse and the mark in `assets/brand/` are the project's own. Use them to refer to this project; do not use them to suggest that something else is nanoMuse or endorsed by it.

## The Python line (`nanomuse/`, `web/`, `demo/`, `site/`)

Frozen since the OpenMinis import (tag `pre-openminis`), kept as the base of the later web and desktop phases. Third-party code inside it keeps its own licence and notice.

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

[MobileGym](https://github.com/Purewhiter/mobilegym) is the simulated Android phone the showcase runs on. `demo/mobilegym/apps/nanoMuse/` is an app module written for it; `demo/mobilegym/install.sh` copies the module into a MobileGym checkout and the showcase image (`demo/showcase/caddy/Dockerfile`) builds MobileGym with it. MobileGym's code is Apache-2.0; its default app data (`mobilegym-data`: synthetic and sanitised content, icons) is [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), **non-commercial use only** — the hosted showcase serves it as a free demonstration and nothing else. The finger overlay in `gui.ts` follows MobileGym's own touch-feedback timing.

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

- **Meta Muse** — the product shape: one agent with a name and a face, a feed, goals, "asks before anything you could not undo". nanoMuse is an independent project, not affiliated with or endorsed by Meta Platforms, Inc.; nothing of the Muse app was decompiled or copied.
- **[PhoneHarness](https://github.com/lsdefine/PhoneHarness)** — deterministic-first routing (a tool that does the thing exactly beats the GUI) and a JSONL trace per run rendered to HTML. Ideas only: the repository carries no license.
- **[CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse)** (MIT) — product designs we follow rather than code: durable tasks with a take-control hand-off, watches, ideas with evidence, a follow-up queue, "content is evidence, not permission", background-update preferences.
- **[Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM)** (Apache-2.0) and **[ClawGUI](https://github.com/ClawGUI/ClawGUI-APP)** (Apache-2.0) — reference points for operating a phone through its screen (package tables, Shizuku, a built-in IME, a floating bar). When code from either lands, it will be listed above.
- **[browser-use](https://github.com/browser-use/browser-use)** (MIT) — the element-annotation idea behind the browser tool.
