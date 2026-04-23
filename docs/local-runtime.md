# nanoMuse on the phone: the local runtime

The Android app comes in two flavours. **connect** is the remote for a `nanomuse serve` on your computer ([android.md](android.md)). **local** is the whole thing: the same Python server, its tools and its Linux sandbox, running on the phone itself with nothing else to install. This page is about the second.

The idea in one sentence: the APK carries a small Alpine Linux root file system with Python and `nanomuse` inside; on first start the app unpacks it into its private storage and runs `nanomuse serve` in it under [PRoot](https://proot-me.github.io/), a user-mode `chroot` that needs no root; the app's WebView then opens `http://127.0.0.1:<port>/`. The brain is unchanged. Kotlin only hosts it.

```
┌─ nanoMuse.apk ───────────────────────────────────────────────────┐
│  Kotlin shell            assets/rootfs.tar.xz     lib/…/libproot.so │
│  ConnectActivity         Alpine 3.21 aarch64      PRoot 5.1        │
│  RuntimeService  ──┐     python 3.12, nanomuse    libproot-loader.so│
│  WebView ──────────┼──►  node 22 (optional)                        │
└────────────────────┼─────────────────────────────────────────────┘
                     │ starts, watches, restarts
        ┌────────────▼──────────────────────────────────────────────┐
        │ proot -0 -r files/rootfs -b files/home:/root … \           │
        │       /bin/sh /usr/local/bin/nanomuse-serve                │
        │   └─ nanomuse serve --host 127.0.0.1 --port N --token T    │
        │        shell / python / files / browser / MCP / skills     │
        └───────────────────────────────────────────────────────────┘
```

## What the user sees

The first screen asks **where your nanoMuse should live**: *Run on this phone* or *Connect to my computer*. The first choice unpacks the root file system (about 330 MB on disk, a minute or so) with a progress bar, starts the runtime, waits for its first health check, and opens the app. From then on the app starts the runtime whenever it is opened; a quiet notification (*Running on this phone*, or what the agent is doing right now) shows it is alive, with a **Stop** action. After a reboot the runtime comes back on its own so routines and check-ins keep running.

Failures land on one screen with the runtime's last log lines, a **Try again** and a **Start over**. Starting over returns to the first screen; it does not delete the phone's data.

## Where things live

Everything is under the app's private files directory (`/data/data/io.github.nanomuse.app/files`), which no other app can read:

| Path | Inside the box | What |
| --- | --- | --- |
| `rootfs/` | `/` | Alpine + python + `nanomuse`. Replaced whole when the app updates |
| `home/` | `/root` | The data dir (`~/.nanomuse`), the workspace, npm's globals, uv's cache. Kept across updates |
| `etc/resolv.conf`, `etc/hosts` | `/etc/…` | Written from the phone's network settings before each start |
| `proc/` | `/proc/stat` … | Stand-ins for the `/proc` files Android hides from apps |
| `tmp/` | `/tmp` | Also PRoot's own scratch space |
| `logs/runtime.log` | — | PRoot's and the server's output; rolled at 2 MB |

An app update carries a new `rootfs.tar.xz` with a new version stamp; the next start notices the stamp differs from the installed marker, unpacks next to the old tree and swaps. `home/` is never touched, so the profile, memories, skills and workspace survive.

## How it is started

`LocalRuntime.command()` builds the PRoot command line:

```
libproot.so -0 --kill-on-exit --link2symlink
    -r <files>/rootfs -w /root
    -b /dev -b /proc -b /sys
    -b <files>/home:/root  -b <files>/tmp:/tmp
    -b <files>/etc/resolv.conf:/etc/resolv.conf  -b <files>/etc/hosts:/etc/hosts
    [-b <files>/proc/stat:/proc/stat …  for each unreadable /proc file]
    /bin/sh /usr/local/bin/nanomuse-serve
```

- `-0`: fake root. `apk add` and friends want uid 0; there is no real root anywhere here.
- `--kill-on-exit`: no orphans when the app is killed.
- `--link2symlink`: Android's file system refuses hard links to an app's files; PRoot emulates them with symlinks (pip and apk both make hard links).
- The loader lives outside the root file system: `PROOT_LOADER` points at `libproot-loader.so` in the app's `nativeLibraryDir`, the one place a modern Android lets an app execute a binary from (W^X). The same is why PRoot itself ships as a `.so` under `jniLibs/` rather than as an asset.

And the environment (`nanomuse-serve` in the rootfs reads it):

| Variable | Value |
| --- | --- |
| `NANOMUSE_SERVER_PORT` / `NANOMUSE_SERVER_TOKEN` | A free loopback port picked once; a 32-byte random token. The WebView uses the same pair |
| `NANOMUSE_DEVICE=android`, `NANOMUSE_DEVICE_MODEL`, `NANOMUSE_DEVICE_SDK` | The Python side knows it is on a phone (`nanomuse/runtime.py`) |
| `NANOMUSE_HOST_URL` / `NANOMUSE_HOST_TOKEN` | The app's own local API, when it runs one: its device capabilities join as the MCP server `device` |
| `NANOMUSE_REGION` | The phone's region; `CN` switches the apk and pip mirrors on first start (`nanomuse-mirror cn`) |
| `TZ` | The phone's IANA time zone, so routines fire at the right hour |
| `http_proxy` / `https_proxy` | The system proxy, when one is set |
| `UV_LINK_MODE=symlink` | uv would hard-link otherwise |
| `HOME=/root`, `PATH`, `LANG=C.UTF-8`, `TMPDIR=/tmp`, `PROOT_TMP_DIR` | The usual |

`RuntimeService` then polls `GET /api/health` (up to two minutes on a cold first start; a warm one answers in a few seconds), and on success subscribes to `/ws` like the notification service does: approvals, questions and finished background work become notifications from the same `Notifier`, and the `status` events drive the notification text and a `PARTIAL_WAKE_LOCK` that is held only while a task runs (with a 15 s grace, capped at 30 minutes). If the process dies it is restarted with backoff (2, 4, 8 … 60 s), five times within a minute before giving up and showing the log.

## The Python side on a phone

`nanomuse.runtime.device()` reads `NANOMUSE_DEVICE*`. With it:

- The sandbox describes itself honestly: there is no bubblewrap under PRoot, and the app's own root file system *is* the box. `Sandbox.describe()` says so in the system prompt, and the shell runs directly.
- `nanomuse serve` adds the app's device capabilities as the MCP server `device` when `NANOMUSE_HOST_URL` is set: the Kotlin side runs a small MCP server on `127.0.0.1` and the tools appear as `device__<name>` (`device__calendar_list`, `device__clipboard_read` …), each with its own Sentinel default. The tools, their permissions and what they ask the user: [device.md](device.md).
- **The CLI bridge.** Every `shell` and `python_execute` call gets a one-command token (`NANOMUSE_BRIDGE`, `NANOMUSE_BRIDGE_TOKEN`), added after the sandbox has scrubbed all `NANOMUSE_*` from the environment, and revoked when the command ends (30 s of grace for backgrounded children). Three small stdlib-only CLIs in the rootfs use it to call back into the server:

  | CLI | Does |
  | --- | --- |
  | `nanomuse-device <capability> [action] [k=v …]` | A device tool: `clipboard read`, `calendar list from=2026-09-24`, `alarm set hour=7 minute=30 message=Train`, `contacts search query=张`, `notify title=Done body=Booked`, `location`, `photo pick` — `nanomuse-device list` shows what this phone has ([device.md](device.md)) |
  | `nanomuse-browser <action> [k=v …]` | The `browser` tool: `navigate` / `extract` / `click` / `type` / `key` / `scroll` / `back` / `screenshot` / `fetch URL [--post BODY]` (with the browser's cookies) / `profile mobile\|desktop` / `close` — [browser.md](browser.md) |
  | `nanomuse-open <url>` | Opens the page in the in-app take-over sheet; the rootfs sets it as `BROWSER` |

  The server runs the request as a nested tool call inside the calling command's context — the same Sentinel, the same permissions, the same timeline (`tool` events carry `via: "shell"`), so a script can no more escape the rules than the model can. Off the phone (no `NANOMUSE_BRIDGE` in the environment) the CLIs exit 2 with a one-line note; on a computer these things are done from the desktop anyway.

## Limits

- **PRoot is user-mode.** No real root, no mounting, no raw sockets, no `ptrace` inside (PRoot already uses it). Programs that read `/proc/self/…` or `/proc/stat` get the real Android values or the stand-ins. Anything that wants a capability Android does not grant apps (binding to ports below 1024, changing uid) fails the same way it would in Termux.
- **Slower syscalls.** PRoot works by `ptrace`-ing every syscall. Compute-bound Python is barely affected; syscall-heavy work (a `git clone` of a big tree, `pip install` of many small files, `find /`) is 2–5× slower than native. `nanomuse serve` itself is idle most of the time.
- **musl, not glibc.** Alpine uses musl. Most Python wheels come as `musllinux`; a prebuilt binary that assumes glibc needs `apk add gcompat`. Node is the Alpine build.
- **No Chromium in the rootfs.** Playwright cannot run a browser here; the browser is always the app's own WebView (the `Browser` tool's device backend, `nanomuse-browser` from scripts — [browser.md](browser.md)). `apk add chromium` does install but does not start under PRoot on Android.
- **Storage.** About 330 MB after unpacking, plus whatever the user installs. The compressed rootfs is under 70 MB; the APK a little more.
- **Background limits.** Android may still kill the service under memory pressure or aggressive vendor battery managers (the per-vendor battery allowances are in [android.md](android.md)). The service is `START_STICKY` and restarts; the scheduler catches up on missed routines.
- **What is in the box.** Alpine's `apk`, `git`, `curl`, `jq`, `bash`, `openssh-client`, `python3` with `pip`, and Node with `npm`. `uv` is not (35 MB); `pip install uv` gets it. `nanomuse-mirror cn|default` switches apk, pip and npm between the upstream servers and mirrors in mainland China; the first start picks from the phone's region.
- **Node is optional.** `NODE=0 scripts/rootfs/build.sh` produces a rootfs without it, about 12 MB smaller compressed. The default includes it because the showcase's Chinese services (lark-cli, `@tencentcloud/tmeet`, `12306-mcp`) are npm packages.

## Building the pieces

```bash
# the root file system (Docker with QEMU for arm64: docker run --privileged --rm tonistiigi/binfmt --install arm64)
scripts/rootfs/build.sh                # → dist/rootfs/nanomuse-rootfs-<ver>-aarch64.tar.xz + .json,
                                       #   copied to android/app/src/local/assets/rootfs.{tar.xz,json}
APK_MIRROR=https://mirrors.aliyun.com PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  scripts/rootfs/build.sh              # the same, with mirrors for the build machine only
scripts/rootfs/build.sh --platform linux/amd64 --no-install   # the same image for your computer, to poke at

# PRoot (needs the Android NDK)
ANDROID_NDK_HOME=~/Android/Sdk/ndk/27.2.12479018 android/native/build-proot.sh
                                       # → android/app/src/local/jniLibs/arm64-v8a/libproot{,-loader}.so

# the app
cd android && ./gradlew assembleLocalDebug assembleConnectDebug   # app/build/outputs/apk/{local,connect}/debug/
```

`scripts/rootfs/Dockerfile` is the whole recipe: a wheel stage builds `nanomuse` from the checkout, the rootfs stage installs Alpine packages, Python and the wheel into `/opt/nanomuse`, Node when asked, the two helper scripts (`nanomuse-serve`, `nanomuse-mirror`), then trims tests, docs and caches. `/etc/nanomuse-rootfs` stamps what went in. The size gate (`ROOTFS_MAX_MB`, 80) fails the build when the compressed tar outgrows the budget.

PRoot is built from the [Termux fork](https://github.com/termux/proot) (`5.1.107.94`, which carries the Android fixes: `--link2symlink`, ashmem/memfd, the loader as a separate file) with talloc `2.4.3`, both pinned by SHA-256, with the NDK's clang for API 26. PRoot is GPL-2.0; it runs as a separate executable that the app starts, and is not linked into the app. Its notice and the source offer are in `THIRD_PARTY_NOTICES.md`.

In CI, `rootfs.yml` builds both and `android.yml` (which calls it) puts them into the `local` APK; the compressed rootfs and its `.json` are attached to every release next to the APKs.

## Files

| File | Does |
| --- | --- |
| `android/app/src/main/java/…/runtime/LocalRuntime.kt` | Install (unpack with progress, swap, version marker), the PRoot command and environment, network files, fake `/proc`, logs |
| `…/runtime/TarUnpacker.kt` | A tar reader for the root file system: ustar / PAX / GNU long names, symlinks, hard links, modes; refuses entries that would escape |
| `…/runtime/RuntimeService.kt` | The foreground service: start, health, restart with backoff, `/ws` → notification text and wake lock, the Stop action |
| `…/Notifier.kt` | Events → notifications, shared with `NotifyService` (remote mode) |
| `nanomuse/runtime.py` | `device()`: the phone as the Python side sees it; the `device` MCP server |
| `nanomuse/bridge/` | Tokens, the server side (`/api/bridge/*`), the three CLIs |
| `scripts/rootfs/` | Dockerfile, `build.sh`, the two scripts inside the rootfs |
| `android/native/build-proot.sh` | PRoot + talloc with the NDK |
