from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from openmuse.vault import CredentialVault
from openmuse.vault.vault import VaultError


def test_vault_roundtrip(tmp_path: Path):
    vault = CredentialVault(tmp_path / "vault.enc", tmp_path / "vault.key")
    vault.set("EMAIL_PASSWORD", "hunter2-secret")
    assert vault.get("EMAIL_PASSWORD") == "hunter2-secret"
    assert vault.names() == ["EMAIL_PASSWORD"]
    # file on disk is encrypted
    assert b"hunter2" not in (tmp_path / "vault.enc").read_bytes()
    if os.name != "nt":
        mode = stat.S_IMODE((tmp_path / "vault.key").stat().st_mode)
        assert mode == 0o600
    # fresh instance with same key can read it
    again = CredentialVault(tmp_path / "vault.enc", tmp_path / "vault.key")
    assert again.get("EMAIL_PASSWORD") == "hunter2-secret"
    assert again.delete("EMAIL_PASSWORD")
    assert again.get("EMAIL_PASSWORD") is None


def test_resolve_and_redact(tmp_path: Path):
    vault = CredentialVault(tmp_path / "v.enc", tmp_path / "v.key")
    vault.set("TOKEN", "tok-1234567890")
    resolved = vault.resolve(
        {"headers": {"Authorization": "Bearer {{vault:TOKEN}}"}, "list": ["{{ vault:TOKEN }}"]}
    )
    assert resolved["headers"]["Authorization"] == "Bearer tok-1234567890"
    assert resolved["list"] == ["tok-1234567890"]
    assert vault.redact("leak tok-1234567890 here") == "leak [REDACTED:TOKEN] here"
    with pytest.raises(VaultError):
        vault.resolve("{{vault:MISSING}}")
    assert vault.resolve("{{vault:MISSING}}", strict=False) == "{{vault:MISSING}}"


def test_wrong_key_is_reported(tmp_path: Path):
    vault = CredentialVault(tmp_path / "v.enc", tmp_path / "k1.key")
    vault.set("A", "value-123456")
    other = CredentialVault(tmp_path / "v.enc", tmp_path / "k2.key")
    with pytest.raises(VaultError):
        other.get("A")
