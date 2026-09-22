# Configuration

OpenMuse reads one TOML file. `openmuse config init` writes a commented copy of [`config/config.example.toml`](../config/config.example.toml) to `config/config.toml`; `openmuse config show` prints the effective settings with secrets masked.

Search order:

1. `--config PATH` / `OPENMUSE_CONFIG`
2. `./config/config.toml`
3. `~/.openmuse/config.toml`

Any string value may contain `${VAR}` or `${VAR:-default}`; it is replaced with the environment variable when the file is loaded, so API keys never need to be written down. `api_key`, `address` and `password` may also be `{{vault:NAME}}`: the value is read from the encrypted vault when the client is built, never shown to the model.

Three layers, later ones win: the file, then environment overrides, then whatever was changed in the app's *Connections* screen (`<data_dir>/app-settings.json`: model, email servers, browser switch, MCP servers added from the phone). That last file only ever refers to secrets as `{{vault:NAME}}`.

## Environment overrides

These win over the file. They cover the settings people change most often and what Docker needs.

| Variable | Setting |
|---|---|
| `OPENMUSE_LLM_PROVIDER`, `OPENMUSE_LLM_MODEL`, `OPENMUSE_LLM_BASE_URL`, `OPENMUSE_LLM_API_KEY`, `OPENMUSE_LLM_TOOL_MODE` | `[llm]` |
| `DEEPSEEK_API_KEY`, `OPENAI_API_KEY` | used as `llm.api_key` when it is empty |
| `OPENMUSE_DATA_DIR` | `data_dir` (default `~/.openmuse`) |
| `OPENMUSE_WORKSPACE` | `agent.workspace` (default `./workspace`) |
| `OPENMUSE_SENTINEL_MODE` | `sentinel.mode` |
| `OPENMUSE_SERVER_HOST`, `OPENMUSE_SERVER_PORT`, `OPENMUSE_SERVER_TOKEN` | `[server]` |
| `OPENMUSE_BROWSER_ENABLED=1` | `browser.enabled = true` (only ever turns it on; the browser Docker image sets it) |
| `OPENMUSE_VAULT_KEY` | Fernet key for the vault (default: `<data_dir>/vault.key`) |
| `OPENMUSE_LOG_LEVEL` | `log_level` |

## `[llm]`

```toml
[llm]
provider      = "openai"           # "openai" = Chat Completions, "openai_responses" = Responses API
model         = "deepseek-flash"
base_url      = "https://api.deepseek.com"
api_key       = "${DEEPSEEK_API_KEY}"
max_tokens    = 4096
temperature   = 0.3
timeout       = 180                # seconds per request
max_retries   = 5                  # exponential back-off on 429 / 5xx / timeouts
stream        = true
tool_mode     = "auto"             # "auto" | "native" | "prompt" — see below
pass_reasoning = false             # send reasoning_content back with assistant turns (some DeepSeek endpoints)
extra_headers = {}                 # e.g. { "X-End-User-Id" = "openmuse" }
extra_body    = {}                 # e.g. { "thinking" = { "type" = "enabled" } }
```

Provider recipes:

| Provider | `model` | `base_url` | Notes |
|---|---|---|---|
| DeepSeek | `deepseek-flash` | `https://api.deepseek.com` | default |
| OpenAI | `gpt-5.6-sol` | `https://api.openai.com/v1` | `provider = "openai_responses"` also works |
| OpenRouter | `deepseek/deepseek-flash` | `https://openrouter.ai/api/v1` | |
| Ollama | `qwen3:8b` | `http://localhost:11434/v1` | `api_key = "ollama"`; see [Local models](#local-models) |
| vLLM / LM Studio | your served name | `http://localhost:8000/v1` | set `tool_mode = "prompt"` if the server ignores `tools` |
| Company gateway | as required | as required | use `extra_headers` / `extra_body`; pick the provider by the API shape the gateway speaks |

### Tool calling modes

| `tool_mode` | What happens |
|---|---|
| `auto` (default) | The API's function calling. If the endpoint *rejects* the `tools` field — Ollama for a model without a tool template ("does not support tools"), vLLM started without a tool parser — OpenMuse logs one warning and describes the tools in the prompt for the rest of the run. |
| `native` | Always the function-calling API; a rejection is an error. |
| `prompt` | Tools are described in the system prompt and calls are parsed from `<tool_call>` blocks. The only mode that works with endpoints that silently *ignore* `tools` (no error, the model just never calls anything) — some "agent app" gateways do this. |

### Local models

Ollama serves an OpenAI-compatible API at `http://localhost:11434/v1`; models with a tool template (Qwen 3, Llama 3.1+, Mistral, DeepSeek-R1 distills) call tools natively, the rest work through `auto`'s prompt fallback. [`scripts/provider_check.py`](../scripts/provider_check.py) runs five everyday tasks (chat, a calculation through `python_execute`, writing a file, remembering a preference, a multi-step job) against any model; results on an RTX 4070 (12 GB), Ollama 0.34:

| Model | Tool calling | provider_check | Notes |
|---|---|---|---|
| `qwen3:8b` | native (also 5/5 with `tool_mode = "prompt"`) | 5/5 | the default preset; 7–20 s per task |
| `llama3.2:3b` | native | 5/5 | often writes the call as a bare JSON object in the text and double-escapes newlines in file content; both are repaired (see below) |
| `gemma3:4b` | prompt, via the `auto` fallback | 5/5 | Ollama rejects `tools` for it; emits ```` ```tool_call ```` fences, which the prompt parser accepts |
| DeepSeek V4.1 Flash (hosted) | native | 5/5 | 1–4 s per task |

Small models bend the protocol in predictable ways, and OpenMuse meets them halfway rather than failing the task: a reply that is a bare or fenced JSON object naming one of the tools (with an arguments object) counts as a tool call in every mode; JSON strings may contain real newlines; `files.write` turns a one-line text with two or more spelled-out `\n` into lines (code, which has real newlines, is never touched). A quoted JSON object with other keys stays text.

Set `max_tokens` to what the model can produce in one turn (4096 is fine for these) and keep `agent.max_context_messages` modest — a local 8B model with an 8k context window fills up fast once tool results start coming back.

Models that emit `<think>…</think>` inside the content are handled: the reasoning is separated and shown only with `agent.show_thinking = true`.

## `[agent]`

```toml
[agent]
name                 = "Muse"          # what the agent calls itself (the app's profile overrides this)
max_steps            = 30              # tool calls per turn before it must wrap up
workspace            = "./workspace"   # the only directory the files tool can touch
language             = "auto"          # or a fixed language: "English", "中文", ...
max_context_messages = 80
show_thinking        = false
user_profile         = ""              # free text injected into the system prompt
instructions         = ""              # extra rules appended to the system prompt
```

With `language = "auto"` the system prompt names the language of the latest user message (detected by script) and tells the model to answer in it. A generic "reply in the user's language" instruction turned out to be unreliable with some models; naming it works.

## `[sentinel]`

```toml
[sentinel]
mode               = "ask"           # ask | strict | auto
always_ask_tools   = ["send_email", "shell"]
always_allow_tools = []
deny_tools         = []
taint_tracking     = true
egress_allowlist   = ["duckduckgo.com", "*.duckduckgo.com", "wikipedia.org", "*.wikipedia.org",
                      "github.com", "*.github.com", "*.githubusercontent.com", "pypi.org", "*.pypi.org"]
audit_file         = ""              # default <data_dir>/audit.jsonl

[[sentinel.rules]]                   # first match wins; values are glob patterns matched against str(arg)
tool   = "shell"
match  = { command = "*rm -rf*" }
action = "deny"                      # allow | ask | deny
reason = "recursive deletes are not allowed"
```

How the pieces combine is described in [sentinel.md](sentinel.md).

## `[sandbox]`

```toml
[sandbox]
mode = "auto"                        # auto | bwrap | off
```

On Linux with [bubblewrap](https://github.com/containers/bubblewrap) installed (`apt install bubblewrap`, `dnf install bubblewrap`), every `shell` and `python_execute` call runs in its own namespace: the workspace and `agent.extra_roots` are the only writable places, your home directory is not there, `/tmp` is private, and there is no network unless the call was assessed as needing it. `auto` uses it when it works here and says so in the log when it does not; `bwrap` insists (`openmuse doctor` fails otherwise); `off` runs commands unboxed, with the scrubbed environment only. Details and what changes for the Sentinel in [sentinel.md → The sandbox](sentinel.md#the-sandbox).

## `[memory]`

```toml
[memory]
enabled    = true
max_inject = 20        # memories injected into the system prompt per turn (keyword-ranked)
```

## `[skills]`

```toml
[skills]
enabled  = true
dir      = ""                        # your skills; empty → <data_dir>/skills
disabled = ["inbox-triage"]          # built-in ones to leave out of the model's list
```

A skill is a folder with a `SKILL.md` — YAML front matter with `name` and `description`, then the steps in Markdown — in the [Agent Skills](https://agentskills.io) format, so skills written for other agents work here. Five are built in (`weekly-review`, `trip-plan`, `inbox-triage`, `compare-options`, `meeting-prep`); a folder in `dir` with the same name as a built-in replaces it. The model gets the index (name and description of every enabled skill) in its system prompt and reads a skill's steps with the `skills` tool when a request fits; `/name` at the start of a chat message runs one directly. Saving or removing a skill from chat is a sensitive call — it asks first, whatever the Sentinel mode. Skills switched off in the app are remembered in `app-settings.json`; the list here and that one are merged. Inside the [sandbox](sentinel.md#the-sandbox) a skill's folder (its scripts and reference files) is visible read-only. See [the app → Skills](app.md#skills) and `openmuse skills` in the [CLI](cli.md#skills).

## Connectors

### Email

```toml
[connectors.email]
enabled       = true
imap_host     = "imap.gmail.com"
imap_port     = 993
smtp_host     = "smtp.gmail.com"
smtp_port     = 587
smtp_starttls = true
address       = "{{vault:EMAIL_ADDRESS}}"
password      = "{{vault:EMAIL_PASSWORD}}"
scrub_secrets = true   # remove one-time codes and reset links before the model reads a mail
```

Store the values with `openmuse vault set EMAIL_ADDRESS` and `openmuse vault set EMAIL_PASSWORD`. `read_emails` marks the session as tainted; `send_email` is in `always_ask_tools` by default.

### Calendar

Any calendar that offers a private iCalendar link — Google (*Settings → Integrate calendar → Secret address in iCal format*), Outlook (*Shared calendars → Publish*), iCloud (*Share Calendar → Public Calendar*), Fastmail, Nextcloud — or an `.ics` file on disk. `webcal://` links are fetched over HTTPS. The feed text is cached in `<data_dir>/calendar-cache.json` (mode 0600) so the agenda is there at startup and between refreshes.

```toml
[connectors.calendar]
enabled         = true
refresh_minutes = 30          # how often feeds are re-read in the background
day_start       = "09:00"     # working hours, for "when am I free"
day_end         = "18:00"

[[connectors.calendar.feeds]]
name = "Work"
url  = "{{vault:CALENDAR_WORK}}"   # the link is the secret: openmuse vault set CALENDAR_WORK

[[connectors.calendar.feeds]]
name = "Family"
url  = "~/family.ics"
```

The `calendar` tool reads (agenda, search, free time) and *drafts*: an event it proposes is written as `calendar/<date>-<title>.ics` in the workspace, and the app shows it as a card with an *Add to calendar* button. It never writes to your calendar itself. Today's and tomorrow's events are in the system prompt; the Feed shows them under *Today*. `openmuse calendar add NAME URL` does the same as the Connections screen.

### Contacts

Who is who. The agent looks people up before writing to them and never guesses an address; the approval card for an email names the recipient from the address book and warns when it does not know them. Sources are `.vcf` files — Google Contacts (*Export → vCard*), iCloud, Outlook (*People → Manage → Export*), Nextcloud, an iPhone (*Contacts → select all → Share*) and Android all export one — as a path, an upload from the phone (kept under `<data_dir>/contacts/`), or a link (kept in the vault). vCard 2.1, 3.0 and 4.0 are read, including Apple's `item1.` label groups and quoted-printable names from old phones. Link text is cached in `<data_dir>/contacts-cache.json` (mode 0600).

```toml
[connectors.contacts]
enabled = true                    # on by default: the agent's own book needs no source

[[connectors.contacts.sources]]
name = "Google"
url  = "~/Downloads/contacts.vcf"

[[connectors.contacts.sources]]
name = "Nextcloud"
url  = "{{vault:CONTACTS_NEXTCLOUD}}"   # a link, kept in the vault: openmuse vault set CONTACTS_NEXTCLOUD
```

Besides the sources there is always *My contacts*, `<data_dir>/contacts.vcf`: the people the agent was told about in chat ("the landlord is Bob Li, bob@example.com") through `contacts` action=add — the only book it writes to, and the only one it can remove people from. The `contacts` tool searches by name, nickname, company, email or phone (every word must match, prefixes count, a character inside a Chinese name counts); a look-up is private data and taints the session. `openmuse contacts search | list | add | sources | add-source | remove-source` from the CLI.

## `[triggers]`

Triggers are standing instructions that start work when something happens — a mail arrives, a calendar event is about to start, a program calls a webhook (see [the app](app.md#triggers)). They are set in chat or under *Upcoming*, not in the config file; this section only tunes how they are watched.

```toml
[triggers]
mail_poll_minutes = 5    # how often the inbox is looked at while a mail trigger is active
hook_min_seconds  = 10   # deliveries to one webhook closer together than this get HTTP 429
```

Mail triggers need the [email connector](#email); event triggers need a [calendar](#calendar). Triggers live in `<data_dir>/triggers.db`.

### Browser

```toml
[browser]
enabled    = true      # pip install "openmuse[browser]" && playwright install chromium
headless   = true
timeout_ms = 30000
```

### MCP servers

Anything that speaks the [Model Context Protocol](https://modelcontextprotocol.io) becomes a set of tools named `<server>__<tool>`, each passing through Sentinel with the risk level you assign.

```toml
[[mcp.servers]]
name    = "filesystem"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "./workspace"]
risk    = "moderate"             # safe | moderate | sensitive

[[mcp.servers]]
name               = "calendar"
url                = "http://localhost:8000/mcp"   # streamable HTTP; falls back to SSE
risk               = "sensitive"
egress             = true         # counts as network egress for taint tracking
reads_private_data = true         # taints the session when called
```

## `[server]`

```toml
[server]
host             = "127.0.0.1"   # 0.0.0.0 to reach it from your phone on the same network
port             = 8787
auth             = true          # access token required (in the QR code / link)
token            = ""            # empty → generated once, stored in <data_dir>/server_token
approval_timeout = 3600          # seconds an approval card waits before counting as "deny"
cors_origins     = []            # only for the Vite dev server, e.g. ["http://localhost:5173"]
```

## Where things live

| Path | Contents |
|---|---|
| `~/.openmuse/` (`data_dir`) | everything below |
| `memory.db`, `goals.db` | SQLite |
| `vault.enc`, `vault.key` | encrypted secrets and the key (or `OPENMUSE_VAULT_KEY`) |
| `audit.jsonl` | append-only audit log |
| `approvals.json` | permissions you granted for 24 hours or always (tool + target, scope, expiry) |
| `app-settings.json` | what was changed in the app's Connections screen, layered over `config.toml` (no secrets, only `{{vault:NAME}}` references) |
| `sessions/` | CLI conversation history |
| `skills/<name>/SKILL.md` | your skills (the Agent Skills format); a name that matches a built-in replaces it |
| `threads/`, `profile.json`, `ideas.json`, `server_token`, `logs/` | app state |
| `./workspace` (`agent.workspace`) | files the agent reads and writes |
