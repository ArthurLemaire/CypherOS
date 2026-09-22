# CLI

Every command accepts `--config PATH` (`-c`). `--auto` switches Sentinel to `auto` mode for that run; explicit deny rules still apply.

## Talking to the agent

```bash
openmuse serve [--host 0.0.0.0] [--port 8787] [--no-qr] [--no-auth]
```

The always-on agent with the phone app. See [app.md](app.md). `--no-auth` is for local development only.

```bash
openmuse chat [--resume] [--show-thinking] [--auto]
```

Interactive session in the terminal with approvals inline. Slash commands:

| Command | Effect |
|---|---|
| `/help` | list commands |
| `/reset` | clear the conversation and the taint flag |
| `/memory`, `/goals` | list memories / goals |
| `/audit [n]` | recent audit entries |
| `/tools` | tools the agent can use right now |
| `/tainted` | whether the session has read private data |
| `/permissions` | standing permissions you granted (key and lifetime) |
| `/revoke <key>` | take one back, e.g. `/revoke shell:git` |

`--resume` continues the most recent session (`<data_dir>/sessions/`).

```bash
openmuse run "Summarise the top three Hacker News stories into hn.md" [--auto]
```

One task, then exit. Non-zero exit if the agent fails.

```bash
openmuse daemon [--interval 3600] [--once]
```

Advance every active goal, sleep, repeat. Runs in Sentinel `auto` mode, so pair it with deny rules and a tight `egress_allowlist`. The app's *Background work* switch does the same thing inside `openmuse serve`, one goal per interval, with updates posted to the chat.

## Goals

```bash
openmuse goals list [--status active|paused|done]
openmuse goals show g_1a2b3c
openmuse goals add "Learn Rust" -s "Read the book, ch. 1–4" -s "Build a CLI" -s "Publish a crate"
openmuse goals run g_1a2b3c            # one background pass now
openmuse goals status g_1a2b3c paused
openmuse goals delete g_1a2b3c
```

## Memory

```bash
openmuse memory list
openmuse memory add "Prefers short answers" --category preference
openmuse memory forget m_9f8e7d        # id or a phrase to search for
openmuse memory clear --yes
```

## Vault

```bash
openmuse vault set EMAIL_PASSWORD      # prompted; or --value for scripts
openmuse vault list                    # names only, never values
openmuse vault delete EMAIL_PASSWORD
```

Reference secrets as `{{vault:EMAIL_PASSWORD}}` in the config or in tool arguments. See [sentinel.md](sentinel.md#credential-vault).

## Audit and config

```bash
openmuse audit [-n 20] [--json]        # recent decisions, approvals, tool calls
openmuse config init [--path config/config.toml] [--force]
openmuse config show                   # effective settings, secrets masked
openmuse config path                   # which file is in use
openmuse version
```
