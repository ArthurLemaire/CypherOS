from __future__ import annotations

from pathlib import Path

import pytest

from openmuse.config import Settings


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.data_dir = tmp_path / "data"
    s.agent.workspace = tmp_path / "workspace"
    s.llm.api_key = "test"
    s.llm.stream = False
    s.ensure_dirs()
    return s
