# Contributing

Use OpenMuse for a real task, report what broke, then pick something focused. Issues and pull requests are welcome; for anything larger than a fix, open an issue first so we can agree on the shape.

## Setup

```bash
git clone https://github.com/OpenMuseAgent/OpenMuse.git && cd OpenMuse
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"            # add ",browser" for the Playwright tool
openmuse config init                  # config/config.toml is git-ignored
```

The phone app lives in `web/` (React, TypeScript, Tailwind, Vite). Node 20+ is only needed if you change it:

```bash
cd web && npm install
npm run dev            # http://localhost:5173, proxied to `openmuse serve` on 8787
npm run check          # eslint, tsc, vitest
npm run build          # writes openmuse/server/static/ — commit the result with your change
```

## Before you push

```bash
ruff check openmuse tests && ruff format openmuse tests
mypy                                           # types; config in pyproject.toml
python -m pytest -q                            # MockLLM only, no network
OPENMUSE_LIVE=1 python -m pytest -q -m live    # optional: against your configured model
cd web && npm run check && npm run build       # if you touched web/
```

CI runs the Python checks on Linux and macOS with Python 3.11–3.13 (Windows is advisory), lints, tests and builds the web app and checks that the committed build is current, and builds the Docker image.

## Guidelines

- **Everything that acts goes through Sentinel.** New tools declare an honest `risk`, set `reads_private_data` / `egress` where they apply, and override `assess()` when a call can be more dangerous than the default or needs a readable summary. See [docs/sentinel.md](docs/sentinel.md#writing-a-safe-tool).
- **Secrets never reach the model.** Use `{{vault:NAME}}` placeholders. Do not log or return raw credentials.
- **Test with `MockLLM`.** Agent and server behaviour is tested without network access (`tests/test_agent.py`, `tests/test_server.py`). Live tests are marked `@pytest.mark.live` and skipped by default.
- **No internal endpoints or keys in the repo.** `config/config.toml`, `.env` and `workspace/` are git-ignored on purpose.
- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org): `feat(tools): …`, `fix(server): …`, `docs: …`, `ci: …`.
- **Style**: Ruff (line length 100), type hints, `from __future__ import annotations`, small modules. In `web/`, keep components small and state in `store.tsx`.
- **Docs are part of the change.** If you alter a setting, a command, a tool's behaviour or the API, update the matching page in `docs/`.

## Adding a tool

1. Subclass `BaseTool` in `openmuse/tools/`: `name`, `description`, `parameters` (JSON schema), `risk`, `async execute(**kwargs) -> ToolResult`.
2. Register it in `openmuse/app.py::_build_tools` (behind a config flag if it needs credentials or an optional dependency).
3. Add a label in `openmuse/server/webui.py::_TOOL_LABELS` so the app shows a readable status.
4. Add a unit test in `tests/test_tools.py`.
5. Mention it in `docs/configuration.md` if it has settings.

Prefer an [MCP server](https://modelcontextprotocol.io) for integrations with an existing protocol; it plugs in through `[[mcp.servers]]` with no code.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml` and `openmuse/__init__.py`; move the `Unreleased` entries in `CHANGELOG.md` under the new version with today's date; commit.
2. `git tag vX.Y.Z && git push origin main vX.Y.Z`.
3. The [Release](.github/workflows/release.yml) workflow checks the tag against the version, builds and smoke-tests the wheel, then publishes to PyPI through Trusted Publishing (`pypi` environment, no stored token). The [Docker image](.github/workflows/docker.yml) workflow pushes `ghcr.io/openmuseagent/openmuse:X.Y.Z` and `:latest` for amd64 and arm64.
4. Paste the changelog section into the GitHub release.

## Security issues

Open a private security advisory on GitHub rather than a public issue.
