"""
Secrets vault for ASHI. Skills request named secrets via get_secret().
v1: JSON file with 0600 permissions. v2: SQLCipher when available.
"""
import os
import json
from typing import Optional

_VAULT_PATH = os.path.expanduser("~/.ashi/secrets.db")


class SecretsVault:
    def __init__(self, vault_path: str = _VAULT_PATH):
        self.vault_path = vault_path
        self._data: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self.vault_path):
            try:
                with open(self.vault_path) as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.vault_path), exist_ok=True)
        with open(self.vault_path, "w") as f:
            json.dump(self._data, f)
        os.chmod(self.vault_path, 0o600)

    def set_secret(self, name: str, value: str):
        self._data[name] = value
        self._save()

    def get_secret(self, name: str) -> Optional[str]:
        if name in self._data:
            return self._data[name]
        return os.environ.get(name)

    def list_secrets(self) -> list[str]:
        return list(self._data.keys())


_vault: Optional[SecretsVault] = None


def _get_vault() -> SecretsVault:
    global _vault
    if _vault is None:
        _vault = SecretsVault()
    return _vault


def get_secret(name: str) -> Optional[str]:
    return _get_vault().get_secret(name)


def set_secret(name: str, value: str):
    _get_vault().set_secret(name, value)
