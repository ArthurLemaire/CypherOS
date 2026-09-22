# Sentinel

Meta describes Muse's safety model as a separate *Sentinel* agent that sits between the model and its tools, approves sensitive actions, keeps credentials out of the model's reach and records what happened. OpenMuse implements the same split. The agent never executes a tool itself; it hands the call to `Sentinel.guard()`:

```
agent ──► Sentinel.guard() ──► policy ──► approval (if needed) ──► vault.resolve ──► execute
agent ◄── redact(result)   ◄── taint bookkeeping ◄─────────────────────────────────────┘
```

Code: `openmuse/sentinel/gate.py` (the gate), `policy.py` (decisions), `audit.py` (log). The vault is `openmuse/vault/`.

## Risk levels

Every tool declares a static `risk`:

| Level | Meaning | Examples |
|---|---|---|
| `safe` | reversible, local | `files` (inside the workspace), `web_search`, `remember`, `goals` |
| `moderate` | reaches outside or changes state | `web_fetch`, `python_execute`, `read_emails`, `browser`, `forget` |
| `sensitive` | hard to undo or externally visible | `shell`, `send_email` |

A tool can raise the level for a particular call in `assess()`: `shell` attaches a warning on patterns such as `rm -rf`, `sudo`, `curl | sh`; `python_execute` is `moderate` for plain computation and files in the workspace but `sensitive` — with the reason on the card — when the code reaches the network, starts other programs, reads environment variables, deletes files or touches paths outside the workspace; `web_fetch` refuses private and loopback addresses outright, on every redirect hop. Tools also declare `reads_private_data` (taints the session) and `egress` with an optional `egress_target` (the host a call sends data to; unknown for `shell` and `python_execute`), used by taint tracking.

Subprocesses started by `shell` and `python_execute` get a scrubbed environment: variables whose names look like credentials (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSW*`, `*CREDENTIAL*`, `*AUTH*`, `*COOKIE*`, `*SESSION*`), everything under `OPENMUSE_`, `AWS_`, `AZURE_`, `GOOGLE_`, `GH_`, `GITHUB_`, `NPM_`, plus `SSH_AUTH_SOCK`, are removed before the child starts, so code the model wrote cannot read the model's own API key or the vault key out of `os.environ`. A command that needs a secret gets it as a `{{vault:NAME}}` argument instead.

## Decision order

For each call, the first matching step decides:

1. **`deny_tools`** → deny.
2. **`[[sentinel.rules]]`**: `tool` (glob, `*` for any) plus `match`, a map of argument name → glob pattern matched against `str(value)`. The first rule that matches wins and yields its `action`.
3. **`always_allow_tools` / `always_ask_tools`**.
4. **Taint**: the session is tainted **and** the call has egress to a host not in `egress_allowlist` (or to an unknown destination) → ask. The approval card shows the destination when it is known.
5. **Risk × mode**:

| mode | `safe` | `moderate` | `sensitive` |
|---|---|---|---|
| `ask` (default) | allow | allow | ask |
| `strict` | allow | ask | ask |
| `auto` | allow | allow | allow |

6. **Warnings**: a call that carries a warning (`rm -rf`, `sudo`, `curl | sh`, code that reads the environment or deletes files) is never waved through by the mode or by `always_allow_tools`; it asks. Only an explicit `allow` rule can override this.

`auto` still honours `deny_tools`, deny rules and step 6. It is what `openmuse daemon`, `--auto` and the app's "Hands-off" setting use — and background goal passes, which is why a dangerous command in an unattended run turns into a card in the Feed instead of just running.

## Approvals

When the decision is *ask*, the UI (console, or an approval card in the app) shows the tool, the summarised call, what you asked for that led to it (the *purpose*), the exact arguments, the risk level and the reasons. You can deny, or allow with a scope:

| Answer | Effect |
|---|---|
| Deny | the tool is not run; the model gets a "Sentinel blocked" result and is told not to retry the same call |
| Once | this call only; nothing is remembered |
| For this task | until the agent finishes what it is doing now (the current run); for `shell` this covers the tool, not just the programs in the current command |
| Until restart | until the process exits |
| For 24 hours | persisted in `<data_dir>/approvals.json` with an expiry |
| Always | persisted until you revoke it |

An approval is a capability, not a mood. It is bound to a **grant key**: the tool plus what the call touches — `web_fetch:example.com`, `send_email:alice@example.com`, `shell:git`, `browser:booking.com`. Allowing `git` commands for the session says nothing about `curl`; a pipeline such as `git status | head` needs every program covered (approving it grants each program separately), and an email to two people needs both recipients. The one deliberate exception is *for this task* on `shell`: a job that needs `git` now will need `ls` and `wc` a moment later, so that answer covers the shell for the rest of the run — while destinations (recipients, hosts) stay bound even within a task. Tools without a meaningful target (`python_execute`, an MCP tool) are granted as a whole, and the Sentinel only offers *once* and *for this task* for arbitrary code with network access. A call that carries a warning (`rm -rf`, `sudo`, `curl | sh`) is approved one at a time — standing permissions never cover it.

Everything you granted is listed under the avatar in the app (Permissions), each with its own revoke button; `DELETE /api/approvals/grants/{key}` and `DELETE /api/approvals` do the same from the API, and `openmuse chat`'s `/forget-approvals` clears them in the console.

In the app an unanswered card times out after `server.approval_timeout` seconds (default one hour) and counts as deny. The agent keeps accepting new messages while a card is waiting. Cards that were still pending when the server stopped are marked expired on restart; the run behind them is gone.

## Taint tracking

Reading private data (`read_emails`, `recall`, files outside the workspace, MCP servers marked `reads_private_data`) marks the session as tainted. From then on, any call that sends data to a host outside `egress_allowlist` needs approval, whatever its risk level. This is the practical defence against prompt injection: a web page cannot instruct the agent to post your inbox somewhere without you seeing the destination first.

`openmuse chat` shows the state with `/tainted`; `/reset` clears it with the conversation. The default allowlist covers search, Wikipedia, GitHub and PyPI; edit `egress_allowlist` to fit your own connectors.

## Credential vault

```bash
openmuse vault set EMAIL_PASSWORD        # prompted; stored Fernet-encrypted in <data_dir>/vault.enc
openmuse vault list                      # names only
openmuse vault delete EMAIL_PASSWORD
```

Config values and tool arguments can reference secrets as `{{vault:NAME}}`. The placeholder is what the model sees in prompts, tool schemas and its own arguments. Sentinel substitutes the real value immediately before execution, and if a secret shows up in a tool's output it is replaced with `{{vault:NAME}}` before the model reads it. The key is `<data_dir>/vault.key` (created on first use, mode 600) or `OPENMUSE_VAULT_KEY`.

## Audit log

Every user message, model turn, decision, approval, tool call and result is appended to `<data_dir>/audit.jsonl` with a UTC timestamp:

```bash
openmuse audit -n 50          # table
openmuse audit --json         # raw lines
```

The app's activity sheet (tap the avatar) reads the same file.

## What this does and does not protect against

Muse runs each user's agent in its own cloud VM with the Sentinel outside it. OpenMuse runs on your machine, as your user, and its Sentinel is a module in the same process. That changes what the safeguards can promise. Honest summary:

**Covered**

- *The model acting beyond what you asked.* Every tool call goes through the policy; sensitive and dangerous calls stop for a decision; permissions are scoped to a tool and a target and can be revoked.
- *Prompt injection that tries to exfiltrate.* Once private data has been read, egress to any host not on the allowlist asks first, with the destination on the card. `web_fetch` cannot be pointed at loopback, link-local, private or cloud-metadata addresses, including through redirects.
- *The model seeing your secrets.* Keys and passwords live in the encrypted vault and enter tool calls as placeholders; they are substituted after approval and redacted from results. Subprocesses do not inherit credential-looking environment variables. The model never sees the access token of the app.
- *Not knowing what happened.* Everything is in `audit.jsonl` and the Activity view.

**Not covered — know this before you run it**

- *OS-level isolation.* `shell` and `python_execute` run as you. A command you approve can do anything you can. The pattern checks are a tripwire, not a sandbox; an adversarial script can evade them. Run OpenMuse in a container or a dedicated user account if the workspace touches anything you would miss (the Docker image is one such setup).
- *The vault key on disk.* By default the Fernet key sits next to the vault (`vault.key`, mode 600). Anyone who can read your data directory can decrypt the vault. Set `OPENMUSE_VAULT_KEY` from a secret manager if that matters to you.
- *DNS rebinding.* `web_fetch` checks the resolved address before the request; a hostile DNS server answering differently a moment later can still point the request at an internal address. The taint rule and the allowlist limit what such a fetch could be combined with.
- *Bad grants.* "Always allow `shell:curl`" is exactly as strong as it sounds. Warnings still ask, but the destination of a `curl` is not inspected.
- *The network the app is on.* The API is protected by a bearer token over plain HTTP by default. Do not expose the port to the internet; use Tailscale or a TLS reverse proxy. Secrets typed into the Connections screen travel over that connection.
- *Approval fatigue.* If cards are approved without reading them, none of this helps.

Report anything that contradicts the "covered" list — see [SECURITY.md](../SECURITY.md).

## Writing a safe tool

- Set an honest `risk`; when in doubt, `moderate`.
- Set `reads_private_data = True` if the output can contain the user's private data, and `egress = True` (with `egress_target` from `assess()` when the host is known) if the call sends data anywhere.
- Override `assess()` to raise the level for dangerous argument patterns and to produce a short human-readable `summary`; it is what the approval card shows.
- Never read secrets yourself. Accept `{{vault:NAME}}` placeholders and let Sentinel resolve them.
- Return errors as `ToolResult(error=...)` rather than raising; `safe_execute` catches the rest.
