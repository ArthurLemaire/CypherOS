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
openmuse goals list [--status active|paused|done] [--category health|finance|career|learning|…]
openmuse goals show g_1a2b3c
openmuse goals add "Learn Rust" -s "Read the book, ch. 1–4" -s "Build a CLI" -s "Publish a crate" \
    --category learning --due 2026-12-31 --check-in "weekly sun 19:00"
openmuse goals run g_1a2b3c            # one background pass now
openmuse goals status g_1a2b3c paused
openmuse goals delete g_1a2b3c
```

## Reminders and routines

```bash
openmuse reminders list [--all]                                  # --all includes the recently fired
openmuse reminders add "Call mum" --at "2026-10-01 18:00"        # one message at that time
openmuse reminders add "Summarise unread email" --repeat "weekdays 07:30" --task   # the agent does it, then reports
openmuse reminders cancel r_1a2b3c
```

A reminder says one thing at the time you named; a routine (`--task`) is work the agent does at that time with its tools. Both fire from the running `openmuse serve` — those set from the terminal land in the main chat, those set in a side chat stay there. Cadence grammar as for goal check-ins: `daily HH:MM`, `weekdays HH:MM`, `weekly <mon…sun> HH:MM`, `monthly <day> HH:MM`.

## Triggers

```bash
openmuse triggers list [--all]                                                   # --all includes cancelled ones
openmuse triggers add mail  "Summarise it and draft a reply" --match "landlord"   # a new mail whose sender/subject has every word
openmuse triggers add event "Put together a one-page brief"  --match "review" --lead 30   # 30 min before a matching event
openmuse triggers add hook  "Check that the site is up"      --match "deploy"    # prints the URL to POST to
openmuse triggers cancel t_1a2b3c
```

A trigger fires when something happens rather than at a time: `mail` needs the email connector (the running server looks at the inbox every `triggers.mail_poll_minutes`, by IMAP UID, so nothing is replayed and nothing fires twice), `event` needs a calendar feed, `hook` is a URL with a key that any program can `POST` to — the body becomes the agent's context. Each firing is a background run in the chat the trigger was set from, shown in the Feed as *New mail: …*, *Coming up: …* or *Webhook: …*. The mail or the request is handed to the model as data, with the instruction that only your standing text says what to do.

## Calendar

```bash
openmuse calendar add Work "https://calendar.google.com/calendar/ical/…/basic.ics"   # link goes to the vault as CALENDAR_WORK
openmuse calendar add Family ~/family.ics                                            # or an .ics file on disk
openmuse calendar agenda --days 7                                                    # what is on, grouped by day
openmuse calendar free --day tomorrow --minutes 45                                   # gaps in the working hours
openmuse calendar feeds                                                              # each feed: events, last read, error
openmuse calendar remove Family
```

Feeds are re-read every `refresh_minutes` by the running server; `agenda --refresh` fetches now. The agent has the same view through its `calendar` tool, plus `draft`, which writes an `.ics` the app shows as an *Add to calendar* card — it never writes to your calendar directly.

## Contacts

```bash
openmuse contacts search "ali"                          # by name, nickname, company, email or phone
openmuse contacts list -n 20                            # the first people alphabetically
openmuse contacts add "Bob Li" -e bob@example.com --note landlord   # into the agent's own book
openmuse contacts sources                               # each address book: people, last read, error
openmuse contacts add-source Google ~/Downloads/contacts.vcf         # a .vcf file, or a link (→ vault CONTACTS_GOOGLE)
openmuse contacts remove-source Google
```

The agent has the same view through its `contacts` tool; `doctor` reports how many people it knows and from where.

## Skills

```bash
openmuse skills list                                    # built-in and yours, on or off
openmuse skills show trip-plan                          # the SKILL.md, as the model reads it
openmuse skills new standup-notes                       # a SKILL.md to fill in, printed with its path
openmuse skills add ./my-skill/                         # a folder or a SKILL.md file …
openmuse skills add https://github.com/anthropics/skills/tree/main/skills/pdf   # … or a raw link / GitHub folder page
openmuse skills disable inbox-triage                    # out of the model's list; the folder stays
openmuse skills enable inbox-triage
openmuse skills remove standup-notes                    # one of yours (built-in ones are disabled, not removed)
```

Skills are folders with a `SKILL.md` in the [Agent Skills](https://agentskills.io) format; yours live in `<data_dir>/skills/` and one with the same name as a built-in replaces it. In chat, `/name` at the start of a message runs one; `doctor` lists what is loaded and any folder it could not read.

## Memory

```bash
openmuse memory list
openmuse memory add "Prefers short answers" --category preference
openmuse memory recall "写邮件给房东"    # what the agent would recall for this, with closeness
openmuse memory forget m_9f8e7d        # id or a phrase to search for
openmuse memory clear --yes
openmuse memory tidy --dry-run         # what a tidy-up would merge and drop
openmuse memory tidy                   # do it; every change is logged
openmuse memory changes                # the log, newest first
openmuse memory restore c_1a2b3c4d     # undo one change
```

`memory recall` shows the ranking the agent would get for a message: keyword hits and, when an embedding endpoint is set up ([configuration → memory](configuration.md#memory)), hits by meaning fused in, each with its cosine closeness — the way to see whether "写邮件给房东" finds "the landlord is Bob Li" before relying on it. `doctor` says whether recall by meaning is on, with which model, and how many memories are indexed.

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
openmuse doctor [--no-model]           # config, data dir, model, connectors — one screen
openmuse version                       # also: openmuse --version / -V
```

`openmuse doctor` is the first thing to run when something is off, and what to paste into a bug report: which config file is in use, where the data lives, which model and endpoint are configured and whether a key is set, whether recall by meaning is on and how many memories are indexed, which web search provider answers and whether it has its key or URL, whether commands run in the sandbox (and why not, if not), the tools the agent has, connector state (mailbox, calendar feeds, address books), and a one-line call to the model with its latency (`--no-model` skips that). It exits non-zero when something needs fixing and says what.
