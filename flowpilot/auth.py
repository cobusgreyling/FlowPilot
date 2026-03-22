"""Authentication and Role-Based Access Control for FlowPilot."""

import hashlib
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Role(Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


ROLE_PERMISSIONS = {
    Role.ADMIN: {
        "workflows.create", "workflows.run", "workflows.delete", "workflows.validate",
        "workflows.export", "workflows.import",
        "secrets.read", "secrets.write", "secrets.delete",
        "users.create", "users.delete", "users.list", "users.update",
        "history.read", "history.clear",
        "sla.read", "sla.write",
        "reports.generate", "reports.deliver",
        "marketplace.publish", "marketplace.install",
        "settings.read", "settings.write",
        "connectors.manage",
    },
    Role.EDITOR: {
        "workflows.create", "workflows.run", "workflows.validate",
        "workflows.export", "workflows.import",
        "secrets.read",
        "history.read",
        "sla.read",
        "reports.generate",
        "marketplace.install",
        "connectors.manage",
    },
    Role.VIEWER: {
        "workflows.validate",
        "history.read",
        "sla.read",
        "reports.generate",
    },
}


@dataclass
class User:
    username: str
    role: Role
    created_at: str = ""
    last_login: str = ""
    active: bool = True


@dataclass
class APIKey:
    key_id: str
    key_prefix: str
    username: str
    name: str
    created_at: str = ""
    last_used: str = ""
    active: bool = True


@dataclass
class Session:
    session_id: str
    username: str
    created_at: float
    expires_at: float


class AuthManager:
    """Manages users, API keys, sessions, and permissions."""

    def __init__(self, db_path: str = "flowpilot_auth.db"):
        self.db_path = db_path
        self._sessions: dict[str, Session] = {}
        self._session_ttl = 3600 * 24
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'viewer',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    active INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP,
                    active INTEGER DEFAULT 1,
                    FOREIGN KEY (username) REFERENCES users(username)
                )
            """)
            conn.commit()
            cursor = conn.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                default_password = os.environ.get("FLOWPILOT_ADMIN_PASSWORD", "admin")
                self.create_user("admin", default_password, Role.ADMIN)

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 100_000
        ).hex()

    @staticmethod
    def _hash_api_key(key: str) -> str:
        return hashlib.sha256(key.encode()).hex()

    def create_user(self, username: str, password: str, role: Role = Role.VIEWER) -> User:
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(password, salt)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, role) VALUES (?, ?, ?, ?)",
                (username, password_hash, salt, role.value),
            )
            conn.commit()
        return User(username=username, role=role)

    def authenticate(self, username: str, password: str) -> Optional[Session]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT password_hash, salt, role, active FROM users WHERE username = ?",
                (username,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            password_hash, salt, role, active = row
            if not active:
                return None
            if self._hash_password(password, salt) != password_hash:
                return None
            conn.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE username = ?",
                (username,),
            )
            conn.commit()
        session_id = secrets.token_urlsafe(32)
        now = time.time()
        session = Session(session_id=session_id, username=username, created_at=now, expires_at=now + self._session_ttl)
        self._sessions[session_id] = session
        return session

    def validate_session(self, session_id: str) -> Optional[User]:
        session = self._sessions.get(session_id)
        if not session or time.time() > session.expires_at:
            self._sessions.pop(session_id, None)
            return None
        return self.get_user(session.username)

    def logout(self, session_id: str):
        self._sessions.pop(session_id, None)

    def create_api_key(self, username: str, name: str) -> tuple[str, APIKey]:
        raw_key = f"fp_{secrets.token_urlsafe(32)}"
        key_id = secrets.token_hex(8)
        key_hash = self._hash_api_key(raw_key)
        key_prefix = raw_key[:10] + "..."
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO api_keys (key_id, key_hash, key_prefix, username, name) VALUES (?, ?, ?, ?, ?)",
                (key_id, key_hash, key_prefix, username, name),
            )
            conn.commit()
        return raw_key, APIKey(key_id=key_id, key_prefix=key_prefix, username=username, name=name)

    def authenticate_api_key(self, raw_key: str) -> Optional[User]:
        key_hash = self._hash_api_key(raw_key)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT username, active FROM api_keys WHERE key_hash = ?", (key_hash,))
            row = cursor.fetchone()
            if not row or not row[1]:
                return None
            conn.execute("UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE key_hash = ?", (key_hash,))
            conn.commit()
        return self.get_user(row[0])

    def revoke_api_key(self, key_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE api_keys SET active = 0 WHERE key_id = ?", (key_id,))
            conn.commit()

    def list_api_keys(self, username: str) -> list[APIKey]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT key_id, key_prefix, username, name, created_at, last_used, active FROM api_keys WHERE username = ?",
                (username,),
            )
            return [
                APIKey(key_id=r[0], key_prefix=r[1], username=r[2], name=r[3],
                       created_at=r[4] or "", last_used=r[5] or "", active=bool(r[6]))
                for r in cursor.fetchall()
            ]

    def get_user(self, username: str) -> Optional[User]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT username, role, created_at, last_login, active FROM users WHERE username = ?", (username,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return User(username=row[0], role=Role(row[1]), created_at=row[2] or "", last_login=row[3] or "", active=bool(row[4]))

    def list_users(self) -> list[User]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT username, role, created_at, last_login, active FROM users")
            return [
                User(username=r[0], role=Role(r[1]), created_at=r[2] or "", last_login=r[3] or "", active=bool(r[4]))
                for r in cursor.fetchall()
            ]

    def update_user_role(self, username: str, role: Role):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE users SET role = ? WHERE username = ?", (role.value, username))
            conn.commit()

    def deactivate_user(self, username: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE users SET active = 0 WHERE username = ?", (username,))
            conn.commit()

    def delete_user(self, username: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM api_keys WHERE username = ?", (username,))
            conn.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()

    def has_permission(self, user: User, permission: str) -> bool:
        if not user.active:
            return False
        return permission in ROLE_PERMISSIONS.get(user.role, set())

    def require_permission(self, user: User, permission: str):
        if not self.has_permission(user, permission):
            raise PermissionError(f"User '{user.username}' ({user.role.value}) lacks permission: {permission}")
