# The Android app

`android/` is a native shell around the web app, in two flavours:

- **nanomuse.apk** (`local`) runs nanoMuse **on the phone itself**: the Python server, its tools and a small Alpine Linux live inside the app, unpacked on first start and run under a user-mode chroot. Nothing to install on a computer. arm64 phones, Android 8.0 or newer. How it works, what it can and cannot do: [local-runtime.md](local-runtime.md).
- **nanomuse-connect.apk** (`connect`) is the **remote for a `nanomuse serve` on your computer** — the same web app in a WebView, plus what a browser tab cannot do on a home network: notifications while the app is closed. Web Push needs `https://` and a push service in the middle; the app keeps its own connection to your server instead. Any CPU.

The local build offers both on its first screen (*Run on this phone* / *Connect to my computer*), so it is the one to download unless the phone is 32-bit or storage is tight.

What the shell adds over the browser tab:

- **Connect by QR code.** Scan the code `nanomuse serve` prints; no typing addresses or tokens.
- **Notifications in the background.** A foreground service keeps one WebSocket open to your server. Approvals, questions and the last word of background work arrive as Android notifications and open the right chat. A resolved approval takes its notification down again. Reconnects after a network change or a reboot.
- **Attachments, downloads, links.** The file picker for the paperclip, downloads to the phone's Downloads folder, links opening in the real browser.
- **The agent's browser.** While the app is connected, its own WebView is a browser the agent may use — offscreen, on a private virtual display so pages run at full speed with the app in the background — and *Take over* on a browser card slides that very page up for you to sign in or decide, then **Done**. In the local build this is the only browser there is; with a server it is used whenever the app is connected (`[browser] backend`). [browser.md](browser.md).
- **Plain HTTP on the LAN.** Works with `http://192.168.x.x:8787` as is.

Everything else is the same web app, served by your `nanomuse serve`.

## Install

Download [`nanomuse.apk`](https://github.com/nano-muse/nanoMuse/releases/latest/download/nanomuse.apk) (always the current release; the same file is also there as `nanomuse-<version>.apk`; the connect-only build is [`nanomuse-connect.apk`](https://github.com/nano-muse/nanoMuse/releases/latest/download/nanomuse-connect.apk)) and open it on the phone. Android asks once to allow installs from your browser or file manager. Android 8.0 (API 26) or newer. Every release is signed with the same key, so a newer APK installs over the old one and keeps its connection and data.

**Run on this phone**: tap it, wait for the unpack (about a minute; ~330 MB of storage), and the app opens on the onboarding: give the agent a name, paste a model API key. That is all; there is no computer involved. The runtime shows a quiet *Running on this phone* notification while it is up, comes back after a reboot, and can be stopped from that notification.

**Connect to my computer**: on the computer,

```bash
nanomuse serve --host 0.0.0.0
```

Tap **Scan QR code** and point the camera at the terminal. Or paste the printed link (`http://…:8787/?token=…`) into the field. The app checks the address and the token against the server before it keeps them.

The app on the phone and the server on your computer need to reach each other: same Wi-Fi, or a VPN such as Tailscale, or the server behind a reverse proxy with TLS (`https://` works too). See [deployment.md](deployment.md) for reaching the server from outside your network.

## Notifications

*Settings → Notifications → Let … notify this phone* turns the background connection on and off. While it is on, a silent "Connected to …" notification sits in the tray: that is Android's requirement for a service that stays alive, and it can be minimised in the notification's own settings. Turning it off stops the service; the web app itself still shows everything when it is open.

Updates arrive through the same connection, so there is nothing to configure on the server and no third party sees the content. In local mode the runtime's own notification carries the same role, and the approvals, questions and results come from the same code.

## Disconnect

*Settings → About → Disconnect from this server* forgets the address and the token and returns to the first screen. Uninstalling does the same. The token is stored in the app's private storage and excluded from cloud backups. In local mode, *Start over* on the failure screen returns to the first screen too, and keeps the phone's data (`files/home`); uninstalling removes it.

## Building it yourself

JDK 17 or newer and the Android SDK (Android Studio installs both). Then:

```bash
cd android
./gradlew assembleConnectDebug    # app/build/outputs/apk/connect/debug/app-connect-debug.apk
./gradlew assembleConnectRelease  # app/build/outputs/apk/connect/release/app-connect-release.apk
```

The `local` flavour also needs the root file system and PRoot in place first — `scripts/rootfs/build.sh` (Docker + QEMU) and `android/native/build-proot.sh` (the NDK) put them under `android/app/src/local/`; see [local-runtime.md](local-runtime.md#building-the-pieces). Then `./gradlew assembleLocalDebug`.

Without a signing key the release build is signed with the debug key, which installs fine but cannot update a build signed with a different key. To sign properly, create a key once and keep it outside the repository:

```bash
keytool -genkeypair -keystore ~/.nanomuse-release/nanomuse.jks -alias nanomuse \
        -keyalg RSA -keysize 4096 -validity 10950
```

and tell Gradle about it in `android/keystore.properties` (ignored by git):

```properties
storeFile=/home/you/.nanomuse-release/nanomuse.jks
storePassword=…
keyAlias=nanomuse
keyPassword=…
```

The same four values can come from the environment as `NANOMUSE_STOREFILE`, `NANOMUSE_STOREPASSWORD`, `NANOMUSE_KEYALIAS`, `NANOMUSE_KEYPASSWORD`.

## Releases

`.github/workflows/android.yml` builds the connect APK and runs the unit tests on every change under `android/`; on pushes to `main` and on `v*` tags it also calls `rootfs.yml` for the root file system and PRoot, builds both release APKs, checks the local one against its size budget (80 MB), and on a tag attaches `nanomuse-<version>.apk`, `nanomuse-<version>-connect.apk`, `nanomuse.apk` and `nanomuse-connect.apk` to the GitHub release — but only when it could sign with the release key, which the repository gets from four secrets: `ANDROID_KEYSTORE_B64` (the `.jks` file, base64), `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Without them the workflow still builds an APK signed with a throwaway debug key and keeps it as a workflow artifact; the maintainer then attaches the APK built locally with the real key. A debug-signed APK never goes on a release, because it could not be updated by a properly signed one.

The `versionName` in `android/app/build.gradle.kts` must match the tag, like the Python package's version does.

## How it is put together

| File | Does |
| --- | --- |
| `ConnectActivity.kt` | The first screen: *Run on this phone* (unpack, start, wait) / *Connect to my computer* (QR scan / paste, checks `GET /api/state` with the token) |
| `MainActivity.kt` | The WebView: loads `<server>/?token=…`, file picker, downloads, external links; the offline / starting / failure screen |
| `NotifyService.kt` | Remote mode: foreground service with an OkHttp WebSocket to `/ws?token=…` |
| `Notifier.kt` | Events → notifications, shared by both services |
| `runtime/RuntimeService.kt`, `runtime/LocalRuntime.kt`, `runtime/TarUnpacker.kt` | Local mode: the runtime on the phone ([local-runtime.md](local-runtime.md)) |
| `Bridge.kt` | `window.NanoMuseAndroid` — the web app uses it to show phone settings instead of Web Push, and to know the mode |
| `Prefs.kt` | Mode, server URL, token, the local port and token, the notifications switch, the agent's name |

The events the service reacts to are the same ones the web app draws cards for: `approval` / `question` with `status: pending` (and their resolution), and `assistant` events with `source: background` and `final: true`. `demo/mobilegym/apps/nanoMuse/bridge.ts` does the same job for the simulator, in TypeScript.
