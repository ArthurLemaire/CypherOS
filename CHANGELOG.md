# Changelog

All notable changes to nanoMuse. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/). Unreleased changes are on `main`.

## [Unreleased]

The first release: one personal agent in the shape of Meta's Muse, made to work in China — it does the work, a Sentinel decides what may run, and with the *Phone* switch on it operates the apps on your phone through their screens.

### The agent

- **Tools**: web search (DuckDuckGo out of the box; Brave, Tavily or a SearXNG instance with a key or URL), web pages, files and pages in a workspace, shell and Python (each call in its own [bubblewrap](https://github.com/containers/bubblewrap) sandbox on Linux), mail, a browser view with take-over, calendar and contacts connectors, any [MCP](https://modelcontextprotocol.io) server.
- **Memory** you can read, edit and forget; recall by keyword and, with any OpenAI-compatible `/embeddings`, by meaning; a tidy-up with undo.
- **Goals** worked on over weeks while the app is closed, with check-ins on a schedule; **reminders and routines**; **triggers** that start work when mail arrives, an event is near or a webhook fires.
- **Skills** in the [Agent Skills](https://agentskills.io) format (`SKILL.md` folders), seven built in — among them `train-tickets` and `phone-messages` for the phone, and `trip-plan`, which looks in 12306 when a phone is connected.
- **A feed** written for you from what the agent knows and what you asked it to follow; **ideas**; a **library** of everything it made.
- **Any OpenAI-compatible model**: Chat Completions or the Responses API, streaming, native or prompt-based tool calling; 阿里云百炼, OpenAI, OpenRouter, Ollama, vLLM, a gateway with its own headers. Pictures attached in chat go to models that take images.

### Sentinel

- The agent never touches a tool directly. A policy decides **allow / ask / deny** per call — by risk level, by rules you write, by taint (private data read earlier holds later egress to stricter rules) — and every decision lands in an audit log.
- **Approvals you scope**: once, this task, always; revocable from the app. Sends and payments on the phone are only ever *once*.
- A **credential vault**: secrets referenced as `{{vault:NAME}}` reach the tool, never the model.

### The phone

- **Operating the phone** (`[gui]`, off by default; *Connections → Phone*; `NANOMUSE_GUI_*`). Three tools when it is on: `phone_screen` (the screen as a picture with a caption), `phone_act` (one action by position, with a `label` saying what is under the finger), `phone_task` (a goal for the *phone operator*).
- **The operator** is a port of the `mobile_use` loop from [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench) (MIT): one screenshot per step, coordinates on a 999×999 grid, `Thought` / `Action` / one tool call, the history as one sentence per step, temperature 0. It never types passwords or codes and never confirms a payment it was not told to make; it asks instead. It works from the picture alone — no accessibility tree, no per-app integration — so it works in any app.
- **Sentinel on the screen**: reading a screen taints the session; a tap whose label names 确认支付, 转账, 提交订单, 发送, 删除 … (`sensitive_words`) or a step that types and submits at once is SENSITIVE with a warning and asks, once.
- **Traces**: every phone task is a JSONL file under `<data_dir>/phone-traces/`; `nanomuse phone traces` lists them, `nanomuse phone trace <id> -o trace.html` renders one with every screen and every tap drawn on it.
- **Devices**: a phone connects over the app's WebSocket, announces its apps and screen size, answers `screen` and `act`; the protocol and the finger-overlay spec are documented for other executors. The first device is the [MobileGym](https://github.com/Purewhiter/mobilegym) simulated phone: in-page screenshots, a ripple for every tap, a caption saying what Muse is doing. Android follows.

### The apps

- **The web app** (`nanomuse serve`): Chat, Feed, Ideas, Goals, Library, Connections, Permissions, Activity; approval cards and questions as they happen; artifacts with previews; push notifications with the app closed; English and 简体中文.
- **The Android app**: a native shell around the web app — scan the QR code `nanomuse serve` prints, then the same app in a WebView with notifications. Signed APK on every release.
- **The showcase** (`demo/showcase/`): a gateway that starts a private nanoMuse per visitor next to the simulated phone, with metered model access and bring-your-own-key; images published from CI.

### Command line

`nanomuse chat`, `run`, `serve`, `daemon`, `goals`, `reminders`, `triggers`, `calendar`, `contacts`, `skills`, `memory`, `vault`, `phone`, `audit`, `config`, `doctor`.
