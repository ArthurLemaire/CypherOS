# nanoMuse as an app on a simulated phone

Muse lives on a phone: it sits among your other apps, and when it needs you — an approval, a
question, something it finished in the background — it comes through the notification shade.
This directory makes nanoMuse behave that way inside [MobileGym](https://github.com/Purewhiter/mobilegym),
a browser-hosted Android simulator with a launcher, a notification shade and 28 re-implemented
apps (WeChat, Alipay, 12306, …). No device, no emulator: one browser tab.

<p align="center">
  <img src="screenshots/setup.png" width="24%" alt="First launch: connect the phone to your nanoMuse server">
  <img src="screenshots/heads-up.png" width="24%" alt="A heads-up notification from nanoMuse on the home screen, badge on the icon">
  <img src="screenshots/shade.png" width="24%" alt="The notification in the shade">
  <img src="screenshots/app.png" width="24%" alt="Tapping it opens nanoMuse on that chat">
</p>

`apps/nanoMuse/` is an app module in MobileGym's own format (manifest, entry component,
navigation declaration, Zustand store — see the platform's app module contract). It is a thin
shell around the real nanoMuse web app:

- **The app** shows the nanoMuse web app full screen, served by `nanomuse serve` on your
  computer. Everything you see is the same code a real phone gets; the shell only keeps the
  tab bar clear of the simulator's gesture bar.
- **Notifications** — real phones get Web Push. The simulator has no push service, so the
  module keeps one WebSocket to the server open for the whole simulator session (the store is
  loaded at boot, before any app is opened) and turns the events a phone would be notified
  about into simulated Android notifications: *Muse needs your approval*, *Muse has a
  question*, and the last word of a background pass or check-in. Tapping one opens nanoMuse
  on that chat. A card you decide from another device takes its notification down again; the
  launcher icon carries the unread badge.
- **Setup** — on first launch the app asks for the server address; paste the link
  `nanomuse serve` prints (it carries the access token). The token is checked by opening the
  server's WebSocket once, so the server needs no CORS configuration.
- **The phone as the agent's hands** — with *Let nanoMuse operate this phone* ticked on the
  setup page (on by default), the module also announces the simulator as a *device*: it lists
  the installed apps, and answers the server's requests for the screen and for actions. The
  screen is read from the simulator's DOM into the element list the agent works from — buttons,
  fields and their text, what is scrollable, what the keyboard covers, coordinates in the
  phone's 360×800 — and actions go through MobileGym's own input API, so a tap lands the way a
  finger would. Nothing is touched unless the server's own *Phone* switch is on too
  (`[gui] enabled`, or Connections → Phone in the app); [docs/gui.md](../../docs/gui.md) has the
  rest, including what asks for approval first.

The lighter variant needs nothing installed: open the simulator's own Browser app and go to the
link `nanomuse serve` prints. That is the web app as any phone browser gets it — full screen, tab
bar, approval cards — minus the notifications, which is what this module adds.

## Run it

Node 22+, Python 3.11+, a Chromium-based desktop browser. MobileGym's 1.9 GB companion
dataset is optional here: nanoMuse does not need it, the simulated media apps just render empty
without it.

```bash
# 1. nanoMuse, as usual — prints a link with a one-time token
nanomuse serve --port 8787

# 2. MobileGym with the nanoMuse app installed
git clone --depth 1 https://github.com/Purewhiter/mobilegym.git
demo/mobilegym/install.sh mobilegym          # copies apps/nanoMuse into the checkout
cd mobilegym && npm install && npm run dev   # http://127.0.0.1:3000
```

Open the simulator, find **nanoMuse** in the launcher (search works too), paste the link from
step 1, *Connect*. Then go back to the home screen and give the agent something to do from
another tab or the CLI — `nanomuse chat`, or the web app in a normal browser tab: the phone
lights up when it needs you.

To watch it operate the phone, turn the *Phone* switch on (Connections → Phone in the web app,
or `NANOMUSE_GUI_ENABLED=1` for step 1) and ask, in the chat, for something that lives in one of
the simulated apps — "打开微信，看看最新一条消息是谁发的", "用 12306 查一下明天北京到上海最早的
高铁", "给 blank. 回一句「好的，明天见」". The agent opens the app on the simulated phone, works
through its screens, and stops at the send button until you approve.

`install.sh` only copies files; MobileGym discovers apps by directory convention, nothing in the
checkout is edited. Run it again after pulling a newer nanoMuse.

## Notes

- **Origin.** The web app runs cross-origin inside an `<iframe>` (`127.0.0.1:8787` inside
  `127.0.0.1:3000`). That is fine for using it; it only means the outer page cannot script the
  inner one, which is the point of an iframe.
- **Dark mode.** The web app inside the frame follows the browser's colour scheme (it cannot
  see the simulator's); the setup page follows the simulator's.
- **Deep links.** The OS hands the app `/?thread=<id>`; the shell forwards `thread` and `tab`
  to the web app's own deep links (`docs/app.md`).
- **Not a MobileGym benchmark task.** The module declares its UI states and transitions like
  every MobileGym app, so the platform's analyzer sees it, but nanoMuse's content is live
  server output and is not deterministic — it is here to show the product, not to be graded.

## Layout

```
apps/nanoMuse/
├── manifest.ts               id, names, icon, theme, splash
├── NanoMuseApp.tsx           entry: router, theme vars, back handling, deep links
├── navigation.declaration.ts routes (/ and /setup), transitions, UI states
├── navigation.ts             go()/back() over the declaration
├── navigation.types.ts       re-exports the platform's shared types
├── state.ts                  Zustand store: server URL, token, notify and GUI switches; wires the bridge
├── bridge.ts                 WebSocket → NotificationService; device announce, screen/act requests
├── gui.ts                    the simulator as a device: DOM → element list, actions → __SIM_INPUT__
├── pages/MusePage.tsx        the web app, full screen
├── pages/SetupPage.tsx       server address, token, the operate-this-phone switch
├── hooks/useNanoMuseGestures.ts
├── data/                     defaults
└── res/icons.tsx
```
