# Deployment

Meta runs each Muse in a per-user secure VM. Locally, a container is the nearest equivalent: the agent sees only its data directory and its workspace.

## Docker

```bash
cp .env.example .env && $EDITOR .env      # API key
openmuse config init                      # or copy config/config.example.toml to config/config.toml
docker compose up -d app                  # the phone app on http://<host>:8787
docker compose logs app                   # shows the URL with the access token
```

Other entry points:

```bash
docker compose run --rm muse                      # terminal chat
docker compose run --rm muse run "plan my week"   # one task
docker compose up -d daemon                       # advance goals on a timer, no UI
```

The image runs as a non-root user with all capabilities dropped. Two volumes hold state: `openmuse-data` (memory, goals, vault, audit log, threads) and `./workspace` (the agent's files). `config/config.toml` is mounted read-only. Set `OPENMUSE_SERVER_TOKEN` in `.env` so the token is stable across restarts, and open the printed URL from your phone using the host's address.

Without cloning — the published image (linux/amd64 and linux/arm64, so a Raspberry Pi or an Apple-silicon Mac works):

```bash
docker run -d --name muse -p 8787:8787 --env-file .env \
  -v openmuse-data:/data -v "$PWD/workspace:/workspace" \
  ghcr.io/openmuseagent/openmuse:latest
docker logs muse                          # the URL with the access token
```

`:latest` and `:X.Y.Z` follow releases; `:edge` follows `main`. Without a mounted `config.toml` the image starts from `config.example.toml`, so the model is set from `.env` (`OPENMUSE_LLM_*`) or in the app's Connections screen.

Building by hand:

```bash
docker build -t openmuse .
docker run -d --name muse -p 8787:8787 --env-file .env \
  -v openmuse-data:/data -v "$PWD/workspace:/workspace" \
  -v "$PWD/config/config.toml:/app/config/config.toml:ro" openmuse
```

## Keeping it running without Docker

A user-level systemd unit is enough:

```ini
# ~/.config/systemd/user/openmuse.service
[Unit]
Description=OpenMuse
After=network-online.target

[Service]
WorkingDirectory=%h/OpenMuse
ExecStart=%h/OpenMuse/.venv/bin/openmuse serve --host 0.0.0.0 --no-qr
Restart=on-failure
EnvironmentFile=%h/OpenMuse/.env

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now openmuse
loginctl enable-linger $USER          # keep it running after logout
journalctl --user -u openmuse -f
```

## Reaching it from outside your network

Do not expose port 8787 to the internet directly. Options that keep the token scheme intact:

- **Tailscale / WireGuard**: bind to `0.0.0.0`, open the tailnet address on your phone.
- **Reverse proxy with TLS** (Caddy, nginx): proxy `/` and `/ws` (WebSocket upgrade) to `127.0.0.1:8787`. The token still applies.

## Updating

```bash
uv tool upgrade openmuse                               # PyPI install (or: pip install -U openmuse)
git pull --ff-only && uv pip install -e ".[dev]"      # source install
docker compose build && docker compose up -d app       # Docker
```

Data formats (SQLite, JSONL, JSON) are kept backward compatible within a minor version.
