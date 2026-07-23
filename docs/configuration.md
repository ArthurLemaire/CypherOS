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
tool_mode     = "native"           # "prompt": describe tools in the prompt, parse <tool_call> blocks
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
| Ollama | `qwen3:32b` | `http://localhost:11434/v1` | `api_key = "ollama"` |
| vLLM / LM Studio | your served name | `http://localhost:8000/v1` | set `tool_mode = "prompt"` if the server ignores `tools` |
| Company gateway | as required | as required | use `extra_headers` / `extra_body`; pick the provider by the API shape the gateway speaks |

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

## `[memory]`

```toml
[memory]
enabled    = true
max_inject = 20        # memories injected into the system prompt per turn (keyword-ranked)
```

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
| `threads/`, `profile.json`, `ideas.json`, `server_token`, `logs/` | app state |
| `./workspace` (`agent.workspace`) | files the agent reads and writes |
