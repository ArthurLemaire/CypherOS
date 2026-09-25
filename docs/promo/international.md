# English-language launch

The same story for readers outside China, in the project's voice. Copy blocks are pasted as
is. Pictures: the seven landscape cards in [cards/out-en/](cards/out-en/) (rendered from
`cards/cards-en.html`), the English cut of the film (`film/out/nanomuse-launch-en.mp4`) and
[film/approval.gif](film/approval.gif). The phone shots in the cards come from an English-locale
device except the approval sheet, which is the Chinese one — the card says so; a retake in
English is on the list in [shots.md](shots.md).

Order: the long post first (it is what every other link points at besides the README), then
Show HN on a weekday morning US time, the X thread the same day, Reddit over the following
days, Product Hunt last, after the first feedback has been folded back into the README.

## The long post

For the project blog if there is one, otherwise dev.to / Medium under the project's name. About
1,100 words. Header image: `cards/out-en/01-cover.png`.

```
nanoMuse: a fully open-source, Muse-style personal agent that runs on your phone

Meta released Muse in September. Put the models aside; what is worth looking at is the shape of the product. Not a chat box — an agent. It has a name and a face. The first conversation is an introduction. It writes you a feed every morning, keeps working on your goals in the background, remembers you, and stops to ask before it does anything you could not undo.

People have been describing this kind of agent for two years. Muse made it a finished consumer product.

But Muse is a service. Every user gets a VM in Meta's cloud; the phone, the web and WhatsApp are clients of it. The models are Meta's, the account is Meta's, and the VM has a browser but no way to reach the apps on your phone.

We thought this shape deserved an open-source version that runs on hardware you own. That is nanoMuse: a fully open-source, Muse-style personal agent for every device you own. Android today.

Four things define it, and all four are in the app.

**Muse-style.** One agent, not a toolbox. It names itself after your first chat (it proposed 小知 to the user in our footage, who was called 老周). A daily feed. Goals shaped in the chat and checked on a schedule in their own conversation. Memory you can read and edit. And a question before anything irreversible.

**Fully open.** The whole repository is GPL-3.0-or-later. No closed component, no account, no server you have to trust, no model you have to use. Every release is built from its tag, signed with one key, installed by hand. Muse is a product you are given; nanoMuse is one you own.

**Any app, API or not.** Most of the apps people actually live in — in China nearly all of them — never had an API. The agent climbs a ladder: a skill, a CLI or an MCP server first; then a page fetched with your login; then the in-app browser; and finally, when you allow it, the phone's own screen. It looks at a screenshot, decides one action, taps or types or swipes, and looks again. We use screenshots rather than the accessibility tree, because the tree in these apps is usually an empty WebView or a pile of unnamed nodes, and a screenshot is what a vision model already knows how to read. The accessibility service is only the hand: it takes the picture and injects the gesture; it does not read the screen. Logins, passwords and codes are handed back to you. Off by default. Since 0.1.12.

**Every device.** One agent; every device you own is a pair of hands and a doorway for it. Since 0.1.13 the phone drives your computer: one Python file on the PC (standard library, nothing to install) prints an address and a six-digit code; you type them into the app; from then on "check what the three newest files in ~/Downloads are called" runs on the computer and the answer — and the approval — comes back to the phone. One way, local network only, no cloud in between. A desktop app, iOS, a self-hosted web version and glasses come next, in that order.

**The approval, in a little more detail**

Before a shell command or a browser action runs, it is classified: deleting, sending, paying, installing. A hit stops the run and puts up a sheet: allow once, allow for this chat, always allow for this folder (or recipient, or domain), deny. Scoped grants are remembered and can be revoked under Permissions. Passwords and verification codes are never typed by the agent — not a setting, a missing capability. The rule is the same on every hand: the phone's shell, its browser, its screen, your computer.

**What it is built on**

The app is a modified OpenMinis 1.13 (GPL-3.0), pulled in with git subtree so upstream releases can still be merged. OpenMinis already had the hard part: a complete on-device agent — Alpine Linux under proot, a shell, a WebView browser, MCP, skills, scheduled tasks, an accessibility CLI, any OpenAI-compatible model. nanoMuse adds the Muse layer on top: one main conversation, the name and the face, the feed, the goals, the readable memory files, the approval gate, the hands, the reach to your computer. Its personality is a markdown file (SOUL.md); what it knows about you is another (USER.md); both sit under Settings → System files, editable.

Models are yours to bring: a chat model for everything, an image model for its face and your pictures, optionally a video model to make the face move. One Alibaba Model Studio key covers all three; or a different provider for each. Chats go to the model you chose and nowhere else; files, memory and pictures stay on the phone. There is no server, so there is nothing for us to see.

**What is not there yet**

Driving the screen sends a screenshot to a vision model every step: slow, and not cheap — a smaller vision model helps. It needs Android 11 or newer. The computer link has no TLS in this version, so use it on a network you trust. Releases are hand-installed APKs, not on any store. No iOS or desktop yet.

Fifteen small releases since 24 September, one APK each, notes for every one. Current: 0.1.15.

Repository: github.com/nano-muse/nanoMuse · Site: nanomuse.cn

nanoMuse is an independent community project, not affiliated with Meta Platforms, Inc.; Muse is a trademark of Meta Platforms, Inc.
```

## Show HN

Text posts on HN do not carry a picture; the GIF goes in the first comment, along with the
limits. Title under 80 characters. Post between 8 and 10 a.m. Eastern on a Tuesday to Thursday
and answer every comment for the first three hours.

Title:

```
Show HN: nanoMuse – an open-source, Muse-style personal agent that runs on your Android phone
```

Body:

```
Meta's Muse (September) is a personal agent as a service: a name, a face, a daily feed, goals worked on in the background, memory, an approval before anything irreversible — served from a VM per user in Meta's cloud, with thin clients.

nanoMuse is that shape of agent as free software, running entirely on your phone. GPL-3.0-or-later, no server, no account, bring your own OpenAI-compatible model.

It is a modified OpenMinis 1.13 (an on-device agent: Alpine under proot, shell, WebView browser, MCP, skills, scheduled tasks) with a Muse layer on top. Two parts I think are worth a look:

- Hands (0.1.12): for apps with no API, the agent looks at a screenshot, does one action through the accessibility service, and looks again. Screenshots, not the accessibility tree — in most Chinese apps the tree is an empty WebView. The accessibility service only takes the picture and injects the gesture. Logins/passwords/codes are handed back to you; the same approval gate (delete/send/pay → allow once / this chat / always for this scope / deny) applies as in the shell. Off by default.
- Reach (0.1.13): one stdlib Python file on your computer prints an address and a six-digit code; pair it in the app; a sentence on the phone runs on the computer and the result and the approval come back to the phone. One way, LAN only, no TLS yet.

Personality and memory are markdown files you can open and edit in the app (SOUL.md, USER.md).

Limits: driving the screen sends a screenshot per step to a vision model (slow, costs money); Android 11+ for that; hand-installed APKs; no iOS/desktop yet. 0.1.15, fifteen small releases since 24 Sept.

Repo: https://github.com/nano-muse/nanoMuse
Not affiliated with Meta; Muse is their trademark.
```

First comment (post right after):

```
The approval sheet in action (6 s): https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/promo/film/approval.gif — the UI follows the system language, so this one is in Chinese: "Allow 小知 to delete build-old in the workspace?" → allow once / allow for this chat / always for the workspace / deny.

Happy to go into the ladder (skill → CLI/MCP → fetched page → in-app browser → screen) or why screenshots over the a11y tree.
```

## X thread

Six posts. The first carries the English film (`film/out/nanomuse-launch-en.mp4`, under 2:20
and 512 MB is fine); the others carry one card each from `cards/out-en/`. Alt text on every
image.

```
1/ nanoMuse: a fully open-source, Muse-style personal agent that runs on your Android phone. A name, a face, a daily feed, goals in the background, memory you can read — and a question before anything it can't undo. GPL-3.0. No server, no account, your own model. [film]

2/ Four things define it, all in the app today: Muse-style · fully open · any app, API or not · every device you own. Details in the cards. [03-four-things]

3/ Before it deletes, sends or pays, it stops: allow once, for this chat, or always for this folder / recipient / domain. Passwords and codes are never typed by the agent — not a setting, a missing capability. [04-approval]

4/ Apps with no API: it looks at a screenshot, does one action through the accessibility service, looks again. Screenshots, not the accessibility tree. Logins go back to you. Off by default. Since 0.1.12. [02-muse-style]

5/ Your computer: one stdlib Python file prints a six-digit code, you type it into the app, and "check the three newest files in ~/Downloads" runs on the PC. Results and approvals come back to the phone. LAN only, one way. Since 0.1.13. [05-reach]

6/ Built on OpenMinis 1.13 (GPL-3.0), which already runs a whole agent on the phone — Alpine under proot, shell, browser, MCP, skills. We add the Muse layer. 0.1.15, fifteen releases since 24 Sept. github.com/nano-muse/nanoMuse — not affiliated with Meta; Muse is their trademark. [07-install]
```

## Reddit

Three subreddits, three angles, three separate posts a day or two apart. Each is a text post
with one image or the GIF; Reddit readers punish copy-paste across subs, so these are not the
same text. Reply in the first hours; the reply lines at the end of [posts.md](posts.md) hold in
English too.

### r/androidapps

```
Title: nanoMuse — an open-source Muse-style personal agent that runs entirely on the phone (GPL-3.0, sideloaded APK)

An agent with a name and a face that does things rather than answering: shell, browser, MCP and skills all inside the APK (Alpine Linux under proot), your own OpenAI-compatible model, no server and no account.

What's different from a chat app:
- It stops and asks before deleting, sending or paying — once / this chat / always for this folder — and never types passwords or codes.
- With Hands on (Settings → Hands, off by default) it can use apps that have no API: screenshot → one tap/type/swipe via the accessibility service → screenshot. It only takes the picture and injects the gesture; it doesn't read the accessibility tree. Needs Android 11+.
- Pair it with your PC (one Python file, six-digit code) and a sentence on the phone runs there.
- Its personality and memory are markdown files you can edit in the app.

Android 8.0+, arm64, hand-installed APK with a sha256 next to it, same signing key every release so updates install over the old one. 0.1.15.

Honest limits: driving the screen is slow and costs vision-model tokens; no TLS on the PC link yet; no Play Store. Repo: github.com/nano-muse/nanoMuse. Based on OpenMinis 1.13 (GPL-3.0). Not affiliated with Meta; Muse is their trademark.
```

### r/LocalLLaMA

```
Title: An on-device personal agent (Muse-style) where you bring the model — any OpenAI-compatible endpoint, including your own

nanoMuse is an open-source Android agent (GPL-3.0-or-later) in the shape Meta's Muse introduced — name, face, daily feed, background goals, editable memory, approvals — but the whole agent runs on the phone and the models are whatever you point it at.

Model side:
- Chat model: any OpenAI-compatible endpoint. A local server on your LAN works (llama.cpp / vLLM / Ollama's compat API); the app just needs the base URL and a key.
- For the screen-driving part (Hands) the chat model has to see images; every step is one screenshot → one action, so a small VLM is the economical choice.
- Optional image model for its avatar and pictures, optional video model for the animated face. One Alibaba Model Studio key covers all three if you want the easy path.
- Chats go only to the endpoint you configured; files, memory, screenshots stay on the phone. There is no server on our side.

Runtime: a modified OpenMinis 1.13 — Alpine under proot, shell, WebView browser, MCP, skills, scheduled tasks. Memory and personality are markdown files (SOUL.md / USER.md) you can open in the app.

Also pairs with your PC over LAN (one stdlib Python host, six-digit code) so a sentence on the phone runs on the computer, with the same approval gate.

0.1.15, APK on GitHub: github.com/nano-muse/nanoMuse. Not affiliated with Meta; Muse is their trademark.
```

### r/selfhosted

```
Title: nanoMuse host: pair your phone's agent with your PC using one stdlib Python file and a six-digit code (no cloud, LAN only)

nanoMuse is an open-source, Muse-style personal agent that runs on an Android phone. The part that may interest this sub is Reach (0.1.13): host/nanomuse_host.py is a single Python 3 file with no dependencies. Run it on a Linux/macOS/Windows box; it prints an address and a six-digit pairing code valid for ten minutes for one phone. Enter both in the app and the phone holds a key; the host stores only its hash.

From then on a sentence on the phone — "run the backup script", "grab ~/Downloads/report.pdf", "open the Grafana dashboard", "what's on the screen?" — is executed on the computer as you, and the result comes back to the phone. Every command is judged by the same gate as the phone's own shell: delete/send/pay stops and asks on the phone before the request reaches the host. Strictly one way (phone → computer); the host has no access to the phone.

Known gaps: no TLS in this version (use it on a network you trust), one phone per pairing code, no service file yet — run it in tmux or write your own unit.

GPL-3.0-or-later. Repo: github.com/nano-muse/nanoMuse (host file: host/nanomuse_host.py). Not affiliated with Meta; Muse is their trademark.
```

## Product Hunt

Launch after Show HN and Reddit, on a Tuesday or Wednesday at 12:01 a.m. PT. Gallery: the
seven cards in `cards/out-en/` (1600 × 1000) and the English film as the first slot.

- Name: nanoMuse
- Tagline (60): Open-source Muse-style personal agent, running on your phone
- Topics: Open Source, Android, Artificial Intelligence, Productivity
- Description (260):

```
A fully open-source, Muse-style personal agent for every device you own. Android today. It has a name and a face, does things instead of answering, keeps working when the app is closed, remembers you in files you can read, asks before anything irreversible — and runs on your phone with the models you bring. GPL-3.0.
```

- First comment (maker):

```
Hi PH — we make nanoMuse. Meta's Muse gave personal agents a shape we like: a name, a face, a feed, goals in the background, memory, an approval before anything irreversible. Muse is a cloud service; nanoMuse is that shape as free software, running entirely on your Android phone with your own model.

Two things I'd point you at: Hands — for apps with no API it looks at a screenshot, does one action, looks again (screenshots, not the accessibility tree; logins handed back to you; off by default) — and Reach — one Python file on your PC, a six-digit code, and a sentence on the phone runs on the computer, with the approval coming back to the phone.

It is built on OpenMinis 1.13 (GPL-3.0) and is GPL-3.0-or-later itself. Fifteen small releases since 24 Sept; 0.1.15 today. Limits are in the README (screen driving is slow and costs vision tokens; no TLS on the PC link yet; no iOS yet). Ask anything.

Not affiliated with Meta; Muse is their trademark.
```

## Before posting, everywhere

- The positioning sentence appears verbatim once: "A fully open-source, Muse-style personal agent for every device you own. Android today."
- Hands and Reach are shipped and were tried on a phone; the copy never says "demo", "coming soon" or "beta" for them.
- Version 0.1.15; fifteen releases since 24 September 2026; 200 steps before "continue?".
- The Meta trademark line and the OpenMinis / GPL line are present.
- Screenshots: no key, no real name, no hostname or LAN address (the pairing shots are pixelated where the host printed the computer's name).
- Do not claim a model is "local" unless the reader configures one; the footage used a cloud model (qwen3.7-plus on Alibaba Model Studio).
