"""Runtime configuration, resolved from environment with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dots.core.duration import parse_duration


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime settings.

    Resolved once at startup via :meth:`from_env`. Everything a dot needs to
    run lives here, so tests can construct an explicit ``Settings`` instead of
    touching the environment.
    """

    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None
    state_dir: Path = Path(".dots")
    log_level: str = "INFO"
    default_interval_seconds: float = 900.0

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        env = environ if environ is not None else dict(os.environ)
        interval = env.get("DOTS_DEFAULT_INTERVAL", "15m")
        return cls(
            llm_provider=env.get("DOTS_LLM_PROVIDER", "openai"),
            llm_model=env.get("DOTS_LLM_MODEL", "gpt-4o-mini"),
            llm_api_key=env.get("DOTS_LLM_API_KEY"),
            state_dir=Path(env.get("DOTS_STATE_DIR", ".dots")),
            log_level=env.get("DOTS_LOG_LEVEL", "INFO"),
            default_interval_seconds=parse_duration(interval),
        )

    def ensure_state_dir(self) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        return self.state_dir
