# Contributing to OpenMuse

Thanks for helping build an open personal agent. Issues, discussions and pull requests are all welcome.

## Development setup

```bash
git clone https://github.com/OpenMuseAgent/OpenMuse.git && cd OpenMuse
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"            # add ",browser" for the Playwright tool
openmuse config init                  # config/config.toml is git-ignored
```

## Before you push

```bash
ruff check openmuse tests
ruff format openmuse tests
python -m pytest -q                   # unit tests only, no network
OPENMUSE_LIVE=1 python -m pytest -q -m live   # optional: smoke test against your model
```

CI runs the same three commands on Python 3.11 and 3.12.

## Guidelines

* **Security first.** Anything that lets the agent act on the world must go through `Sentinel`. New tools declare an honest `risk` level, set `reads_private_data` / `egress_hosts` where relevant, and override `assess()` if a call can be more dangerous than the default.
* **Secrets never reach the model.** Use `{{vault:NAME}}` placeholders; never log or return raw credentials.
* **Tests with `MockLLM`.** Agent behaviour is tested without network access (`tests/test_agent.py` shows the pattern). Live tests are marked `@pytest.mark.live` and skipped by default.
* **No internal endpoints.** Do not commit gateway URLs, app ids or keys. `config/config.toml`, `.env` and `workspace/` are git-ignored on purpose.
* **Commit messages** follow [Conventional Commits](https://www.conventionalcommits.org): `feat(tools): …`, `fix(llm): …`, `docs: …`, `ci: …`.
* **Style**: Ruff (line length 100), type hints everywhere, `from __future__ import annotations`, small modules.

## Adding a tool

1. Subclass `BaseTool` in `openmuse/tools/`, define `name`, `description`, `parameters`, `risk`, and `async execute(**kwargs) -> ToolResult`.
2. Register it in `openmuse/app.py::_build_tools` (behind a config flag if it needs credentials).
3. Add a unit test in `tests/test_tools.py`.
4. Document it in the *Tools* table of both READMEs.

Prefer exposing new integrations as [MCP servers](https://modelcontextprotocol.io) when possible — they plug in via `[[mcp.servers]]` with zero code.

## Reporting security issues

Please open a private security advisory on GitHub instead of a public issue.
