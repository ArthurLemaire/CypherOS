"""Credential vault.

Secrets live encrypted on disk (Fernet / AES-128-CBC + HMAC). The model only
ever sees placeholders such as ``{{vault:EMAIL_PASSWORD}}``; the Sentinel
resolves them for tools that opted in (``accepts_secrets``) and connectors
resolve their own configuration right before use. Tool output is scrubbed of
any secret value before it is handed back to the model.

Key management: ``$OPENMUSE_VAULT_KEY`` (base64 Fernet key) or a key file at
``~/.openmuse/vault.key`` created on first use with ``0600`` permissions.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

PLACEHOLDER_RE = re.compile(r"\{\{\s*vault:([A-Za-z0-9_.-]+)\s*\}\}")


class VaultError(RuntimeError):
    pass


class CredentialVault:
    def __init__(self, path: Path, key_path: Path | None = None):
        self.path = Path(path)
        self.key_path = Path(key_path) if key_path else self.path.with_suffix(".key")
        self._fernet: Fernet | None = None
        self._cache: dict[str, str] | None = None

    # ------------------------------------------------------------------ key handling
    def _key(self) -> bytes:
        env_key = os.environ.get("OPENMUSE_VAULT_KEY")
        if env_key:
            return env_key.encode()
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        self.key_path.write_bytes(key)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:  # pragma: no cover - windows
            pass
        return key

    @property
    def fernet(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(self._key())
        return self._fernet

    # ------------------------------------------------------------------ persistence
    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = {}
            return self._cache
        try:
            raw = self.fernet.decrypt(self.path.read_bytes())
        except InvalidToken as exc:
            raise VaultError(
                f"cannot decrypt {self.path} – wrong key? (key file: {self.key_path})"
            ) from exc
        data = json.loads(raw.decode("utf-8"))
        self._cache = {str(k): str(v) for k, v in data.items()}
        return self._cache

    def _save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = self.fernet.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(token)
        try:
            os.chmod(tmp, 0o600)
        except OSError:  # pragma: no cover
            pass
        tmp.replace(self.path)
        self._cache = dict(data)

    # ------------------------------------------------------------------ public API
    def set(self, name: str, value: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise VaultError("secret names may only contain letters, digits, '_', '.', '-'")
        data = dict(self._load())
        data[name] = value
        self._save(data)

    def get(self, name: str) -> str | None:
        return self._load().get(name)

    def delete(self, name: str) -> bool:
        data = dict(self._load())
        existed = data.pop(name, None) is not None
        if existed:
            self._save(data)
        return existed

    def names(self) -> list[str]:
        return sorted(self._load().keys())

    def has_placeholders(self, value: Any) -> bool:
        return bool(PLACEHOLDER_RE.search(json.dumps(value, ensure_ascii=False, default=str)))

    def resolve(self, value: Any, strict: bool = True) -> Any:
        """Replace ``{{vault:NAME}}`` placeholders inside strings / dicts / lists."""
        if isinstance(value, str):

            def repl(m: re.Match[str]) -> str:
                secret = self.get(m.group(1))
                if secret is None:
                    if strict:
                        raise VaultError(
                            f"secret '{m.group(1)}' is not in the vault "
                            f"(add it with: openmuse vault set {m.group(1)})"
                        )
                    return m.group(0)
                return secret

            return PLACEHOLDER_RE.sub(repl, value)
        if isinstance(value, dict):
            return {k: self.resolve(v, strict) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve(v, strict) for v in value]
        return value

    def redact(self, text: str) -> str:
        """Replace any stored secret value appearing in ``text``."""
        if not text:
            return text
        for name, secret in self._load().items():
            if len(secret) >= 6 and secret in text:
                text = text.replace(secret, f"[REDACTED:{name}]")
        return text


__all__ = ["CredentialVault", "VaultError", "PLACEHOLDER_RE"]
