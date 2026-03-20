# The public showcase

A page anyone can open: a phone in the browser with 微信, 支付宝, 铁路12306 and the other
[MobileGym](https://github.com/Purewhiter/mobilegym) apps on it, and nanoMuse installed. Open
nanoMuse, and a **private nanoMuse is started for you** on the showcase server — your own
container, your own token, phone operation on — for thirty minutes and within a model budget.
Ask it to check the earliest train to Shanghai and watch it open 12306 on the phone.

Nothing about the phone runs on the server. MobileGym is a React app: the whole simulated
phone lives in the visitor's tab (~400 MB of *their* memory). The server runs three things:

| | |
|---|---|
| **Caddy** | HTTPS, the static site (MobileGym + the nanoMuse app), `/api/demo/*` to the gateway, and one hostname per session |
| **gateway** (`gateway/`) | Starts a nanoMuse container per visitor, relays the phone's HTTP and WebSocket to it, proxies the container's model calls to the provider with the demo key, keeps the books |
| **sessions** | `ghcr.io/nano-muse/nanomuse` containers on an internal Docker network with no way out — the gateway is the only thing they can reach |

```
visitor's browser ──HTTPS──▶ Caddy ── demo.nanomuse.dev ──▶ /srv/site (MobileGym + nanoMuse app)
   │  MobileGym phone            │                      └▶ /api/demo/* ──▶ gateway
   │  nanoMuse app (iframe)      └── <id>.s.nanomuse.dev ─────────────────▶ gateway ──▶ nm-<id>:8787
   └──────────────────────────────────────────────────────────────────────────────┘        │
                                            models ◀── gateway ◀── /llm/<id>/{main,gui} ◀──┘
```

A session is one hostname (`<id>.s.nanomuse.dev`) because the nanoMuse web app and the
MobileGym module both take a server *origin*, and because the browser then keeps each session's
token in its own `localStorage`. The wildcard certificate that needs is why Caddy is built with
the Cloudflare DNS module.

## What the gateway enforces

- **One container per visitor**, `--read-only`, no capabilities, `no-new-privileges`, 512 MB,
  one CPU, 256 processes, tmpfs for `/data` and `/workspace`. Gone after `SESSION_TTL_S`
  (30 min) or `IDLE_TTL_S` (10 min) without traffic, and everything in it with it.
- **No network** from the containers except to the gateway (`docker network --internal`). The
  web fetch and shell tools cannot reach the internet from a demo session; the phone can.
- **The demo key never leaves the server.** Containers get a per-session key and
  `NANOMUSE_LLM_BASE_URL=http://gateway:8000/llm/<id>/main`; the gateway swaps the key and
  forwards to the provider. Streaming passes through; `usage` (asked for on streams) is what
  the budget counts.
- **Budgets:** per session `SESSION_LLM_REQUESTS` / `SESSION_LLM_TOKENS`, per day (Asia/Shanghai)
  `DAILY_LLM_REQUESTS` / `DAILY_LLM_TOKENS`. Over budget, the model call gets an OpenAI-shaped
  429 and the agent tells the visitor.
- **Per visitor (IP):** `PER_IP_ACTIVE` sessions at once, `PER_IP_DAILY` a day. `MAX_SESSIONS`
  overall.
- **Bring your own key:** the visitor can enter a provider URL, model and key on the setup page.
  The gateway keeps them in memory for the session and forwards with them (no budget of ours);
  the container never sees the key. Only `https://` to hosts in `BYOK_ALLOWED_HOSTS` (the usual
  providers), never to an address inside the server's network.

Two lanes: `main` (the model that talks to the visitor) and `gui` (the one that reads screens
and taps; many small calls with a screenshot each). The default is 阿里云百炼's `qwen3.8-27b`
for both — it reads screenshots, so one key does everything. Set `GUI_*` to split the lanes.

### Trial credentials for the phone app

The same proxy can hand a new phone its first model. With `TRIAL_ENABLED=1`, `POST /api/trial`
with `{"device": "<a random id the app keeps>"}` answers with a key (`nmt_…`) and two
addresses — `https://<SITE_HOST>/llm/trial/<id>/main` and `…/gui` — that go straight into the
app's `[llm]` and `[gui]` settings. Every call through them is metered against the trial's
lifetime budget, `TRIAL_TOKENS` (a million); spent, the proxy answers 429 `trial_exhausted` and
the app asks for the user's own key. One trial per device: asking again with the same id
rotates the key and keeps the count, so a reinstall recovers nothing extra. New trials are
capped per address (`TRIAL_PER_IP_DAILY`) and per day (`TRIAL_DAILY_NEW`, 200); all trials
together may spend `TRIAL_DAILY_TOKENS` a day; each is held to `TRIAL_RPM` requests a minute.
Trials live in SQLite on the `gateway-data` volume and survive restarts; `GET /api/trial/<id>`
with the key shows what is left, and `/api/demo/info` carries the totals.

## Deploying

You need: a Linux box with Docker (4 cores / 8 GB is plenty for `MAX_SESSIONS=20` — a session
idles at ~150 MB), a domain on Cloudflare, and a 百炼 key (or any OpenAI-compatible provider
that takes images).

```bash
# 1. DNS on Cloudflare:   demo.nanomuse.dev  A  <server>   DNS only (see the note on the proxy)
#                         *.s.nanomuse.dev   A  <server>   DNS only — sessions are WebSockets to Caddy
#    Cloudflare → My Profile → API Tokens: Zone → DNS → Edit and Zone → Zone → Read on the zone.

# 2. the code
git clone https://github.com/nano-muse/nanoMuse.git && cd nanoMuse/demo/showcase
cp .env.example .env && $EDITOR .env          # names, ACME_EMAIL, CLOUDFLARE_API_TOKEN, keys

# 3. what the sessions run
docker pull ghcr.io/nano-muse/nanomuse:latest  # or: docker build -t nanomuse:latest ../.. && set NANOMUSE_IMAGE

# 4. (optional, 1.9 GB) MobileGym's companion data: app media and home-screen widgets.
#    Without it the phone works but media apps render empty and two home widgets show an error.
mkdir -p data && curl -L https://github.com/Purewhiter/mobilegym/releases/download/data-v0.1.0/mobilegym-data-v0.1.0.tar.gz | tar -xz -C data
#    CC BY-NC 4.0 — non-commercial use only (see MobileGym's LICENSE-DATA).

# 5. up — the published images (.github/workflows/showcase.yml builds them from main) …
docker compose pull && docker compose up -d
#    … or build them here (clones MobileGym and compiles Caddy; a few minutes):
docker compose up -d --build
docker compose logs -f gateway
```

Open `https://demo.nanomuse.dev`, find nanoMuse in the launcher (search works), and it starts.
`curl https://demo.nanomuse.dev/api/demo/info` shows sessions in use and today's spend.

Updating: `git pull && docker pull ghcr.io/nano-muse/nanomuse:latest && docker compose pull && docker compose up -d`.
Sessions in flight end when the gateway restarts; visitors get *Your Muse on the showcase server
has ended* and a button for a new one.

Both certificates are obtained through Cloudflare's DNS API (`CLOUDFLARE_API_TOKEN`); the
records themselves stay "DNS only". Cloudflare's proxy can be switched on for `SITE_HOST`
when the site is under attack — Caddy is built with the
[cloudflare-ip](https://github.com/WeidiDeng/caddy-cloudflare-ip) module and trusts
`X-Forwarded-For` from Cloudflare's ranges only, so `PER_IP_*` keeps counting visitors rather
than edges (set the zone's SSL/TLS mode to *Full (strict)*: the origin has a real certificate).
It is off by default on purpose: from mainland China the free plan routes through overseas
edges, and the phone's 1.6 MB bundle that a Hong Kong server delivers in 2–3 s took 15–40 s
through the proxy in our measurements. The audience this is for reaches the origin faster.

### Other sites on the same Caddy

The Caddyfile ends with `import /etc/caddy/sites.d/*.caddy`, and `docker-compose.yml` mounts
`sites.d/` there and `www/` (or `WWW_ROOT`) at `/srv/www`, both read-only and both ignored by
git. One file per site, its files under `www/<name>/`, then `docker compose up -d caddy` — a box
that has no such sites is unchanged.

The project site is served this way at [nanomuse.cn](https://nanomuse.cn): `mirror/` holds the
site block and `sync.sh`, which a systemd timer runs every minute to pull
[nano-muse.github.io](https://github.com/nano-muse/nano-muse.github.io) into `www/nanomuse.cn/`
— a push to that repository is on the mirror within the minute, with no key or webhook anywhere.
`sudo mirror/install.sh` sets up all of it and is safe to run again after `git pull`. What is not
in the repository: two A records at the registrar (`nanomuse.cn`, `www.nanomuse.cn` → this box).
A server outside mainland China needs no ICP filing for a `.cn` name; one inside does.

### Running it on your machine

The gateway runs anywhere Docker does; Caddy is only for TLS and names. Browsers resolve
`*.localhost` to the loopback, so:

```bash
docker network create --internal nanomuse-sessions
docker build -t nanomuse:local ../..                        # the sessions' image
site/build.sh                                              # clones MobileGym, builds with VITE_NANOMUSE_DEMO=/api/demo
cd gateway && pip install -e '.[dev]' && cd ..
PUBLIC_SCHEME=http SITE_HOST=localhost SESSION_DOMAIN=s.localhost PUBLIC_PORT=:8000 \
NANOMUSE_IMAGE=nanomuse:local SITE_DIR=$PWD/site/dist \
MAIN_API_KEY=sk-... python -m showcase_gateway              # http://localhost:8000
```

`cd gateway && pytest` runs the gateway's tests (no Docker needed; the containers are faked).

## Costs, roughly

A session that asks two or three things, one of them on the phone, is 5–15 model calls and
20–60k tokens: about ¥0.05–0.2 at DeepSeek/百炼 prices. Two hundred sessions a day is ¥20–40.
The daily caps in `.env.example` (3,000 calls / 6M tokens) bound the worst day at a few tens of
yuan; lower them if you like. Put a spending alert on the provider accounts too — the gateway's
counters live in memory and start from zero when it restarts.

## Known limits

- One gateway, one host. The session counters are in memory (the trials are in SQLite); that is
  fine for a showcase and would need a shared store to scale out.
- The gateway holds the Docker socket, i.e. root on the host. It is the trusted part; keep it
  off the public network (compose does: only Caddy is published).
- No egress from sessions means the search, fetch and browser tools fail inside a demo. That is
  the point of the demo — the phone — but say so if visitors ask.
- The MobileGym data set is CC BY-NC 4.0; the showcase is non-commercial.
