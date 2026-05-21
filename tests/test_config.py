from __future__ import annotations

from pathlib import Path

import pytest

from openmuse.config import load_settings


def test_env_expansion_and_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[llm]
model = "deepseek-flash"
api_key = "${TEST_KEY}"
base_url = "${TEST_URL:-https://api.deepseek.com/}"
extra_headers = { "X-User" = "${TEST_USER:-anon}" }

[sentinel]
mode = "strict"

[[sentinel.rules]]
tool = "shell"
match = { command = "*rm*" }
action = "deny"
""",
        "utf-8",
    )
    monkeypatch.setenv("TEST_KEY", "sk-test")
    monkeypatch.delenv("TEST_URL", raising=False)
    monkeypatch.delenv("OPENMUSE_LLM_MODEL", raising=False)
    s = load_settings(cfg)
    assert s.llm.api_key == "sk-test"
    assert s.llm.base_url == "https://api.deepseek.com"  # trailing slash stripped
    assert s.llm.extra_headers == {"X-User": "anon"}
    assert s.sentinel.mode == "strict"
    assert s.sentinel.rules[0].action == "deny"

    monkeypatch.setenv("OPENMUSE_LLM_MODEL", "other-model")
    monkeypatch.setenv("OPENMUSE_SENTINEL_MODE", "auto")
    s = load_settings(cfg)
    assert s.llm.model == "other-model"
    assert s.sentinel.mode == "auto"

    # container-style overrides win over values set in the file
    monkeypatch.setenv("OPENMUSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENMUSE_WORKSPACE", str(tmp_path / "ws"))
    s = load_settings(cfg)
    assert s.data_dir == tmp_path / "data"
    assert s.agent.workspace == tmp_path / "ws"


def test_missing_explicit_config_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "nope.toml")


def test_defaults_without_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENMUSE_CONFIG", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    monkeypatch.setenv("HOME", str(tmp_path))
    s = load_settings()
    assert s.llm.api_key == "sk-from-env"
    assert s.source == "defaults+env"


def test_provider_key_fallback_follows_the_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A missing api_key is filled from the provider's own variable, never another's."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.delenv("OPENMUSE_LLM_API_KEY", raising=False)
    cfg = tmp_path / "config.toml"

    def key_for(base_url: str | None) -> str | None:
        line = f'base_url = "{base_url}"\n' if base_url else ""
        cfg.write_text(f'data_dir = "{tmp_path / "data"}"\n[llm]\n{line}')
        return load_settings(cfg).llm.api_key

    assert key_for(None) == "sk-deepseek"  # the default endpoint is DeepSeek's
    assert key_for("https://api.deepseek.com") == "sk-deepseek"
    assert key_for("https://api.openai.com/v1") == "sk-openai"
    assert key_for("https://openrouter.ai/api/v1") == "sk-openai"  # the shared convention
    monkeypatch.delenv("OPENAI_API_KEY")
    assert not key_for("https://api.openai.com/v1")  # DeepSeek's key does not stand in
    assert key_for("https://api.deepseek.com") == "sk-deepseek"
