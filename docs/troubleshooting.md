# Troubleshooting

**The phone cannot open the URL.** Start with `--host 0.0.0.0` (the default binds to localhost only), make sure both devices are on the same network, and allow the port through the machine's firewall. The URL shown uses the LAN address the server could detect; if it is wrong, use the machine's address from `ip addr` / `ipconfig` with the same `?token=`.

**"web app not built" on start.** You are running from a checkout without the built front-end. `cd web && npm install && npm run build`, or install the package instead.

**Replies come back in the wrong language.** With `agent.language = "auto"` the system prompt names the language of your latest message (detected by script). If a model still drifts, set a fixed language in *You → Reply language* or `agent.language = "English"`.

**The beginning of a streamed reply is missing.** Some proxies that inline `<think>…</think>` into the content drop the first tokens after `</think>` on the server side. Non-streaming responses are complete; set `stream = false` under `[llm]`.

**The model never calls tools.** The endpoint probably ignores the `tools` field. Set `tool_mode = "prompt"`; tools are then described in the system prompt and parsed from `<tool_call>` blocks.

**429 / rate limits.** Requests retry with exponential back-off (`max_retries`, default 5). Lower `agent.max_steps`, or add `web_fetch` to `always_ask_tools` to slow the loop down.

**An approval card never appears in the terminal.** `openmuse daemon` and `--auto` run in Sentinel `auto` mode by design. Use `openmuse chat` or the app for interactive approvals.

**"Sentinel blocked" for something you wanted.** Check `openmuse audit -n 20` for the reason: a deny rule, `deny_tools`, or taint (private data read earlier in the session plus a new network destination). Add the host to `egress_allowlist` or approve once.

**Email tool returns nothing useful.** With `scrub_secrets = true` one-time codes and reset links are removed before the model reads a mail; that is intentional. Check IMAP settings with `openmuse config show` and the vault entries with `openmuse vault list`.

**Playwright fails to install Chromium.** Older distributions are not supported by recent Playwright builds. Use the Docker image or leave `browser.enabled = false`; `web_fetch` covers most reading tasks.

**Reset everything.** Stop the server and delete `~/.openmuse` (or your `data_dir`). The vault key lives there too, so export secrets first if you need them.
