# Changelog

All notable changes to nanoMuse. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/). Unreleased changes are on `main`.

## [0.1.13] - 2026-09-25 · Reach

The phone drives your computer, as a working demo. A small companion on the PC — one Python file, standard library only — is paired with the app by a six-digit code on the same network; from then on a sentence on the phone runs there: a command in its shell, a file fetched or dropped, a page opened in its browser, a look at its screen. The results come back to the phone, and so do the approvals: a command for the computer is judged by the same `ShellGuard` as the phone's own shell and waits for the same card before it is sent. One way — the phone drives the computer, never the other way round.

### Added

- **`host/nanomuse_host.py`** — the companion. `python3 nanomuse_host.py` prints the computer's LAN address and a pairing code (six digits, ten minutes, one phone, five wrong tries lock it) and serves JSON over HTTP: `POST /pair` (code → bearer token; only the token's SHA-256 is kept in `~/.nanomuse/host.json`), `GET /info`, `POST /shell` (`command`, `cwd`, `timeout` ≤ 15 min; exit code, stdout and stderr capped at 200 KB, `timed_out`), `GET /files?path=`, `GET /file?path=` (≤ 50 MB), `PUT /file?path=`, `POST /open` (`http(s)`/`file` URLs only, the default browser), `GET /screen` (mss + Pillow when installed, else `screencapture` / `grim` / `gnome-screenshot` / `spectacle` / `import` / `scrot` / PowerShell; 501 when nothing works). `--forget` drops every paired phone; `--no-pair` starts without a code. `tests/test_host.py` (9 tests) drives it end to end on Linux, macOS and Windows in CI.
- **`nanomuse-pc`** (`io.github.nanomuse.reach.ReachOffloadHandler`): `status` (which paired computers answer), `run "<command>" [--on <computer>] [--cwd] [--timeout]`, `ls [<path>]`, `get <remote> [--name]` (into the chat's attachments; pictures come with a `markdown` line), `put <local> <remote> [--force]` (never overwrites quietly: an existing file needs `--force`, and `--force` needs the card), `open <url>`, `screen` (a picture of the computer's screen into the attachments). Exit codes 0 ok · 1 failed · 2 usage · 3 no computer / refused · 4 the user said no. When the host does not answer, the reply says so and points to the setting.
- **Approvals on the phone** (`GuardKind.COMPUTER`): a command for the computer goes through `ShellGuard.assess` and `RiskGate` exactly like one for the phone; the card and the notification add *On the computer “desk”, not on this phone.* Grants are kept apart from the phone's (`pc:` targets), so *always allow* for a folder here never covers the same folder there.
- **Settings → Computers** (`io.github.nanomuse.ui.reach.ComputersScreen`, `minis://settings/computers`): the paired computers with system, address and when each last answered — tap to check, *Forget* to drop the key; *Pair a computer* in two steps (run the script, enter the address and the code) with the errors the host returns in plain words; *How it works* in four lines (judged like the phone's shell; runs as you; local network, no encryption yet; the computer never reaches into the phone). The Settings list shows the count.
- **The agent knows its computers** (`Computers.promptParagraph`): which are paired, the verbs, the one-way rule, and — with none paired — the one-time pairing it should explain instead of pretending.
- `Computers` (store + OkHttp client, tokens in the app's private preferences); `ReachTest` (4 tests); en / zh / zh-TW strings (`nm_pc_*`, `nm_risk_desc_on_computer`, `nm_risk_preview_computer`); CI lints and formats `host/` with the Python line.

### Changed

- versionCode 14; installs over 0.1.12 without losing data.

### Known issues

- No TLS between the phone and the computer in this version: the token travels in clear on your local network. Use a network you trust; `--forget` when a phone is gone. Certificates pinned at pairing are the plan for the next Reach step.
- The address is typed, not discovered: when the computer's IP changes (DHCP), forget and pair again — mDNS discovery is not in yet.
- `put` reads the whole file into memory on both sides; fine for documents and pictures, not for gigabytes.
- The computer's screen is a picture for the agent to look at, not yet a hand: mouse and keyboard on the PC (the UI-TARS-style operator) come later, on the same host.

## [0.1.12] - 2026-09-25 · Hands

The phone's screen as a hand, as a working demo. For the apps that have no API — 12306, 微信, 支付宝, 美团 — the agent can now use the phone the way you do: it looks at a screenshot, decides one action, taps, types or swipes, and looks again. Perception is the screenshot alone; no accessibility tree is read. The accessibility service is only the hand — it takes the screenshot, performs the gesture and types into the field that has the cursor. A capsule at the top of the screen shows each step with *Stop*; logins, passwords and codes are handed to you; a tap that pays, sends, posts or deletes waits for the same approval card as the shell and the browser. Off by default, under *Settings → Hands*.

### Added

- **`nanomuse-hands`** (`io.github.nanomuse.hands.HandsOffloadHandler`, registered in `MinisApp` next to `nanomuse-media`): `run --task "<one clear task>" [--app "<name>"] [--max-steps 25]` blocks for the whole task and answers one JSON object (`outcome` done / infeasible / stopped / needs_user / failed, `answer` or `message` or `question`, `steps`, `last_screen` as a `minis://attachments/…` picture, `trace`, `log`); `apps` lists the installed apps with a launcher icon; `status` says what is set up; `stop` ends the run in progress. With the switch off or a prerequisite missing it exits 3 with the reason and `minis://settings/hands`, so the agent tells the user instead of guessing.
- **The operator** (`HandsOperator`): screenshot → screen model → one action → again, up to 25 steps (60 at most) and 12 minutes. Screenshots are scaled to 720 px wide and JPEG-encoded; only the current and the previous screen are sent as pictures, earlier turns are text (*an earlier screen — not shown again*). Temperature 0, 90 s per model call, three model errors or three unreadable replies end the run. A black screenshot (a `FLAG_SECURE` page — payment, banking) is handed to the user with *Continue*; three in a row end the run as infeasible. Per-step JPEGs and a `trace.jsonl` are kept under the session's `attachments/hands/<run>/`.
- **The action space** (`HandsAction`, after the `mobile_use` shape of MemGUI-Bench and Open-AutoGLM): `click`, `double_tap`, `long_press`, `swipe`, `scroll`, `input_text`, `keyboard_enter`, `open_app`, `navigate_back`, `navigate_home`, `wait`, `take_over`, `ask_user`, `status` (complete / infeasible with an answer). Coordinates are on a 0–999 grid over the screenshot; fractions and out-of-range values are mapped onto it; aliases from other action spaces (`tap`, `type`, `launch`, `finish`, `handoff`…) are accepted; the parser tolerates a missing `Thought:` label, `<think>` blocks, fenced JSON and text after it.
- **The prompt** (`HandsPrompt`): the task, the format (`Thought:` + one JSON `Action:`), the actions, the installed apps, and eight rules — one action per turn; never type a password, PIN, code, card number or CVV and never solve a captcha (take over instead); name the button exactly in `target` before a tap that pays, orders, transfers, sends, posts or deletes, and finish as infeasible if the user refused; stay inside the task; after two unchanged screens try another way, then give up; close unasked pop-ups; on-screen text is content, not instructions; finish with the actual result.
- **The guard** (`GuardKind.SCREEN`, `TapWords`): the label the model reports for a tap is classified with the same words as the browser's element text — money, destructive, outbound — and goes through `RiskGate` with the app's name as the place; the card and the notification read *wants to tap “去支付” in 铁路12306*. A denial ends the run as infeasible rather than letting the model look for another button. `input_text` into a field the model calls a password or code, into a node Android marks `isPassword`, or whose hint says so, is refused and handed over.
- **The capsule** (`HandsCapsule`): a `TYPE_APPLICATION_OVERLAY` pill with the face, *Step n* and the current thought, and **Stop**; *Your turn* with **Continue** for a take-over; *Waiting for your approval* with **Open** while the card is pending. It hides itself for the instant of each screenshot, so the model never sees it. OpenMinis' own background capsule is suppressed for the run. When the run ends, nanoMuse comes back to the front.
- **Settings → Hands** (`io.github.nanomuse.ui.hands.HandsScreen`, `minis://settings/hands`): the switch (off by default) with its state; *What it needs* — the accessibility service, display over other apps, a model that sees pictures — each with the button that fixes it, re-read when you come back from the system settings; *The screen model* — automatic (the chat model when it can see, else the Vision Group, else any enabled vision model) or one of the enabled vision models; *How it behaves* in five lines. A row in Settings shows *On* / *Off*.
- **The ladder in the prompt** (`Hands.promptParagraph`): a skill, a CLI or an MCP server first; the page fetched with the user's login or `browser_use` second; the screen last, and the agent says which rung before it starts. When the hands are off or not ready, the paragraph says so and gives the link, and tells the agent not to fall back to `android-a11y-cli`.
- `HandsApps`: installed apps by label with a few aliases (微信 / WeChat, 支付宝 / Alipay, 12306, 美团, 京东, 抖音, 小红书, 高德…); the manifest `<queries>` gains `MAIN`/`LAUNCHER` so the list is visible on Android 11+.
- en / zh / zh-TW strings (`nm_hands_*`, `nm_risk_desc_screen`, `nm_risk_preview_screen`); `HandsActionTest` (12 tests) and `TapWordsTest` (7).

### Changed

- `BrowserGuard.judgeClick` uses `TapWords`; its regexes moved there unchanged, except that *Unsubscribe* is no longer read as a subscription (it is destructive).
- `HandsAction.Point.toPixels` rounds to the nearest pixel instead of truncating.
- versionCode 13; installs over 0.1.11 without losing data.

### Known issues

- A working demo: it needs Android 11 or newer (screenshots through the accessibility service), a vision model, and the two permissions. Apps that set `FLAG_SECURE` are black to it and handed to you. Typing goes through `ACTION_SET_TEXT` on the focused field, which some custom keyboards and web views ignore — the model is told to tap the field first and try again. The x86 emulator cannot run the arm64 APK; the flow was built and unit-tested, not driven on a device before release.

## [0.1.11] - 2026-09-25 · Hatch

A face of its own, and a first conversation the model runs. The bundled default avatar is now a small pale-yellow dragon — drawn with qwen-image-3.0-pro, posed for the five states with the same model, and shipped with four looping clips from MiniMax-H3, so a fresh install moves the way a custom face does. The first conversation no longer reads the user's reply with regular expressions: the chat model decides what "what should I call you?" was answered with, keeps the thread when the answer is something else, and proposes the agent's own names in the user's language. The image-and-video settings recommend one Alibaba Cloud Model Studio key for all three models while keeping a different provider per model possible.

### Added

- **The built-in dragon** (`res/drawable-nodpi/nm_avatar_{idle,working,waiting,happy,error}.webp`, 1024², ~170 KB together; `res/raw/nm_motion_{idle,working,waiting,happy}.mp4`, 768², 4 s, ~1 MB together). `AgentMood` carries the still and the clip for each state; the header, the studio preview and the notification icon use them, and the built-in face fills the disc like a custom one. The vector red panda is gone. `docs/avatar-moods.png` and the screenshots in `docs/screenshots/` are redrawn with the dragon.
- **Model-driven naming** (`io.github.nanomuse.onboarding.FirstConversation`, `nanomuse-naming`). While the first conversation waits for the form of address, the system prompt asks the model to decide what the user meant: an address → confirm it, ask what to call the agent and end with a `nanomuse-naming` block (`user_address`, two `suggest`ions); "nothing in particular" → the same with `null`; anything else → help with it first and bring the question back, no block. While the chooser is up, a name typed, "call you 豆丁" or "the first one" is reported as `agent_name` in the same block; other messages are answered and the chooser stays. The block is parsed in `nmAfterTurn` and rendered as nothing; the address goes to MEMORY, the name to SOUL.md; the phase is kept across restarts. Suggestions come from the model — two-character Chinese names in the spirit of 豆丁 or 小满 when the user writes Chinese, short English names like Pip or Wren otherwise — and never an existing assistant's name (Siri, Alexa, Cortana, Jarvis, Muse, Gemini, Copilot, 小爱, 小度, 小艺, 天猫精灵, 豆包, 文心, 通义, 阿福); the built-in fallback pools follow the same rule (豆丁, 小满, 团团, 叮叮, …; Pip, Wren, Juno, Remy, …). `FirstConversationTest` (6 tests).
- **One key for three models.** The *Image & video models* intro and the welcome screen's provider step say it plainly: one Model Studio key covers the chat model, `qwen-image-3.0-pro` and `MiniMax/MiniMax-H3`; each model is still chosen on its own, so any of them can come from another provider on another key. The video model follows the image model's provider when that provider is on Model Studio and nothing else was chosen; *No video model* is remembered as a choice. The image footer explains that qwen-image-3.0-pro both draws and poses. The avatar announcement mentions the clips being made when a video model is set.

### Changed

- `ImageGen.suggestedModel` for Model Studio is `qwen-image-3.0-pro`; `editDashScope` calls the 3.x models with their own parameters (`size`, `prompt_extend`, `watermark`) and keeps `qwen-image-edit-max` for older ones.
- `MediaModels.imageEndpoint` only reports an endpoint with a model name, so the model-driven explanation runs instead of the fixed fallback when the name is blank.
- The media page's status rows read `model · provider`; *Back to the built-in face* replaces *Back to the red panda*; the default description in the studio describes the dragon.
- versionCode 12; installs over 0.1.10 without losing data.

### Removed

- `FirstConversation.extractAddress`, `extractAgentName`, `interceptWhileChoosing`, `onUserNameReply`, `ChatViewModel.nmBeforeSend` — the heuristics the block replaces.

## [0.1.10] - 2026-09-25 · Motion

The face moves, and the three models are named. Muse has its image and video models built in; nanoMuse runs on three of your own — the chat model, an image model, a video model — and now says so in one place, in the settings and in the conversation. With a video model set, the avatar gets a short looping clip for each state: a head shake at rest, a crystal ball while it waits for you, a star when pleased, a laptop while it works. The agent can also make pictures and short clips on request through the same two models, and when one is missing it explains what to set up instead of pretending.

### Added

- **Settings → Image & video models** (`io.github.nanomuse.ui.media.MediaModelsScreen`, `minis://settings/media`). One page for the three models: the chat model (the default group, a row to its picker); the image model — a provider among those that can draw, the model name with the catalogue's quick picks, *Ready* / *Not set* / *Type a model name below*, and what stops working without it; the video model — opt-in, a provider on Alibaba Cloud Model Studio and `MiniMax/MiniMax-H3`, the *Animate the avatar after a change* switch, and a row for the current face's clips (n of 4, *Make* / *Redo*, the stage while it draws). The Settings list shows the row with *Not set* while no image model is usable; the avatar studio's *Image model* entries open this page.
- **The moving avatar** (`io.github.nanomuse.avatar.AvatarMotion`, `io.github.nanomuse.media.VideoGen`). After a new face is adopted and its poses are drawn, four 4-second clips are made in the background — one per state from that state's pose as the first frame, sequentially, through Model Studio's asynchronous video API (temporary upload → `video-synthesis` task → poll → download). The header and the studio play the current state's clip in a loop, muted, inside the same circle (`AgentAvatar.LoopingClip`: `TextureView` + `MediaPlayer`, first frame faded in, paused with the app), and fall back to the still pose where there is no clip. The status line reads *Animating 1/4…* meanwhile. Clips are cleared with the face they belong to.
- **`nanomuse-media`** (`io.github.nanomuse.media.MediaOffloadHandler`): a sandbox command for the agent. `image --prompt … [--from <picture>] [--size WxH]` draws or edits through the image model, `video --prompt … [--from <picture>] [--seconds 4-15]` makes a clip through the video model, `status` prints what is configured; results land in the session's attachments with a `markdown` line the agent puts in its reply so the file shows inline. When the model needed is not set, the command exits with a `tell_user` message and the link to the setting.
- **The agent knows its three models** (`MediaModels.promptParagraph`, appended to the system prompt): which are set, how to use `nanomuse-media`, and — when the image model is missing — to explain that changing its look or drawing needs one, that unlike Muse this is something the user sets up, and to link *Image & video models*. A "change your avatar to …" request with no usable image model goes to the chat model with a one-turn note (`SessionAddenda`), so the answer comes from the agent in the user's language rather than from a fixed string.
- en / zh / zh-TW strings (`nm_media_*`, `nm_avatar_status_animating`); `MediaTest` (6 tests: argv parsing, DashScope host detection, task-failure wording, motion prompts, the missing-model note, the CLI help).

### Changed

- `MediaModels.imageEndpoint` counts an image model as set only when it has a provider with a key *and* a model name; a provider the catalogue does not know shows *Type a model name below* instead of *Not set*, and the avatar flow no longer starts and fails with "set an image model first".
- The image-model sheet in the avatar studio is gone; its entries lead to the new page.
- versionCode 11; installs over 0.1.9 without losing data.

## [0.1.9] - 2026-09-25 · Portrait

The face, Muse's way. Changing the avatar is a sentence in the chat — "change your avatar to a corgi", with a reference picture if you like — answered by four takes in a 2×2 card; tap one or say "the second one", and the agent announces its new look while the poses are drawn. Behind the face is the agent's own page. The name pill under the face is re-measured against Muse's, and the face comes in five sizes.

### Added

- **Avatar change in the chat** (`io.github.nanomuse.avatar.AvatarFlow`, `ChatViewModel.nmInterceptAvatar`). Requests in Chinese and English are recognised before the model sees them — 把/将 … (虚拟)形象/头像 换成/改成/变成 X, 换个形象：X, 变成 X; change/switch/set (your/the) avatar to X, new avatar: X, become X. The first image attached goes in as a reference (`ImageGen.edit`). Four candidates are drawn in parallel into a 2×2 card (`AvatarOptionsCard`: numbered tiles, a breathing placeholder, per-tile retry, *Again*, *Keep current*); the pick is a tap or a typed choice (第二个, 2, "the second one", 左上, "last"; "again" redraws). The chosen face is adopted at once, the announcement is persisted with a `nanomuse-avatar` fence that renders as the frozen card (chosen tile highlighted), the poses land in the header as they finish, and a line goes into MEMORY. A draft main chat gets its session row first, and the reply is persisted with the request so the transcript never ends on an unanswered turn.
- **House-style prompts** (`AvatarStudio`). New default style *3D toy*: soft matte collectible-vinyl render, full body, facing the viewer, centred on pure white, square, one character; the four takes vary colouring, a lighter and a darker breed with an accessory, a playful outfit. Poses follow Muse's fixed set: headphones and a laptop (working), a crystal ball (waiting), a five-pointed star (happy), a sweat drop (error).
- **Share** (`io.github.nanomuse.avatar.AvatarShare`, `AvatarShareSheet`, `AvatarShareCard`). After the new look lands, a card offers to share it; the sheet shows five pastel 1080×1350 cards (the face on a rounded white card with a soft shadow, a speech bubble, the wordmark and tagline) and hands the chosen one to the system share sheet through the `FileProvider`. Also from the agent's page.
- **The agent's page** (`io.github.nanomuse.ui.profile.AgentProfileScreen`, `minis://settings/profile`), opened from the face or the name on any home tab: ×, share, the face with a pen badge (→ *Change avatar* / *Edit name* / *Avatar studio*), the name, *online*, and four panes — today's and yesterday's activity from the sessions (title, tools used or the reply, time; tap to open), approvals kept as *Always* with a link to Permissions, the daily routines with a link to Scheduled tasks, and the SOUL and Memory gradient cards with an *Edit* row for the name. *Change avatar* returns to the chat with "Change your avatar to " / "把虚拟形象改成" already typed and the keyboard up (`HomeBus.PrefillComposer`, `ChatViewModel.nmPrefillComposer`).
- **Avatar size** (`io.github.nanomuse.ui.avatar.AvatarSize`; *Settings → Appearance → Avatar size*): Small 44dp, Medium 56, Large 66, Extra large 76 (default), Hidden — the header follows live.
- Status lines *Generating options* / *Finishing the new look* while the flow draws; the face shows the working mood meanwhile.
- en / zh / zh-TW strings (`nm_avatar_*`, `nm_profile_*`, `nm_appearance_avatar_size*`); `AvatarFlowTest` (5 tests), `AvatarStudioTest` updated for the new prompts.

### Changed

- **Name pill** (`MuseHeader.MuseNamePill`), measured against Muse's screens: white, 14dp radius, 2dp shadow, 12×4dp padding, the name 14sp *regular* (it was 15sp SemiBold) and the status as an 11.5sp grey second line inside the pill instead of a separate row; the pill overlaps the face by 10dp.
- The setup is marked done the first time the home is shown, so an empty main chat (a draft with no session row) can no longer bring the welcome screen back after a trip to another page.
- versionCode 10.

### Fixed

- `AvatarStudio` (since 0.1.6) updated its four candidate slots with a read-modify-write from four coroutines; one result could overwrite another and leave a tile loading forever. The updates are atomic now (`MutableStateFlow.update`).

## [0.1.8] - 2026-09-25 · Polish

The shell, brought level with Muse's. Same features underneath; the type, the home composer, the header and every settings page now follow Muse's own screens rather than OpenMinis' iOS-style chrome.

### Changed

- **Type.** Muse renders in the phone's system face (MiSans on Xiaomi, Roboto elsewhere), so nothing is bundled; what changed is the scale. `MinisTheme` now builds its `Typography` from a Muse-like scale — zero tracking, 16/24 body, 14/20 and 13/18 secondary, SemiBold titles (17/22 for page titles) — instead of Material's defaults (`Theme.kt`, `museTypography()`); the user's text-size setting still scales it.
- **Home composer** (`ChatScreen.kt`, `ChatComposerWidgets.kt`). In the home shell the composer is Muse's one-row pill on a flat grey capsule (`MuseTones.bubble`, 26dp radius, no shadow, 16dp margins): a bare "+", the text with the placeholder *Message*, a bare mic; a blue send arrow replaces the mic once there is text or an attachment, and the stop button while the agent works. The "/" commands moved into "+" → *Commands*. Voice mode, recording and message editing fall back to OpenMinis' two-row card, which is unchanged elsewhere. The one `BasicTextField` is declared once and placed in either layout.
- **Header.** The rows under the agent's name — model group, provider · model — are off by default on the main chat, as on Muse, which shows only the name; the bar is 116dp instead of 136dp. *Appearance → Home → Show the model under the name* turns them back on, live (`AppearanceScreen.kt`, `KEY_NM_HEADER_MODEL`, `NmHomeChrome.rememberHeaderModelShown()`); with them off, ••• → *Model* opens the picker. The round header buttons lose their outline in the light theme and get a soft shadow, like Muse's discs.
- **Replies.** In the home shell the agent's text arrives in grey bubbles, one per paragraph, with no "✦ name" label above each turn — the face in the header says who is talking (`NmAssistantBubble`, wrapping `AssistantText`, `AssistantMarkdownBlock` and legacy content; a 6dp gap stands in for `AssistantHeader`). Code blocks, tables and HTML stay bare so they keep their width.
- **Settings** (`SettingsScreen.kt`, `SettingsComponents.kt`, `io.github.nanomuse.ui.muse.MuseChrome`). Muse's page: a round back disc, a centred 17sp title, white 16dp cards on the grey canvas, rows of one bare ink glyph + label + chevron, hairline separators, no section headers or subtitles. The main page opens with the model card (default group, provider · model, *Change*) where Muse has its plan card, then *Manage Providers* and *Token Usage*; the agent's card (Soul, Avatar, Memory, System files, Skills, MCP Integrations, Environment Variables); the phone's (Permissions, Background & notifications, Storage, Shared Folders, Mount External Folders, Backup & Restore); the app's (Appearance, Logs); About, Privacy Policy, Feedback; the version at the foot. Every entry OpenMinis had is still there.
- **Every settings sub-page.** `SettingsScaffold` and the 24 screens that draw their own bar now use `MuseTopAppBar`, a drop-in for Material's `TopAppBar` / `CenterAlignedTopAppBar`. `SettingsSection` labels are sentence-case grey text instead of small caps; cards are 16dp; `SettingsRow` draws its glyph bare in ink (22dp) instead of on a coloured tile; `SettingsChoiceRow` shows Muse's radio — a hollow ring, or an ink disc with a white check.
- `docs/screenshots/chat-approval.png` (and the web copy) retaken on this build.
- versionCode 9.

### Kept on purpose

- Every OpenMinis feature and setting; the two-row composer for voice, recording and editing; the status line under the name ("Needs approval", "Working…") and the naming card of the first conversation.

## [0.1.7] - 2026-09-25 · Welcome

The first run is back, in Muse's shape. A fresh install opens on a welcome screen — the mark, three steps, one blue button — instead of a chat that cannot answer: add a model provider, pick from the models it actually serves, meet the agent. The steps are OpenMinis' own provider and model screens.

### Fixed

- On phones, 0.1.3's home replaced the session list and with it the three-step setup OpenMinis shows before the first conversation (`OnboardingLanding` in `SessionListScreen`). A fresh install of 0.1.3–0.1.6 opened straight into the main chat with no provider; the reply to the greeting failed with "No provider configured" and the only way to a provider was Settings in the drawer. `NanoMuseHome` now shows `FirstRunSetupScreen` until the setup is done, and step 2 is OpenMinis' `OnboardingModelSelectionScreen`, which refreshes each enabled provider's catalogue and lists it.
- The main chat's `ChatViewModel` is not built before the setup is over; one built earlier resolved its model when no default group existed and kept whichever entry it found first.

### Added

- **Welcome screen** (`io.github.nanomuse.ui.onboarding.FirstRunSetup`): the N mark, "Welcome to nanoMuse", the three steps as rows with done / current / locked states, a blue *Continue* that performs the next step (*Start* on the last), *Skip for now* on step 2, the fine print that the key stays on the phone with *Learn more*, a gear to Settings. Gate: shown when there is no provider, or for a brand-new install (no sessions) until *Start* or *Skip for now* sets `setup.done` in the `nanomuse` prefs; loading is gated on `ProviderRepository.configLoaded` and the session list so a returning user never sees it flash.
- en / zh / zh-TW strings (`nm_setup_*`); `FirstRunSetupTest` (4 tests).

### Changed

- versionCode 8.

## [0.1.6] - 2026-09-25 · Avatar

The agent gets a face of your choosing. Describe it in a sentence, your own image model draws four, you pick one, and the app poses it for every state the agent can be in — then the face on the disc breathes, bobs, tilts, pops and shakes with what the agent is doing, the way Muse's does. Around it, the small motions that make an app feel finished: pages that cross-fade, feed cards that settle in, a heart that pops.

### Added

- **Avatar page** (`io.github.nanomuse.avatar`, `ui/avatar`; Settings → Avatar, or tap the face on any header). Muse's layout: the face on its disc with the agent's name and what it is doing right now, the preview cycling through the moods; *Describe a new face* — one sentence, a row of style chips (flat, 3D clay, watercolour, pixel, line art, sticker) and a blue *Draw four*; *Pick one* — a 2×2 grid of candidates with a shimmer while they draw, a check on the chosen one, and *Use this one*. Failed tiles say why and retry on tap. The ⋯ menu holds *Name and style* (the soul editor), *Image model*, *Redraw the moods* and *Back to the red panda*.
- **Bring your own image model.** Generation goes through the providers you already configured — no new key: any enabled OpenAI-compatible, OpenRouter or xAI instance, with the catalogue's image models offered as chips and a sensible default per host (`qwen-image-3.0` on Alibaba Bailian / DashScope, `gpt-image-1` on OpenAI, `grok-2-image` on xAI, `google/gemini-2.5-flash-image` on OpenRouter). Candidates use OpenMinis' `images/generations`; the four moods are image *edits* of the picture you chose — *working* wears headphones at a laptop, *waiting* looks up with a question mark, *happy* hugs a star, *error* has a sweat drop — through `images/edits` on OpenAI-style hosts and DashScope's native `qwen-image-edit-max` on Alibaba hosts, so the character stays the same. Two calls run at a time; rate limits are retried twice with a growing pause.
- **The face moves.** `AgentAvatar` cross-fades between moods (260 ms) and animates them: a slow breath at rest (2.6 s, +1.8 %), a quicker breath and a 2.5 dp bob while working, a ±4° tilt while it waits for you, a spring pop when a turn ends well, a 420 ms shake when it failed. A custom face fills the whole disc; the built-in red panda keeps its inset. The afterglow only reads outcomes from the run that just ended — a plain reply after an old failure smiles — and a run you stopped ends quietly.
- **Pictures stay on the phone**: `minis-global/nanomuse/avatar/{base,working,waiting,happy,error}.png` (512 px), `candidates/0–3.png` and `avatar.json` (prompt, style, model, time). Candidates survive restarts until you draw again; *Back to the red panda* removes the face and its moods but keeps the candidates.
- Motion elsewhere: home pages cross-fade (160 ms in, 120 ms out; the chat underneath fades a touch slower so the switch reads as one), new feed posts settle in and deleted ones fade out (`animateItem`), the like heart pops with a spring and its colour eases.

### Changed

- The header's face opens the avatar page; the name pill still opens the soul settings (name, style).
- Deep link `minis://settings/avatar` (also `/face`).
- versionCode 7.

### Kept, on purpose

- The built-in red panda is still the default and one tap away; the launcher icon is untouched. Provider instances, keys and OAuth are OpenMinis' own — the avatar page only reads what you configured there.

## [0.1.5] - 2026-09-25 · Memory

The agent starts to keep things: a feed it writes for you every morning, the files that make it what it is — who it is, what it knows about you, what it remembers, when it wakes — readable and editable in one place, and a way to bring over what another assistant already knew. Long tasks keep the screen on and ask "continue?" instead of wrapping up early.

### Added

- **Feed tab** (`io.github.nanomuse.feed`, `ui/feed`). A fifth glyph in the bottom bar. A built-in routine — *Write the feed*, daily at 08:00, visible under Goals → Routines with its switch, editor and run records like any other — asks the agent to read GLOBAL.md, the last seven days of diary, USER.md and the goals, and write three to six short posts. Each post is a fenced ` ```nanomuse-feed ` JSON block in the feed's own side chat ("Feed"); the app turns every block into `minis-global/nanomuse/feed/YYYY-MM-DD/NN.md` (front matter: title, type, emoji, source, created, liked) and the tab renders them as Muse's cards on a grey canvas — weekday + part of day as the section title, a 44 dp emoji tile, title, Markdown body, heart · *Discuss* · ⓘ. *Discuss* opens a side chat titled after the post with its text as the opener; ⓘ shows type, time, sources, the file path, and a delete. The first visit shows Muse's *About the feed* card with the steering sentence and *Edit* / *Got it*; the round sliders button at the top right opens the sheet — the sentence (`feed-preferences.md`, quoted in the feed's system prompt), the daily switch, "Daily at 08:00 · tap to change" (opens the routine editor), *Write it now*. Twelve posts a day at most; thirty days are kept.
- **System files** (Settings → System files; also in the ⋯ menu of every tab and the drawer). Muse's list: an `MD` badge, the file name, "MD · 358 B · 03:13", sort by name or by last modified, ⋮ to copy or share. Opening a file gives Muse's page: round back button, the name, a pill with the pencil and ⋯, an italic *About this file* quote, and the file rendered as Markdown. Five files: `SOUL.md` (the persona — saving refreshes the cached soul), `USER.md` (new — what the agent knows about you), `GLOBAL.md` (the memory; ⋯ jumps to OpenMinis' memory pages for the diary), `feed-preferences.md`, and `HEARTBEAT.md` — a read-only view of every routine and goal check with schedule and last run, with a ♥ badge. Edits use a monospace editor with a hint, Cancel and a blue Save.
- **USER.md in the system prompt.** When the file has content it is appended after the memory fragments, with one paragraph telling the model to keep it current from its shell (`/var/minis/memory/USER.md`) and never to put secrets in it. The file lives next to `GLOBAL.md` and `SOUL.md` in `minis-global/memory/` so the agent can reach it — the outline had it one level up.
- **Import memory** (System files → ⋯ → Import memory). One page: the prompt to give your other assistant ("gather everything you remember about me into bullet points…") with a copy button, a *From* field, a paste box, and *Add to memory*, which appends `### <date> · <from>` and the text under a `## 导入` / `## Imported` section at the end of `GLOBAL.md` (created if missing, recognised in either language).
- **Finished browser steps** keep their picture: the last live frame of the in-app browser is remembered per tool block (`BrowserFrames`) and shown when the step saved no screenshot of its own, and the floating status bar reads "Open test page · Done" for a completed `browser_use` step. The two levels of status stay as they were: the running tool's title under the face, the action chips on the cards.
- **Screen stays on** while the agent drives the in-app browser or another app through the accessibility service (`KeepAwake`, hooked in `ChatScreen` next to `isStreaming`; the a11y CLI handler stamps every command). Ordinary chat and shell work let it time out as usual.
- **"Still going after 200 steps".** When the agent loop reaches `MAX_AGENT_TURNS` it no longer writes an error into the chat; a card above the composer asks whether to keep going — *Continue* resumes from where it stopped, *Stop here* leaves OpenMinis' Resume banner in place. The card is cleared when you send, retry, clear the chat or switch sessions.
- `nanomuse-feed` blocks render as a small "Added to the feed" card with an *Open* button in the conversation where they were written.

### Changed

- `nmAfterTurn` also hands every completed turn to the feed parser; `buildSystemPrompt` appends the USER.md paragraph and, in the feed's session only, the feed protocol and a digest of the memory files and goals (≤ 7 000 characters).
- nanoMuse log categories no longer double the `nanoMuse.` prefix.
- versionCode 6.

### Kept, on purpose

- OpenMinis' memory pages (`GLOBAL.md` + diary) and the soul editor are unchanged; the system files pages open them for the parts they cover. The feed routine is an ordinary scheduled task — pause, edit or delete it like any other.

## [0.1.4] - 2026-09-25 · Guardrails

Before it deletes your files, sends something out or pays, the agent stops and asks — in the shell and in the browser. What you approve can be remembered per chat, or for good per recipient / host / folder. Passwords and verification codes are never typed by the agent; the browser is handed to you instead.

### Added

- **Shell guard** (`io.github.nanomuse.guard.ShellGuard`). Every `shell_execute` command is classified before it runs: *destructive* (`rm` outside scratch dirs, `find -delete`, `shred`, `truncate`, `git reset --hard` / `clean -f` / `checkout --` / `branch -D`, `gh repo delete`…), *outbound* (`git push`, `curl`/`wget` with a body or a writing method, `ssh`/`scp`/`rsync`/`nc`, mail clients, `lark-cli` write verbs, `gh` writes, cloud CLIs, package publishing, anything named like a sender), *money* (an outbound command that mentions paying, ordering, transferring…), *install* (`apk`/`apt`/`pip`/`npm i`/`cargo install`…) and *safe*. Pipelines, `&&`/`;` chains, `sudo`/`env`/`nohup` wrappers, heredocs and inline `sh -c` / `python -c` scripts are judged part by part; deleting under `/tmp`, `/var/tmp`, `/dev/shm` is free. Each classification carries an *object*: the folder (`/var/minis/workspace`, `/var/minis/shared`, or the first two path components), the host, the remote, the chat id, the recipient.
- **Approval card** (`RiskApprovalHost`, `RiskApprovalCard`). Destructive, outbound and money commands suspend the tool call and slide a card in above the composer, Muse's way: icon, "Allow Spark to delete in the workspace?", one line of what it means, the command in a grey preview box, and the buttons *Allow once* · *Allow for this chat* · *Always allow for the workspace* · *Deny*. The chat behind it dims; the header status reads *Needs approval*. Alarming shapes — wiping a whole tree, `dd`/`mkfs`, `curl | sh`, `chmod 777`, force push, fork bombs — get a warning card with only *Allow once* and *Deny*. Payments are asked about every time; there are no remembered approvals for money. Three minutes without an answer count as a denial.
- **Remembered approvals** (`Grants`, `minis-global/nanomuse/grants.json`). *Allow for this chat* covers the same class for the rest of that conversation and is dropped when the chat is cleared or deleted; *Always allow* is persisted per class + object. Settings → Permissions gets a *nanoMuse remembered approvals* section listing each standing grant with its date; tapping one revokes it.
- **Browser guard** (`BrowserGuard`). Before `browser_use` clicks or types, the target element is described in-page. A tap whose text or label reads like paying, ordering, sending, deleting, publishing or confirming a purchase asks first — the card shows the button text and the page URL, and *Always allow* binds to the host. Typing into a password field, a one-time-code field (`autocomplete`, name, id, placeholder, label, a numeric 4–8 digit code box, CVV) is refused outright: the tool result tells the model the field is the user's to fill, and the in-app browser is brought to the front on that page.
- **Background approvals.** If the app is in the background when a card is pending, a high-priority notification carries the same title and description with *Allow once* and *Deny* actions; tapping it opens that chat. The notification is cancelled when the card is answered from anywhere.
- **Policy paragraph in the system prompt** (`RiskPolicy`): what the app stops for, that the model should not ask twice, that a denial must not be retried or routed around, that passwords and codes are never typed, and that installs run with a one-line mention afterwards.
- 23 unit tests for the shell and browser classifiers (`app/src/test/java/io/github/nanomuse/guard`).

### Changed

- `executeShellCommand` runs the gate first; a denied command returns the denial to the model as the tool result and marks the tool card failed. Installs run without asking and append a one-line notice to the result.
- versionCode 5.

### Kept, on purpose

- OpenMinis' own confirmation for `minis-config` settings changes (`ConfigConfirmationGate`) and its per-category tool permissions are untouched; nanoMuse's grants sit above them on the Permissions page.

## [0.1.3] - 2026-09-25 · Home

The app opens on a conversation, not a list. One main chat with the face at the top, side chats in a drawer, and a bottom bar with Ideas, Goals and Library — the shape of Muse on a phone. Everything OpenMinis had is still there; it is reached from these pages instead of the old session list.

### Added

- **Home.** In compact windows the start route renders `NanoMuseHome`: a four-tab shell (chat, ideas, goals, library) whose chat pane stays composed under the other tabs, so switching tabs keeps the scroll position, the composer draft and a running stream. Tablet and landscape widths keep OpenMinis' two-pane scaffold unchanged. Deep links and notifications still open a full-screen chat on top.
- **Main chat.** The first session becomes the main chat and is remembered (`nanomuse` prefs); it is what the app opens on and what the chat tab returns to. Its header is Muse's: the face on a pale disc, the name pill hanging off its chin, a round menu button on the left and a round ⋯ on the right. Side chats get the compact header — title, menu, ⋯ — and take their title from the first exchange, as before.
- **The drawer.** Agent name, "Main chat", the side-chat list with search, an archive glyph that opens the full session list (OpenMinis' `SessionListScreen`, now at `nanomuse/all_chats`, handing the pick back to Home), settings, compose. Long-press a side chat to make it the main chat.
- **Goals.** A page with *Tracking* (goals with a checkbox, the latest note, cadence, next check and progress; ⋯ for open conversation / check now / pause / delete), *Routines* (OpenMinis' scheduled tasks — switch, schedule summary, run now, run records, editor, "All routines"), and *Create a goal* with seven categories. Creating one is a conversation: the sheet's "Let's go" sends an opener to the main chat with a two-turn system addendum; the model asks its questions and ends with a fenced ` ```nanomuse-goal ` block that the app turns into a goal card and a `goals.json` entry. Each goal gets its own session and a hidden interval `ScheduledTask` (`hidden`, `goalId`, `intervalMinutes` added to the model) that appends a one-line check to that session; the goal's context and the reporting protocol travel in that session's system prompt, and the model's ` ```nanomuse-goal-update ` block becomes a progress card and updates the row.
- **Ideas.** Twenty-four starters in six sections from `assets/nanomuse/ideas.{zh,en}.json`: emoji, pitch, what it does, and a sheet with one primary action — send to chat, create a routine (prefilled scheduled task, editor opens), or start a goal in a category.
- **Library.** *Artifacts* and *Media* segments listing what the agent wrote under `minis-sessions/*/workspace` and `minis-global/shared`, newest first, with type icons and image thumbnails, the conversation it came from, preview through OpenMinis' file preview, share via the file provider; ⋯ opens shared folders and the main chat's files.
- `nanomuse-*` fenced blocks render as cards in both the streaming and the static Markdown renderers.

### Changed

- The first-conversation and goal hooks now also run after *retry*, *resume* and queued prompts, not only after a plain send.
- The scheduled-task list hides goal checks; they are managed from the Goals page.
- Muse neutrals for nanoMuse pages (`MuseTones`): white surfaces, a warm disc under the face, grey fills — OpenMinis' iOS-grouped scheme is left as it is for its own screens.
- versionCode 4.

### Kept, on purpose

- Session list, scheduled tasks and their editor, shared folders, file browser and preview, terminal, model groups and every settings page are unchanged and reachable from the new pages.

## [0.1.2] - 2026-09-25 · Identity

The agent gets a face and a name, and the first conversation is where you meet it — the shape of Muse's first run, on top of OpenMinis's setup cards, which are unchanged.

### Added

- **The red panda in the chat header.** Above the name, 36 dp, drawn from the same shapes as the logo (`scripts/gen-avatar.py` derives five VectorDrawables from `web/src/components/redPandaShapes.ts`). Its mood follows the session: idle, working (breathing, narrowed eyes) while the model streams, waiting (round mouth) when an approval, a permission or a config confirmation is pending, happy for three seconds after a turn, error for four after a failure. Tap it — or the name pill under it — to open Settings → Soul (`minis://settings/soul`).
- **Muse's header.** The name sits in a capsule under the face; while the agent works the model rows give way to a status line (the running tool's title, "Thinking…", or "Waiting for you" in the accent colour) and come back when it is idle.
- **The first conversation.** With no sessions yet and the default name still in place, the first chat opens with a scripted greeting, how the agent works and "what should I call you?"; the reply is saved as the user's form of address in `GLOBAL.md` (`## About the user`), the model confirms in one sentence and asks for its own name, and a chooser card appears under that message — two suggestions and "Something else…", the composer's placeholder turning into "Write a name here". A pick or a typed name goes straight into `SOUL.md` (no `minis-config` round-trip, no approval gate); the header, the message labels and the placeholder rename at once, and the model's next reply — one line about the name, three concrete things it can do here, "what first?" — is steered by a system-prompt addendum that exists only for those two turns. The opening and the card are virtual UI rows: never in the database, never in the history a provider sees (Anthropic rejects a transcript that opens with the assistant). The opening is drawn again when the first session is reopened.
- **The name everywhere.** Notifications carry the face as their large icon and the Soul name as sender: the foreground service ("<name> is working"), background results, scheduled tasks, alarms, config confirmations, and the notifications the agent sends itself; the browser banner reads "<name> is browsing". Both happen through `scripts/rebrand.py` (`notification_faces`, the `%1$s` placeholder), so an upstream pull keeps them.
- **CI**: `.github/workflows/android.yml` builds a debug arm64 APK on ubuntu-24.04 for pushes and pull requests that touch the Android tree, and uploads it as an artifact. No signing, no secrets.
- `-Pnm.abi=x86_64` builds a chat-only test APK for the x86_64 emulator (the sandbox payloads are arm64-only).

### Changed

- The chat top bar no longer shows the session title; "Rename chat" moved to the ⋮ menu, and the Appearance switch "Show chat title" is gone (its `minis-config` key remains, inert).
- Copy in nanoMuse's voice for the welcome card, the onboarding subtitle and the service notification (en, zh, zh-TW; other locales keep upstream's wording). The Korean locale had 30 strings still reading "Minis" — `rebrand.py` now catches the particle-suffixed form.
- versionCode 3.

### Kept, on purpose

- The provider list and its OAuth sign-ins (Claude, Codex, Kimi, OpenRouter) and the three setup cards stay as in OpenMinis 1.13; there are no vendor presets yet.

## [0.1.1] - 2026-09-25 · Foundation

The first version of the Android line: [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 as nanoMuse, functionally identical to upstream. Pre-release; arm64 APK signed with the project key that every later version will use.

### Changed

- **The app is OpenMinis 1.13, imported with `git subtree` under `android/`** (unsquashed, 38 upstream commits in the history). The iOS half, the iSH submodule and iOS-only scripts are removed; `deps/proot` is a submodule pointing at our fork [nano-muse/proot](https://github.com/nano-muse/proot), whose `loader-info.awk` no longer needs gawk.
- **Identity**: application id `io.github.nanomuse.app` (the Kotlin package stays `com.openminis.app` for upstream merges), name nanoMuse in all 17 locales and in every user-facing string, the agent's default name and 🐾 header, the one-stroke N as adaptive launcher icon (white tile, brand gradient; a dark skin; Android 13 themed-icon layer; a flat status-bar mark for notifications), the brand blue `#015CFB` / `#58A6FF` instead of iOS blue and the teal Material scheme, one accent hue in chat (links, thinking, inline code, blockquotes, the send button, the user bubble).
- **Where things point**: update check on `nano-muse/nanoMuse` releases; About shows the licence, "Based on OpenMinis 1.13" and the Meta trademark note; Feedback opens a pre-filled GitHub issue form; the privacy policy is [docs/privacy.md](docs/privacy.md). The Telegram group and the mailbox are gone.
- **Licence**: the repository is GPL-3.0-or-later ([NOTICE](NOTICE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)); contributions need a DCO sign-off.
- **Build**: `scripts/rebrand.py` and `scripts/gen-android-icons.py` are idempotent and re-run after every upstream pull; `scripts/android/build-natives.sh` builds proot, the Alpine root file system and `rclone.aar`; `scripts/release-apk.sh <version>` builds, signs (`android/keystore.properties`, debug key otherwise), names and publishes. JDK 21, SDK CMake 3.22.1, NDK r27c, Go 1.26.

### Frozen

- The Python line (`nanomuse/`, `web/`, `demo/`, `site/`) at tag `pre-openminis`, the base of the web and desktop phases. Its unreleased changes below stay as the record of what it does.

## [Unreleased]

The first release: an open-source personal AI agent inspired by Meta's Muse. One agent that does the work while a Sentinel decides what may run; it reaches a service through its API, an MCP server, a command-line tool, a browser or — with the *Phone* switch on — the screen of the app on your phone. This release is the first phase of the plan: the phone, with the agent on your own machine and no cloud VM; the web on a per-user VM and the desktop come after ([docs/roadmap.md](docs/roadmap.md)).

### The agent

- **Tools**: web search (DuckDuckGo out of the box; Brave, Tavily or a SearXNG instance with a key or URL), web pages, files and pages in a workspace, shell and Python (each call in its own [bubblewrap](https://github.com/containers/bubblewrap) sandbox on Linux), mail, a browser view with take-over, calendar and contacts connectors, any [MCP](https://modelcontextprotocol.io) server.
- **Memory** you can read, edit and forget; recall by keyword and, with any OpenAI-compatible `/embeddings`, by meaning; a tidy-up with undo.
- **Goals** worked on over weeks while the app is closed, with check-ins on a schedule; **reminders and routines**; **triggers** that start work when mail arrives, an event is near or a webhook fires.
- **Skills** in the [Agent Skills](https://agentskills.io) format (`SKILL.md` folders), eleven built in — among them five for Chinese services that need no screen: `feishu` (飞书 through the official lark-cli: agenda, messages, events, tasks, documents), `tencent-meeting` (腾讯会议 through Tencent's tmeet CLI: meetings, invitations, recordings and minutes), `amap` (高德地图 through its MCP server: places, routes, distance, weather), `kuaidi100` (parcels through the 快递100 MCP server) and `train-tickets` (trains through the community 12306 MCP server — timetable, seats, prices, connections; booking on the phone's screen only when told to). [docs/services.md](docs/services.md) lists what has been run inside the phone's root file system, what has not, and what we will not recommend.
- **MCP servers** take `{{vault:NAME}}` placeholders in `url`, `args` and `env`, resolved at connect time; a call with no arguments sends an empty object (servers built on zod reject a missing one); the **sandbox** has `share` / `share_read_only` so a CLI and its login can be brought into the box (mirrored under the box's `$HOME`) while the rest of home stays out.
- **A feed** written for you from what the agent knows and what you asked it to follow; **ideas**; a **library** of everything it made.
- **Any OpenAI-compatible model**: Chat Completions or the Responses API, streaming, native or prompt-based tool calling; 阿里云百炼, OpenAI, OpenRouter, Ollama, vLLM, a gateway with its own headers. Pictures attached in chat go to models that take images.

### Sentinel

- The agent never touches a tool directly. A policy decides **allow / ask / deny** per call — by risk level, by rules you write, by taint (private data read earlier holds later egress to stricter rules) — and every decision lands in an audit log.
- **Approvals you scope**: once, this task, always; revocable from the app. Sends and payments on the phone are only ever *once*.
- A **credential vault**: secrets referenced as `{{vault:NAME}}` reach the tool, never the model.

### The phone

- **Operating the phone** (`[gui]`, off by default; *Connections → Phone*; `NANOMUSE_GUI_*`). Three tools when it is on: `phone_screen` (the screen as a picture with a caption), `phone_act` (one action by position, with a `label` saying what is under the finger), `phone_task` (a goal for the *phone operator*).
- **The operator** is a port of the `mobile_use` loop from [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench) (MIT): one screenshot per step, coordinates on a 999×999 grid, `Thought` / `Action` / one tool call, the history as one sentence per step, temperature 0. It never types passwords or codes and never confirms a payment it was not told to make; it asks instead. It works from the picture — no per-app integration — so it works in any app; a device that has an accessibility tree (the Android app) sends the elements along as a second input, for small text and for knowing a password field when it sees one.
- **The ladder**: the screen is the fourth rung, after a skill / CLI / MCP server, a fetch with the user's login, and the in-app browser. The system prompt says so, the agent announces a phone step before it takes it and asks first when it is climbing on its own; a skill declares its rung with `channel:` in `SKILL.md` (`api`, `cli`, `web`, `browser`, `gui`, `mixed`) and a `gui` skill is marked *on the phone's screen* in the agent's index; every audited tool call records its `channel`, and the Activity view shows how many of a session's steps were on the screen.
- **Sentinel on the screen**: reading a screen taints the session; a tap whose label names 确认支付, 转账, 提交订单, 发送, 删除 … (`sensitive_words`) or a step that types and submits at once is SENSITIVE with a warning and asks, once.
- **Traces**: every phone task is a JSONL file under `<data_dir>/phone-traces/`; `nanomuse phone traces` lists them, `nanomuse phone trace <id> -o trace.html` renders one with every screen and every tap drawn on it.
- **Devices**: a phone connects over the app's WebSocket, announces its apps and screen size, answers `screen` and `act`; the protocol and the finger-overlay spec are documented for other executors. The first device is the [MobileGym](https://github.com/Purewhiter/mobilegym) simulated phone: in-page screenshots, a ripple for every tap, a caption saying what Muse is doing.
- **Android operates its own screen** (Android 11+): the app's accessibility service takes the screenshot (downscaled to 720 px wide, taps scaled back), performs the gestures, presses Back / Home / Recents, opens apps, types through `ACTION_SET_TEXT` or the clipboard and refuses password fields outright; it sends the element tree with every screen. While a task runs a **capsule** sits over the operated app — the red panda, the current step and a **Stop** button; one tap ends the action in flight (`nanomuse:stop`), the operator finishes with `stopped` and the agent asks what to do instead of carrying on. When the agent needs you the capsule grows into a card with the question and *Open*. The finger is drawn as in the spec (rings, lines, typed text, caption) on a layer the screenshot never sees. *Connections → Phone → This phone* shows whether the service is on, opens the Accessibility settings, and explains Android 13's *Restricted setting* and the service being switched off by the system.

### The apps

- **The web app** (`nanomuse serve`): Chat, Feed, Ideas, Goals, Library, Connections, Permissions, Activity; approval cards and questions as they happen; artifacts with previews; push notifications with the app closed; English and 简体中文.
- **First run and identity**: setup is a three-item checklist — meet your nanoMuse, add a model, connect mail / calendar / contacts (optional) — with *Start* locked until a model is saved and the ticks kept across a reload. The name comes first (1–20 characters, six suggestions, empty means nanoMuse), then the avatar, a tagline, a tone (formal / casual / playful / concise), how much it says (short / detailed / bullet points), anything else in your own words, and what it calls you; each is its own paragraph of the system prompt. The name runs through the app, the approval and permission copy, Settings, the CLI banner and the MobileGym bridge. The model form groups providers by protocol with vendor subtitles — DeepSeek, Kimi, Qwen, GLM, 豆包, MiniMax, OpenAI (Chat Completions and Responses), OpenRouter, Ollama, any OpenAI-compatible endpoint — with a masked key, a *Get a key* link per vendor, `/v1` added to a bare host, no key for local endpoints, and the endpoint's own model list (`POST /api/llm/models`, catalogue fallback, a typed model never replaced). Bring your own key; there is no account with us and no OAuth login.
- **The red panda**: the agent's face is an SVG drawn live that changes pose with its state — idle (breathing, blinking, glancing about), working (typing at a laptop), waiting for you (a raised paw and a "!"), done (a bounce), failed (a shake), offline (asleep). Drawn simplified with soft 2.5D shading above 28 px and flat below (three levels of detail from one geometry, `redPandaShapes.ts`), it is also the logo: the web icon, the README cover, the Android launcher (flat, with a monochrome silhouette for themed icons and the status bar) and the launcher icon of the MobileGym app — all generated, none drawn twice. Six plush dolls and an emoji remain as alternatives.
- **The Android app**, two flavours. `nanomuse.apk` runs nanoMuse **on the phone itself**: a small Alpine Linux with Python, `nanomuse` and Node inside the APK (under 70 MB compressed), unpacked on first start and run under [PRoot](https://github.com/termux/proot) — a user-mode chroot, no root — with the WebView on `127.0.0.1`. A foreground service starts it, restarts it, holds a wake lock only while a task runs, and comes back after a reboot; your data lives outside the root file system and survives updates. `nanomuse-connect.apk` is the remote for a server on your computer: scan the QR code `nanomuse serve` prints, then the same app in a WebView with notifications. Both signed on every release ([docs/local-runtime.md](docs/local-runtime.md), [docs/android.md](docs/android.md)).
- **Keeping it running**: the scheduler and the phone share the schedule. The Python side knows the earliest moment anything is due (`next_wake_at` in `/api/upcoming`, a `schedule` event when it changes) and the local runtime sets one alarm for it — exact when Android allows it, inexact when it does not (Android 14 denies exact alarms to a fresh install), and `POST /api/tick` when it fires. *Settings → Keep it running* shows the battery, overlay and exact-alarm state with a button to Android's own page for each, a *Start after a reboot* switch, and the extra step vendor Android needs (小米, 华为 / 荣耀, OPPO, vivo, 三星, 魅族 — with a shortcut to the auto-start page). Crashes are written to a file on the phone and nowhere else; *Export logs* zips them with the app's recent logcat and the runtime's log for the share sheet.
- **The browser, on either side**: one browser tool with two backends — Chromium through Playwright on the server, with a persistent profile so logins survive a restart, or the phone's own WebView inside the app, offscreen on a private virtual display so pages run at full speed while the app is in the background. Same actions, same numbered elements, same frames in the chat; `mobile` / `desktop` / custom profiles; a `fetch` action that carries the browser's cookies for logged-in requests without a page. *Take over* in the app slides the real page up as a sheet (no reload), **Done** hands it back. A `wait` action for pages that draw themselves after `load`; the browser's own profile files never show up as artifacts. The device protocol is documented for other executors ([docs/browser.md](docs/browser.md)).
- **The phone's own capabilities** ([docs/device.md](docs/device.md)): on the phone the app runs a small MCP server on `127.0.0.1` that `nanomuse serve` picks up as the server `device` with no configuration — clipboard (read only while on screen, as Android has it), notifications, calendars (read, create, update, delete), contacts (read-only), location, alarms and timers through the clock app, photos through the system Photo Picker only. Each tool has its own Sentinel default (`DEVICE_TOOLS`); MCP servers in general take per-tool `tools.<name>` overrides now. Every permission is Android's own dialog — shown at once when the app is on screen, through a notification to tap when it is not — and the model is told whether the user declined or nobody answered. Reading notifications is not offered.
- **The workspace in the Files app** (local build): a `DocumentsProvider` shows the agent's workspace as a root in the system Files app and in open/save dialogs. **Share into nanoMuse**: text, links and files from any app's share sheet become a new conversation with the files uploaded and the text as a draft, waiting for what to do with them.
- **The CLI bridge**: inside the phone's sandbox, `nanomuse-device`, `nanomuse-browser` and `nanomuse-open` let any shell command or script use the phone's capabilities and the in-app browser through the server (`/api/bridge/*`) with a one-command token — as nested tool calls under the same Sentinel, on the same timeline. `nanomuse-open` is the box's `BROWSER`. The Python side knows when it runs on a phone (`nanomuse.runtime`) and describes its sandbox honestly.
- **The showcase** (`demo/showcase/`): a gateway that starts a private nanoMuse per visitor next to the simulated phone, with metered model access and bring-your-own-key; images published from CI.
- **Website**: `site/`, one static page in English and 中文 with the red panda playing a task end to end, published to GitHub Pages from `.github/workflows/pages.yml`.
- **The film**: a 66-second promo (`site/media/nanomuse-promo.mp4`) rendered frame by frame from `site/promo/storyboard.html` with Playwright and ffmpeg — the same markup and mascot as the app, so it can be re-cut by editing HTML.

### Command line

`nanomuse chat`, `run`, `serve`, `daemon`, `goals`, `reminders`, `triggers`, `calendar`, `contacts`, `skills`, `memory`, `vault`, `phone`, `audit`, `config`, `doctor`.
