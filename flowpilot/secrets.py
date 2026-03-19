"""Secrets vault — encrypted credential storage for connectors.

Stores API keys and tokens in an encrypted SQLite database using
Fernet symmetric encryption. Avoids raw environment variables and
prevents credentials leaking into shell history.

Usage
-----
    from flowpilot.secrets import SecretsVault

    vault = SecretsVault("my-passphrase")
    vault.set("SLACK_BOT_TOKEN", "xoxb-...")
    token = vault.get("SLACK_BOT_TOKEN")
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from pathlib import Path

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class SecretsVault:
    """Encrypted credential store backed by SQLite.

    Derives a Fernet key from a passphrase using PBKDF2.
    Falls back to base64 obfuscation if cryptography is not installed.
    """

    def __init__(self, passphrase: str | None = None, db_path: str = ".flowpilot_secrets.db"):
        self._db_path = db_path
        self._passphrase = passphrase or os.environ.get("FLOWPILOT_SECRET_KEY", "flowpilot-default")
        self._fernet = self._create_fernet() if HAS_CRYPTO else None
        self._init_db()

    def _create_fernet(self) -> "Fernet":
        key = hashlib.pbkdf2_hmac(
            "sha256",
            self._passphrase.encode(),
            b"flowpilot-salt-v1",
            100_000,
        )
        return Fernet(base64.urlsafe_b64encode(key))

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS secrets (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def set(self, key: str, value: str) -> None:
        """Store an encrypted secret."""
        encrypted = self._encrypt(value)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO secrets (key, value, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value=?, updated_at=CURRENT_TIMESTAMP""",
                (key, encrypted, encrypted),
            )

    def get(self, key: str) -> str | None:
        """Retrieve and decrypt a secret. Returns None if not found."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT value FROM secrets WHERE key = ?", (key,)
            ).fetchone()
        if row:
            return self._decrypt(row[0])
        return None

    def get_or_env(self, key: str) -> str | None:
        """Try vault first, fall back to environment variable."""
        return self.get(key) or os.environ.get(key)

    def delete(self, key: str) -> bool:
        """Remove a secret."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("DELETE FROM secrets WHERE key = ?", (key,))
            return cursor.rowcount > 0

    def list_keys(self) -> list[str]:
        """List all stored secret keys (not values)."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT key FROM secrets ORDER BY key").fetchall()
        return [r[0] for r in rows]

    def _encrypt(self, value: str) -> str:
        if self._fernet:
            return self._fernet.encrypt(value.encode()).decode()
        return base64.b64encode(value.encode()).decode()

    def _decrypt(self, encrypted: str) -> str:
        if self._fernet:
            return self._fernet.decrypt(encrypted.encode()).decode()
        return base64.b64decode(encrypted.encode()).decode()
