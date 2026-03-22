"""OAuth2 flow manager for connector authentication."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


@dataclass
class OAuth2Provider:
    name: str
    client_id: str
    client_secret: str
    auth_url: str
    token_url: str
    scopes: list[str] = field(default_factory=list)
    redirect_uri: str = "http://localhost:7860/oauth/callback"


@dataclass
class OAuth2Token:
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    token_type: str = "Bearer"
    scope: str = ""

    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at


PROVIDER_CONFIGS = {
    "google": {"auth_url": "https://accounts.google.com/o/oauth2/v2/auth", "token_url": "https://oauth2.googleapis.com/token"},
    "github": {"auth_url": "https://github.com/login/oauth/authorize", "token_url": "https://github.com/login/oauth/access_token"},
    "slack": {"auth_url": "https://slack.com/oauth/v2/authorize", "token_url": "https://slack.com/api/oauth.v2.access"},
    "microsoft": {"auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize", "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token"},
    "stripe": {"auth_url": "https://connect.stripe.com/oauth/authorize", "token_url": "https://connect.stripe.com/oauth/token"},
}


class OAuth2Manager:
    """Manages OAuth2 flows, token storage, and refresh."""

    def __init__(self, db_path: str = "flowpilot_oauth.db"):
        self.db_path = db_path
        self._providers: dict[str, OAuth2Provider] = {}
        self._encryption_key = self._derive_key()
        self._init_db()

    def _derive_key(self) -> bytes:
        secret = os.environ.get("FLOWPILOT_SECRET_KEY", "flowpilot-default-key")
        if HAS_CRYPTO:
            key = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"flowpilot-oauth", 100_000)
            return base64.urlsafe_b64encode(key[:32])
        return b""

    def _encrypt(self, data: str) -> str:
        if HAS_CRYPTO and self._encryption_key:
            return Fernet(self._encryption_key).encrypt(data.encode()).decode()
        return base64.b64encode(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        if HAS_CRYPTO and self._encryption_key:
            return Fernet(self._encryption_key).decrypt(data.encode()).decode()
        return base64.b64decode(data.encode()).decode()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    provider TEXT NOT NULL,
                    username TEXT NOT NULL,
                    token_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (provider, username)
                )
            """)
            conn.commit()

    def register_provider(self, provider: OAuth2Provider):
        self._providers[provider.name] = provider

    def get_auth_url(self, provider_name: str, state: str = "") -> tuple[str, str]:
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' not registered")
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()
        if not state:
            state = secrets.token_urlsafe(16)
        params = {
            "client_id": provider.client_id,
            "redirect_uri": provider.redirect_uri,
            "response_type": "code",
            "scope": " ".join(provider.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        url = f"{provider.auth_url}?{urlencode(params)}"
        return url, code_verifier

    def exchange_code(self, provider_name: str, code: str, code_verifier: str = "") -> OAuth2Token:
        if not HAS_REQUESTS:
            raise RuntimeError("requests library required for OAuth2")
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' not registered")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": provider.redirect_uri,
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        resp = _requests.post(provider.token_url, data=data, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        token = OAuth2Token(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", ""),
            expires_at=time.time() + body.get("expires_in", 3600),
            token_type=body.get("token_type", "Bearer"),
            scope=body.get("scope", ""),
        )
        return token

    def refresh_token(self, provider_name: str, username: str) -> OAuth2Token:
        if not HAS_REQUESTS:
            raise RuntimeError("requests library required for OAuth2")
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' not registered")
        current = self.get_valid_token(provider_name, username)
        if not current or not current.refresh_token:
            raise ValueError("No refresh token available")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": current.refresh_token,
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
        }
        resp = _requests.post(provider.token_url, data=data, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        token = OAuth2Token(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", current.refresh_token),
            expires_at=time.time() + body.get("expires_in", 3600),
            token_type=body.get("token_type", "Bearer"),
            scope=body.get("scope", current.scope),
        )
        self.store_token(provider_name, username, token)
        return token

    def get_valid_token(self, provider_name: str, username: str) -> Optional[OAuth2Token]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT token_data FROM oauth_tokens WHERE provider = ? AND username = ?",
                (provider_name, username),
            )
            row = cursor.fetchone()
            if not row:
                return None
        data = json.loads(self._decrypt(row[0]))
        token = OAuth2Token(**data)
        if token.is_expired and token.refresh_token:
            try:
                return self.refresh_token(provider_name, username)
            except Exception as e:
                logger.warning(f"Token refresh failed: {e}")
                return None
        return token if not token.is_expired else None

    def store_token(self, provider_name: str, username: str, token: OAuth2Token):
        encrypted = self._encrypt(json.dumps({
            "access_token": token.access_token, "refresh_token": token.refresh_token,
            "expires_at": token.expires_at, "token_type": token.token_type, "scope": token.scope,
        }))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO oauth_tokens (provider, username, token_data, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (provider_name, username, encrypted),
            )
            conn.commit()

    def revoke_token(self, provider_name: str, username: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM oauth_tokens WHERE provider = ? AND username = ?", (provider_name, username))
            conn.commit()

    def list_connections(self, username: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT provider, updated_at FROM oauth_tokens WHERE username = ?", (username,),
            )
            return [{"provider": r[0], "connected_at": r[1]} for r in cursor.fetchall()]
