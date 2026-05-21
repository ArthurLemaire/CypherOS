# The Android app

`android/` is a small native shell around the web app. It exists for one reason the browser cannot cover on a home network: notifications while the app is closed. Web Push needs `https://` and a push service in the middle; the Android app keeps its own connection to your server instead.

What it adds over the browser tab:

- **Connect by QR code.** Scan the code `openmuse serve` prints; no typing addresses or tokens.
- **Notifications in the background.** A foreground service keeps one WebSocket open to your server. Approvals, questions and the last word of background work arrive as Android notifications and open the right chat. A resolved approval takes its notification down again. Reconnects after a network change or a reboot.
- **Attachments, downloads, links.** The file picker for the paperclip, downloads to the phone's Downloads folder, links opening in the real browser.
- **Plain HTTP on the LAN.** Works with `http://192.168.x.x:8787` as is.

Everything else is the same web app, served by your `openmuse serve`.

## Install

Download [`openmuse.apk`](https://github.com/OpenMuseAgent/OpenMuse/releases/latest/download/openmuse.apk) (always the current release; the same file is also there as `openmuse-<version>.apk`) and open it on the phone. Android asks once to allow installs from your browser or file manager. Android 8.0 (API 26) or newer, any CPU. Every release is signed with the same key, so a newer APK installs over the old one and keeps its connection.

Then:

```bash
openmuse serve --host 0.0.0.0
```

Tap **Scan QR code** and point the camera at the terminal. Or paste the printed link (`http://…:8787/?token=…`) into the field. The app checks the address and the token against the server before it keeps them.

The app on the phone and the server on your computer need to reach each other: same Wi-Fi, or a VPN such as Tailscale, or the server behind a reverse proxy with TLS (`https://` works too). See [deployment.md](deployment.md) for reaching the server from outside your network.

## Notifications

*Settings → Notifications → Let … notify this phone* turns the background connection on and off. While it is on, a silent "Connected to …" notification sits in the tray: that is Android's requirement for a service that stays alive, and it can be minimised in the notification's own settings. Turning it off stops the service; the web app itself still shows everything when it is open.

Updates arrive through the same connection, so there is nothing to configure on the server and no third party sees the content.

## Disconnect

*Settings → About → Disconnect from this server* forgets the address and the token and returns to the Connect screen. Uninstalling does the same. The token is stored in the app's private storage and excluded from cloud backups.

## Building it yourself

JDK 17 or newer and the Android SDK (Android Studio installs both). Then:

```bash
cd android
./gradlew assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
./gradlew assembleRelease      # app/build/outputs/apk/release/app-release.apk
```

Without a signing key the release build is signed with the debug key, which installs fine but cannot update a build signed with a different key. To sign properly, create a key once and keep it outside the repository:

```bash
keytool -genkeypair -keystore ~/.openmuse-release/openmuse.jks -alias openmuse \
        -keyalg RSA -keysize 4096 -validity 10950
```

and tell Gradle about it in `android/keystore.properties` (ignored by git):

```properties
storeFile=/home/you/.openmuse-release/openmuse.jks
storePassword=…
keyAlias=openmuse
keyPassword=…
```

The same four values can come from the environment as `OPENMUSE_STOREFILE`, `OPENMUSE_STOREPASSWORD`, `OPENMUSE_KEYALIAS`, `OPENMUSE_KEYPASSWORD`.

## Releases

`.github/workflows/android.yml` builds the APK on every change under `android/` and, on a `v*` tag, attaches `openmuse-<version>.apk` and `openmuse.apk` to the GitHub release — but only when it could sign with the release key, which the repository gets from four secrets: `ANDROID_KEYSTORE_B64` (the `.jks` file, base64), `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Without them the workflow still builds an APK signed with a throwaway debug key and keeps it as a workflow artifact; the maintainer then attaches the APK built locally with the real key. A debug-signed APK never goes on a release, because it could not be updated by a properly signed one.

The `versionName` in `android/app/build.gradle.kts` must match the tag, like the Python package's version does.

## How it is put together

| File | Does |
| --- | --- |
| `ConnectActivity.kt` | QR scan / paste, checks `GET /api/state` with the token, stores server and token |
| `MainActivity.kt` | The WebView: loads `<server>/?token=…`, file picker, downloads, external links, offline screen |
| `NotifyService.kt` | Foreground service with an OkHttp WebSocket to `/ws?token=…`; turns events into notifications |
| `Bridge.kt` | `window.OpenMuseAndroid` — the web app uses it to show phone settings instead of Web Push |
| `Prefs.kt` | Server URL, token, the notifications switch, the agent's name |

The events the service reacts to are the same ones the web app draws cards for: `approval` / `question` with `status: pending` (and their resolution), and `assistant` events with `source: background` and `final: true`. `demo/mobilegym/apps/OpenMuse/bridge.ts` does the same job for the simulator, in TypeScript.
