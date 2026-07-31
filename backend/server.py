from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = next((p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents] if (p / ".env").exists()), Path(__file__).resolve().parent.parent)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.config import create_profile, delete_profile, hard_delete_profile, load_profiles, set_default_profile, update_profile
from llm.providers.gemini_provider import GeminiProvider
from llm.providers.openai_provider import OpenAIProvider

from backend.fault_diagnoses_agent import ServiceCatalog

FALLBACK_ALIYUN_MODELS = [
    "qwen-max",
    "qwen-plus",
    "qwen-turbo",
    "qwen-long",
    "qwen3-max-preview",
    "qwen3-235b-a22b",
    "qwen3-32b",
    "qwen3-14b",
    "qwen3-8b",
    "qwen-vl-max",
    "qwen-vl-plus",
    "qwen2.5-vl-72b-instruct",
    "qwen2.5-vl-32b-instruct",
    "qvq-max",
    "qwen-omni-turbo",
]

FALLBACK_GEMINI_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
MANAGEABLE_ROLES = {ROLE_ADMIN, ROLE_USER}
SUPER_ADMIN_USERNAME = "YPCJ"
SUPER_ADMIN_PASSWORD = "20201214"
SESSION_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_session_title(app_id: str) -> str:
    app_name = app_id.strip() or "app"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"{app_name} {ts}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _auth_db_path() -> Path:
    return PROJECT_ROOT / "data" / "auth.sqlite3"


def _session_db_path() -> Path:
    return PROJECT_ROOT / "data" / "session.sqlite3"


def _new_password_hash(password: str) -> str:
    iterations = 200_000
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, raw_iters, salt, digest = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(raw_iters)
        expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()
    except Exception:
        return False
    return hmac.compare_digest(expected, digest)


def _is_valid_username(username: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{2,31}", username))


def _is_super_admin_username(username: str) -> bool:
    return username.strip().casefold() == SUPER_ADMIN_USERNAME.casefold()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.strip()) // 4) if text else 0


@dataclass
class User:
    username: str
    role: str
    password: str = ""


@dataclass
class Session:
    id: str
    owner: str
    app_id: str
    title: str
    status: str
    updated_at: str
    model_profile_id: str
    model_name: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)


class AppState:
    def __init__(self):
        self.catalog = ServiceCatalog()
        self.sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._event_cond = threading.Condition(self._lock)
        self._run_events: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._run_state: dict[tuple[str, str], str] = {}
        self._latest_run_by_session: dict[str, str] = {}
        self.auth_db_path = _auth_db_path()
        self.session_db_path = _session_db_path()
        self._init_auth_store()
        self._init_session_store()
        self.sessions = self._load_sessions_from_store()
        self._purge_deleted_model_profiles_if_unused()

    def login(self, username: str, password: str) -> dict[str, Any]:
        if not username or not password:
            raise ValueError("用户名和密码不能为空")
        role = "admin" if "admin" in username.lower() else "user"
        self.users[username] = User(username=username, role=role, password=password)
        token = f"tok_{uuid.uuid4().hex}"
        self.tokens[token] = username
        return {"access_token": token, "role": role}

    def logout(self, token: str) -> None:
        self.tokens.pop(token, None)

    def current_user(self, token: str) -> User:
        username = self.tokens.get(token)
        if not username:
            raise PermissionError("未登录或 token 无效")
        return self.users[username]

    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.auth_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _session_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.session_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_session_schema_version(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT value FROM session_meta WHERE key = 'schema_version'").fetchone()
        if not row:
            return 0
        try:
            return int(str(row["value"]))
        except ValueError:
            return 0

    def _set_session_schema_version(self, conn: sqlite3.Connection, version: int) -> None:
        conn.execute(
            "INSERT INTO session_meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(version),),
        )

    def _migrate_session_store_to_v1(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                app_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                model_profile_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                kind TEXT NOT NULL,
                model TEXT,
                tokens INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                position INTEGER NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_messages_sid_pos ON session_messages(session_id, position)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                record_type TEXT NOT NULL,
                label TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                position INTEGER NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_records_sid_pos ON session_records(session_id, position)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                position INTEGER NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_artifacts_sid_pos ON session_artifacts(session_id, position)")

    def _init_session_store(self) -> None:
        self.session_db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._session_db() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            version = self._get_session_schema_version(conn)
            if version < 1:
                self._migrate_session_store_to_v1(conn)
                version = 1
            if version != SESSION_SCHEMA_VERSION:
                raise RuntimeError(
                    f"不支持的 session schema 版本: {version}, 期望 {SESSION_SCHEMA_VERSION}。"
                )
            self._set_session_schema_version(conn, SESSION_SCHEMA_VERSION)

    def _load_sessions_from_store(self) -> dict[str, Session]:
        loaded: dict[str, Session] = {}
        with self._session_db() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            rows = conn.execute(
                """
                SELECT session_id, owner, app_id, title, status, updated_at, model_profile_id, model_name
                FROM sessions
                ORDER BY updated_at DESC
                """
            ).fetchall()
            for row in rows:
                session_id = str(row["session_id"])
                messages = []
                message_rows = conn.execute(
                    """
                    SELECT payload_json FROM session_messages
                    WHERE session_id = ?
                    ORDER BY position ASC, id ASC
                    """,
                    (session_id,),
                ).fetchall()
                for message_row in message_rows:
                    try:
                        payload = json.loads(str(message_row["payload_json"]))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        messages.append(payload)

                records = []
                record_rows = conn.execute(
                    """
                    SELECT payload_json FROM session_records
                    WHERE session_id = ?
                    ORDER BY position ASC, id ASC
                    """,
                    (session_id,),
                ).fetchall()
                for record_row in record_rows:
                    try:
                        payload = json.loads(str(record_row["payload_json"]))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        records.append(payload)

                artifacts = []
                artifact_rows = conn.execute(
                    """
                    SELECT payload_json FROM session_artifacts
                    WHERE session_id = ?
                    ORDER BY position ASC, id ASC
                    """,
                    (session_id,),
                ).fetchall()
                for artifact_row in artifact_rows:
                    try:
                        payload = json.loads(str(artifact_row["payload_json"]))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        artifacts.append(payload)

                loaded[session_id] = Session(
                    id=session_id,
                    owner=str(row["owner"]),
                    app_id=str(row["app_id"]),
                    title=str(row["title"]),
                    status=str(row["status"]),
                    updated_at=str(row["updated_at"]),
                    model_profile_id=str(row["model_profile_id"]),
                    model_name=str(row["model_name"]),
                    messages=messages,
                    records=records,
                    artifacts=artifacts,
                )
        return loaded

    def _persist_all_sessions(self) -> None:
        with self._lock:
            for session in self.sessions.values():
                self._persist_session(session)

    def _persist_session(self, session: Session) -> None:
        with self._session_db() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            existing = conn.execute(
                "SELECT created_at FROM sessions WHERE session_id = ?",
                (session.id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else _now()
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, owner, app_id, title, status, updated_at, model_profile_id, model_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    owner = excluded.owner,
                    app_id = excluded.app_id,
                    title = excluded.title,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    model_profile_id = excluded.model_profile_id,
                    model_name = excluded.model_name
                """,
                (
                    session.id,
                    session.owner,
                    session.app_id,
                    session.title,
                    session.status,
                    session.updated_at,
                    session.model_profile_id,
                    session.model_name,
                    created_at,
                ),
            )

            conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session.id,))
            for idx, message in enumerate(session.messages):
                conn.execute(
                    """
                    INSERT INTO session_messages (
                        session_id, message_id, role, content, kind, model, tokens, payload_json, position
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.id,
                        str(message.get("id", f"{session.id}_m_{idx+1}")),
                        str(message.get("role", "")),
                        str(message.get("content", "")),
                        str(message.get("kind", "text")),
                        message.get("model"),
                        int(message.get("tokens", 0) or 0),
                        json.dumps(message, ensure_ascii=False, default=str),
                        idx,
                    ),
                )

            conn.execute("DELETE FROM session_records WHERE session_id = ?", (session.id,))
            for idx, record in enumerate(session.records):
                conn.execute(
                    """
                    INSERT INTO session_records (
                        session_id, record_id, record_type, label, payload_json, position
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.id,
                        str(record.get("id", f"{session.id}_r_{idx+1}")),
                        str(record.get("type", "other")),
                        str(record.get("label", "")),
                        json.dumps(record, ensure_ascii=False, default=str),
                        idx,
                    ),
                )

            conn.execute("DELETE FROM session_artifacts WHERE session_id = ?", (session.id,))
            for idx, artifact in enumerate(session.artifacts):
                conn.execute(
                    """
                    INSERT INTO session_artifacts (
                        session_id, artifact_id, name, path, artifact_type, payload_json, position
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.id,
                        str(artifact.get("id", f"{session.id}_a_{idx+1}")),
                        str(artifact.get("name", "")),
                        str(artifact.get("path", "")),
                        str(artifact.get("artifact_type", "other")),
                        json.dumps(artifact, ensure_ascii=False, default=str),
                        idx,
                    ),
                )

    def _delete_session_from_store(self, session_id: str) -> None:
        with self._session_db() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def _init_auth_store(self) -> None:
        self.auth_db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('super_admin','admin','user')),
                    is_disabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
                )
                """
            )
            users_table_sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
            ).fetchone()
            users_table_sql = str(users_table_sql_row["sql"]) if users_table_sql_row else ""
            if "super_admin" not in users_table_sql:
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("ALTER TABLE users RENAME TO users_legacy")
                conn.execute(
                    """
                    CREATE TABLE users (
                        username TEXT PRIMARY KEY,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL CHECK(role IN ('super_admin','admin','user')),
                        is_disabled INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO users (username, password_hash, role, is_disabled, created_at, updated_at)
                    SELECT username, password_hash, role, is_disabled, created_at, updated_at FROM users_legacy
                    """
                )
                conn.execute("DROP TABLE users_legacy")
                conn.execute("PRAGMA foreign_keys = ON")
        admin_username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
        admin_password = os.getenv("ADMIN_PASSWORD", "20210426").strip() or "20210426"
        self._ensure_admin_user(admin_username, admin_password)
        self._ensure_super_admin_user(SUPER_ADMIN_USERNAME, SUPER_ADMIN_PASSWORD)

    def _ensure_admin_user(self, username: str, password: str) -> None:
        if _is_super_admin_username(username):
            return
        now = _now()
        with self._db() as conn:
            row = conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET role = ?, is_disabled = 0, updated_at = ? WHERE username = ?",
                    (ROLE_ADMIN, now, username),
                )
                return
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_disabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                (username, _new_password_hash(password), ROLE_ADMIN, now, now),
            )

    def _ensure_super_admin_user(self, username: str, password: str) -> None:
        now = _now()
        with self._db() as conn:
            row = conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET password_hash = ?, role = ?, is_disabled = 0, updated_at = ? WHERE username = ?",
                    (_new_password_hash(password), ROLE_SUPER_ADMIN, now, username),
                )
                return
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_disabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                (username, _new_password_hash(password), ROLE_SUPER_ADMIN, now, now),
            )

    def register(self, username: str, password: str) -> dict[str, Any]:
        clean_username = username.strip()
        if _is_super_admin_username(clean_username):
            raise ValueError("该用户名不可注册")
        if not _is_valid_username(clean_username):
            raise ValueError("用户名格式非法：3-32位，仅支持字母/数字/下划线/中划线，且不能以中划线开头")
        if len(password) < 6:
            raise ValueError("密码长度至少为 6 位")
        now = _now()
        with self._db() as conn:
            exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (clean_username,)).fetchone()
            if exists:
                raise ValueError("用户名已存在")
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_disabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                (clean_username, _new_password_hash(password), ROLE_USER, now, now),
            )
        return {"username": clean_username, "role": ROLE_USER}

    @staticmethod
    def _can_manage_target(requester_role: str, target_role: str) -> bool:
        if requester_role == ROLE_SUPER_ADMIN:
            return target_role in MANAGEABLE_ROLES
        if requester_role == ROLE_ADMIN:
            return target_role == ROLE_USER
        return False

    @staticmethod
    def _creatable_roles(requester_role: str) -> set[str]:
        if requester_role == ROLE_SUPER_ADMIN:
            return {ROLE_ADMIN, ROLE_USER}
        if requester_role == ROLE_ADMIN:
            return {ROLE_USER}
        return set()

    def create_user_by_admin(self, requester: User, username: str, password: str, role: str = "user") -> dict[str, Any]:
        creatable_roles = self._creatable_roles(requester.role)
        if not creatable_roles:
            raise PermissionError("无权限")
        clean_username = username.strip()
        role_value = role.strip() or ROLE_USER
        if _is_super_admin_username(clean_username):
            raise ValueError("该用户名不可创建")
        if not _is_valid_username(clean_username):
            raise ValueError("用户名格式非法：3-32位，仅支持字母/数字/下划线/中划线，且不能以中划线开头")
        if len(password) < 6:
            raise ValueError("密码长度至少为 6 位")
        if role_value not in creatable_roles:
            raise ValueError("当前角色无权创建该类型用户")
        now = _now()
        with self._db() as conn:
            exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (clean_username,)).fetchone()
            if exists:
                raise ValueError("用户名已存在")
            conn.execute(
                "INSERT INTO users (username, password_hash, role, is_disabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                (clean_username, _new_password_hash(password), role_value, now, now),
            )
        return {"username": clean_username, "role": role_value}

    def login(self, username: str, password: str) -> dict[str, Any]:
        clean_username = username.strip()
        if not clean_username or not password:
            raise ValueError("用户名和密码不能为空")
        with self._db() as conn:
            row = conn.execute(
                "SELECT username, role, password_hash, is_disabled FROM users WHERE username = ?",
                (clean_username,),
            ).fetchone()
            if not row:
                raise PermissionError("用户名或密码错误")
            if int(row["is_disabled"]) == 1:
                raise PermissionError("账号已禁用")
            if not _verify_password(password, str(row["password_hash"])):
                raise PermissionError("用户名或密码错误")
            token = f"tok_{uuid.uuid4().hex}"
            expires_at = (_utcnow() + timedelta(days=7)).isoformat()
            conn.execute(
                "INSERT INTO auth_tokens (token, username, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token, str(row["username"]), expires_at, _now()),
            )
            return {"access_token": token, "role": str(row["role"]), "expires_at": expires_at}

    def logout(self, token: str) -> None:
        with self._db() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))

    def current_user(self, token: str) -> User:
        if not token:
            raise PermissionError("未登录或 token 无效")
        now_iso = _utcnow().isoformat()
        with self._db() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE expires_at <= ?", (now_iso,))
            row = conn.execute(
                """
                SELECT u.username AS username, u.role AS role, u.is_disabled AS is_disabled
                FROM auth_tokens t
                JOIN users u ON u.username = t.username
                WHERE t.token = ?
                """,
                (token,),
            ).fetchone()
            if not row:
                raise PermissionError("未登录或 token 无效")
            if int(row["is_disabled"]) == 1:
                raise PermissionError("账号已禁用")
            return User(username=str(row["username"]), role=str(row["role"]))

    def visible_sessions(self, user: User) -> list[Session]:
        if user.role in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
            return list(self.sessions.values())
        return [session for session in self.sessions.values() if session.owner == user.username]

    def list_users(self, requester: User) -> list[dict[str, Any]]:
        if requester.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
            raise PermissionError("无权限")
        with self._db() as conn:
            rows = conn.execute(
                "SELECT username, role, is_disabled, created_at, updated_at FROM users ORDER BY created_at ASC"
            ).fetchall()
            return [
                {
                    "username": str(row["username"]),
                    "role": str(row["role"]),
                    "is_disabled": bool(int(row["is_disabled"])),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in rows
                if not _is_super_admin_username(str(row["username"]))
            ]

    def update_user(self, requester: User, username: str, *, role: str | None = None, is_disabled: bool | None = None) -> dict[str, Any]:
        if requester.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
            raise PermissionError("无权限")
        if requester.role == ROLE_ADMIN:
            raise PermissionError("管理员无权修改用户信息")
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("用户名不能为空")
        if _is_super_admin_username(clean_username):
            raise PermissionError("无权限修改超级管理员")
        now = _now()
        with self._db() as conn:
            row = conn.execute(
                "SELECT username, role, is_disabled, created_at, updated_at FROM users WHERE username = ?",
                (clean_username,),
            ).fetchone()
            if not row:
                raise KeyError(clean_username)
            target_role = str(row["role"])
            if not self._can_manage_target(requester.role, target_role):
                raise PermissionError("无权限")

            next_role = str(row["role"])
            next_disabled = bool(int(row["is_disabled"]))
            if role is not None:
                role_value = role.strip()
                if role_value not in MANAGEABLE_ROLES:
                    raise ValueError("role 仅支持 admin 或 user")
                if requester.role == ROLE_ADMIN:
                    raise PermissionError("管理员无权修改角色")
                next_role = role_value
            if is_disabled is not None:
                next_disabled = bool(is_disabled)
            if clean_username == requester.username and next_disabled:
                raise ValueError("不能禁用当前登录管理员")

            conn.execute(
                "UPDATE users SET role = ?, is_disabled = ?, updated_at = ? WHERE username = ?",
                (next_role, 1 if next_disabled else 0, now, clean_username),
            )
            updated = conn.execute(
                "SELECT username, role, is_disabled, created_at, updated_at FROM users WHERE username = ?",
                (clean_username,),
            ).fetchone()
            return {
                "username": str(updated["username"]),
                "role": str(updated["role"]),
                "is_disabled": bool(int(updated["is_disabled"])),
                "created_at": str(updated["created_at"]),
                "updated_at": str(updated["updated_at"]),
            }

    def delete_user(self, requester: User, username: str) -> None:
        if requester.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
            raise PermissionError("无权限")
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("用户名不能为空")
        if _is_super_admin_username(clean_username):
            raise PermissionError("无权限删除超级管理员")
        if clean_username == requester.username:
            raise ValueError("不能删除当前登录用户")
        with self._db() as conn:
            row = conn.execute("SELECT role FROM users WHERE username = ?", (clean_username,)).fetchone()
            if not row:
                raise KeyError(clean_username)
            if not self._can_manage_target(requester.role, str(row["role"])):
                raise PermissionError("无权限")
            conn.execute("DELETE FROM users WHERE username = ?", (clean_username,))

    def update_own_password(self, requester: User, current_password: str, new_password: str) -> None:
        if len(new_password) < 6:
            raise ValueError("新密码长度至少为 6 位")
        with self._db() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                (requester.username,),
            ).fetchone()
            if not row:
                raise KeyError(requester.username)
            if not _verify_password(current_password, str(row["password_hash"])):
                raise PermissionError("当前密码错误")
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE username = ?",
                (_new_password_hash(new_password), _now(), requester.username),
            )

    def reset_user_password_by_admin(self, requester: User, username: str, new_password: str) -> None:
        if requester.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
            raise PermissionError("无权限")
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("用户名不能为空")
        if _is_super_admin_username(clean_username):
            raise PermissionError("无权限修改超级管理员")
        if len(new_password) < 6:
            raise ValueError("新密码长度至少为 6 位")
        with self._db() as conn:
            row = conn.execute("SELECT role FROM users WHERE username = ?", (clean_username,)).fetchone()
            if not row:
                raise KeyError(clean_username)
            target_role = str(row["role"])
            if not self._can_manage_target(requester.role, target_role):
                raise PermissionError("无权限")
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE username = ?",
                (_new_password_hash(new_password), _now(), clean_username),
            )

    @staticmethod
    def ui_status(raw_status: str) -> str:
        return "archived" if raw_status == "archived" else "active"

    def grouped_sessions(self, user: User) -> dict[str, list[dict[str, Any]]]:
        active: list[dict[str, Any]] = []
        archived: list[dict[str, Any]] = []
        for session in sorted(self.visible_sessions(user), key=lambda item: item.updated_at, reverse=True):
            payload = self.session_payload(session)
            if self.ui_status(session.status) == "active":
                active.append(payload)
            else:
                archived.append(payload)
        return {"active": active, "archived": archived}

    def session_payload(self, session: Session) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "title": session.title,
            "status": self.ui_status(session.status),
            "updated_at": session.updated_at,
            "model_profile_id": session.model_profile_id,
            "model_name": session.model_name,
        }

    def message_payload(self, message: dict[str, Any]) -> dict[str, Any]:
        return {
            "message_id": message.get("id"),
            "role": message.get("role"),
            "content": message.get("content", ""),
            "kind": message.get("kind", "text"),
            "model_profile_id": message.get("model"),
            "usage": {"total_tokens": message.get("tokens", 0)},
        }

    def record_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "record_id": record.get("id"),
            "record_type": record.get("type"),
            "label": record.get("label", ""),
        }

    def artifact_payload(self, artifact: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact_id": artifact.get("id"),
            "filename": artifact.get("name"),
            "path": artifact.get("path"),
            "artifact_type": artifact.get("artifact_type"),
            "session_id": artifact.get("session_id"),
        }

    def create_session(self, user: User, app_id: str, model_profile_id: str | None, title: str | None = None) -> Session:
        profiles = load_profiles(include_deleted=False)
        profile_id = model_profile_id or profiles["default_profile"]
        profile = profiles["profiles"].get(profile_id)
        if not profile_id or not isinstance(profile, dict):
            raise ValueError("未找到可用的模型入口")
        session_title = (title or "").strip() or _default_session_title(app_id)
        model_name = str(profile.get("model") or profile_id)
        session = Session(
            id=f"sess_{uuid.uuid4().hex[:8]}",
            owner=user.username,
            app_id=app_id,
            title=session_title,
            status="running",
            updated_at=_now(),
            model_profile_id=profile_id,
            model_name=model_name,
        )
        with self._lock:
            self.sessions[session.id] = session
            self._persist_session(session)
        return session

    def _count_sessions_using_profile(self, profile_id: str) -> int:
        with self._session_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM sessions WHERE model_profile_id = ?",
                (profile_id,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def _purge_deleted_model_profiles_if_unused(self) -> None:
        profiles = load_profiles()
        deleted_ids = [
            profile_id
            for profile_id, profile in profiles.get("profiles", {}).items()
            if isinstance(profile, dict) and profile.get("deleted_at")
        ]
        for profile_id in deleted_ids:
            if self._count_sessions_using_profile(profile_id) == 0:
                hard_delete_profile(profile_id)

    def get_session(self, user: User, session_id: str) -> Session:
        with self._lock:
            session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        if user.role not in {ROLE_SUPER_ADMIN, ROLE_ADMIN} and session.owner != user.username:
            raise PermissionError("无权访问该 session")
        return session

    def list_records(self, session: Session, kind: str) -> list[dict[str, Any]]:
        if kind == "skills":
            return [record for record in session.records if record.get("type") == "skill"]
        if kind == "tools":
            return [record for record in session.records if record.get("type") == "tool"]
        return session.records

    def list_artifacts(self, user: User, session_id: str | None = None, artifact_type: str | None = None) -> list[dict[str, Any]]:
        sessions = self.visible_sessions(user)
        if session_id:
            sessions = [session for session in sessions if session.id == session_id]
        items: list[dict[str, Any]] = []
        for session in sessions:
            for artifact in session.artifacts:
                if artifact_type and artifact_type != "all" and artifact.get("artifact_type") != artifact_type:
                    continue
                items.append(artifact)
        return items

    def list_models(self) -> dict[str, Any]:
        profiles = load_profiles(include_deleted=False)
        items = []
        for profile_id, profile in profiles["profiles"].items():
            items.append(
                {
                    "profile_id": profile_id,
                    "provider": profile.get("provider"),
                    "model_name": profile.get("model"),
                    "base_url": profile.get("base_url"),
                    "temperature": profile.get("temperature"),
                    "top_p": profile.get("top_p"),
                    "top_k": profile.get("top_k"),
                    "max_output_tokens": profile.get("max_output_tokens"),
                }
            )
        return {"items": items, "default_profile": profiles["default_profile"]}

    def list_aliyun_model_catalog(self, query: str = "", profile_id: str = "qwen_default") -> list[str]:
        profiles = load_profiles(include_deleted=False).get("profiles", {})
        profile = profiles.get(profile_id)
        if not isinstance(profile, dict):
            profile = None
        if not profile:
            for item in profiles.values():
                if isinstance(item, dict) and str(item.get("provider", "")).lower() == "aliyun":
                    profile = item
                    break
        if not profile:
            return []
        models: list[str]
        try:
            provider = OpenAIProvider(profile)
            models = provider.list_models()
        except Exception:
            models = FALLBACK_ALIYUN_MODELS
        q = query.strip().lower()
        if not q:
            return sorted(set(models))
        return [m for m in models if q in m.lower()]

    def list_gemini_model_catalog(self, query: str = "") -> list[str]:
        try:
            models = GeminiProvider().list_models()
        except Exception:
            models = FALLBACK_GEMINI_MODELS
        q = query.strip().lower()
        if not q:
            return sorted(set(models))
        return [m for m in models if q in m.lower()]

    def _emit_event(self, session_id: str, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        key = (session_id, run_id)
        with self._event_cond:
            events = self._run_events.setdefault(key, [])
            event = {
                "id": f"{run_id}_{len(events) + 1}",
                "type": event_type,
                "session_id": session_id,
                "run_id": run_id,
                "timestamp": _now(),
                "payload": payload,
            }
            events.append(event)
            self._event_cond.notify_all()

    def _set_run_state(self, session_id: str, run_id: str, state: str) -> None:
        key = (session_id, run_id)
        with self._event_cond:
            self._run_state[key] = state
            self._event_cond.notify_all()

    def _append_assistant_message(
        self,
        session: Session,
        *,
        content: str,
        kind: str,
        model: str | None,
        tokens: int,
    ) -> dict[str, Any]:
        message = {
            "id": f"{session.id}_a_{len(session.messages)+1}",
            "role": "assistant",
            "content": content,
            "kind": kind,
            "model": model,
            "tokens": tokens,
        }
        session.messages.append(message)
        return message

    @staticmethod
    def _parse_record_label(label: str) -> tuple[str, dict[str, Any]]:
        raw = str(label or "").strip()
        if not raw:
            return "", {}
        if "(" not in raw or not raw.endswith(")"):
            return raw, {}
        tool_name, args_text = raw.split("(", 1)
        args_text = args_text[:-1].strip()
        if not args_text:
            return tool_name.strip(), {}
        try:
            parsed = json.loads(args_text)
            if isinstance(parsed, dict):
                return tool_name.strip(), parsed
        except json.JSONDecodeError:
            pass
        return tool_name.strip(), {"raw": args_text}

    def _execute_run(self, session_id: str, run_id: str, user_content: str) -> None:
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                self._set_run_state(session_id, run_id, "error")
                self._emit_event(session_id, run_id, "run.error", {"message": "session 已不存在"})
                return
            app_id = session.app_id
            model_profile_id = session.model_profile_id
            model_name = session.model_name
            messages_snapshot = list(session.messages)

        def stream_trace(text: str) -> None:
            trace_text = str(text).strip()
            if not trace_text:
                return
            with self._lock:
                sess = self.sessions.get(session_id)
                if not sess:
                    return
                message = self._append_assistant_message(
                    sess,
                    content=trace_text,
                    kind="log",
                    model=model_profile_id,
                    tokens=_estimate_tokens(trace_text),
                )
                self._persist_session(sess)
            self._emit_event(session_id, run_id, "message.delta", {"message": self.message_payload(message)})

        def stream_assistant(msg: dict[str, Any]) -> None:
            content = str(msg.get("content", "") or "").strip()
            if not content:
                return
            with self._lock:
                sess = self.sessions.get(session_id)
                if not sess:
                    return
                message = self._append_assistant_message(
                    sess,
                    content=content,
                    kind="text",
                    model=msg.get("model"),
                    tokens=int(msg.get("tokens", 0) or _estimate_tokens(content)),
                )
                self._persist_session(sess)
            self._emit_event(session_id, run_id, "message.delta", {"message": self.message_payload(message)})

        def stream_record(rec: dict[str, Any]) -> None:
            with self._lock:
                sess = self.sessions.get(session_id)
                if not sess:
                    return
                sess.records.append(rec)
                self._persist_session(sess)
            self._emit_event(session_id, run_id, "record.created", {
                "record_id": rec.get("id"),
                "record_type": rec.get("type"),
                "label": rec.get("label"),
            })
            if rec.get("type") in {"tool", "skill"}:
                tool_name, arguments = self._parse_record_label(str(rec.get("label", "")))
                self._emit_event(session_id, run_id, "tool.call", {"name": tool_name or "unknown", "arguments": arguments})
                self._emit_event(session_id, run_id, "tool.result", {"name": tool_name or "unknown", "status": "ok"})

        try:
            if app_id == "fault_diagnoses":
                result = self.catalog.agent.run_turn(
                    messages_snapshot,
                    model_profile=model_profile_id,
                    on_trace=stream_trace,
                    on_record=stream_record,
                    on_assistant_message=stream_assistant,
                )
            elif app_id == "log_transform":
                result = self.catalog.log_transform_agent.run_turn(
                    messages_snapshot,
                    model_profile=model_profile_id,
                    on_trace=stream_trace,
                    on_record=stream_record,
                    on_assistant_message=stream_assistant,
                )
            else:
                reply = f"已收到对 {app_id} 的请求：{user_content[:80]}"
                result = {
                    "trace_messages": [],
                    "assistant_messages": [{"content": reply, "model": model_name, "tokens": _estimate_tokens(reply)}],
                    "records": [],
                    "artifacts": [],
                }

            with self._lock:
                session = self.sessions.get(session_id)
                if not session:
                    self._set_run_state(session_id, run_id, "error")
                    self._emit_event(session_id, run_id, "run.error", {"message": "session 已不存在"})
                    return

                # For mock/fallback apps (no callbacks), process messages now
                if app_id not in {"fault_diagnoses", "log_transform"}:
                    for trace_line in result.get("trace_messages", []):
                        trace_text = str(trace_line)
                        message = self._append_assistant_message(
                            session,
                            content=trace_text,
                            kind="log",
                            model=session.model_profile_id,
                            tokens=_estimate_tokens(trace_text),
                        )
                        self._emit_event(session_id, run_id, "message.delta", {"message": self.message_payload(message)})

                    for assistant in result.get("assistant_messages", []):
                        assistant_content = str(assistant.get("content", "") or "").strip()
                        if not assistant_content:
                            continue
                        message = self._append_assistant_message(
                            session,
                            content=assistant_content,
                            kind="text",
                            model=assistant.get("model"),
                            tokens=int(assistant.get("tokens", 0) or _estimate_tokens(assistant_content)),
                        )
                        self._emit_event(session_id, run_id, "message.delta", {"message": self.message_payload(message)})

                    for record in result.get("records", []):
                        session.records.append(record)
                        if record.get("type") in {"tool", "skill"}:
                            tool_name, arguments = self._parse_record_label(str(record.get("label", "")))
                            self._emit_event(session_id, run_id, "tool.call", {"name": tool_name or "unknown", "arguments": arguments})
                            self._emit_event(session_id, run_id, "tool.result", {"name": tool_name or "unknown", "status": "ok"})

                # Process new artifacts (for all app types)
                new_artifacts = []
                for artifact in result.get("artifacts", []):
                    artifact_payload = dict(artifact)
                    artifact_payload["session_id"] = session.id
                    session.artifacts.append(artifact_payload)
                    new_artifacts.append(artifact_payload)

                session.status = "completed"
                session.updated_at = _now()
                self._persist_session(session)

            for artifact_payload in new_artifacts:
                self._emit_event(session_id, run_id, "artifact.created", self.artifact_payload(artifact_payload))

            self._set_run_state(session_id, run_id, "done")
            self._emit_event(session_id, run_id, "run.done", {"status": "completed"})
        except Exception as exc:
            with self._lock:
                session = self.sessions.get(session_id)
                if session:
                    session.status = "failed"
                    session.updated_at = _now()
                    self._persist_session(session)
            self._set_run_state(session_id, run_id, "error")
            self._emit_event(session_id, run_id, "run.error", {"message": str(exc)})

    def open_event_stream(self, user: User, session_id: str, run_id: str | None) -> Iterator[dict[str, Any]]:
        self.get_session(user, session_id)
        target_run_id = run_id
        if not target_run_id:
            target_run_id = self._latest_run_by_session.get(session_id)
        if not target_run_id:
            raise ValueError("该 session 暂无可订阅的运行")

        key = (session_id, target_run_id)
        index = 0
        while True:
            event: dict[str, Any] | None = None
            with self._event_cond:
                events = self._run_events.get(key, [])
                state = self._run_state.get(key)
                if index < len(events):
                    event = events[index]
                    index += 1
                elif state in {"done", "error"}:
                    break
                else:
                    self._event_cond.wait(timeout=1.0)
                    continue
            if event:
                yield event

    def send_message(self, user: User, session_id: str, content: str) -> dict[str, Any]:
        text = content.strip()
        if not text:
            raise ValueError("content 不能为空")

        with self._lock:
            session = self.get_session(user, session_id)
            user_message_id = f"{session_id}_u_{len(session.messages)+1}"
            session.messages.append({"id": user_message_id, "role": "user", "content": text, "kind": "text"})
            session.updated_at = _now()
            session.status = "running"
            run_id = f"run_{uuid.uuid4().hex[:8]}"
            key = (session_id, run_id)
            self._run_events[key] = []
            self._run_state[key] = "running"
            self._latest_run_by_session[session_id] = run_id
            self._emit_event(session_id, run_id, "run.accepted", {"status": "running"})
            self._persist_session(session)

        worker = threading.Thread(
            target=self._execute_run,
            args=(session_id, run_id, text),
            daemon=True,
        )
        worker.start()
        return {"message_id": user_message_id, "run_id": run_id}

    def control(self, user: User, session_id: str, action: str) -> dict[str, Any]:
        session = self.get_session(user, session_id)
        action = action.lower()
        if action in {"stop", "pause"}:
            session.status = "paused"
        elif action == "resume":
            session.status = "running"
        elif action == "cancel":
            session.status = "cancelled"
        elif action == "rerun":
            session.status = "running"
        elif action == "archive":
            session.status = "archived"
        elif action == "activate":
            session.status = "running"
        else:
            raise ValueError(f"不支持的 action: {action}")
        session.updated_at = _now()
        with self._lock:
            self._persist_session(session)
        return {"status": self.ui_status(session.status)}

    def delete_session(self, user: User, session_id: str) -> None:
        with self._lock:
            session = self.get_session(user, session_id)
            del self.sessions[session.id]
            self._delete_session_from_store(session.id)
        self._purge_deleted_model_profiles_if_unused()


STATE = AppState()


class AgentRequestHandler(BaseHTTPRequestHandler):
    server_version = "FaultAssistantAgent/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _set_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._set_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int = 204) -> None:
        self.send_response(status)
        self._set_cors()
        self.end_headers()

    def _send_sse_stream(self, user: User, session_id: str, run_id: str | None) -> None:
        self.send_response(200)
        self._set_cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            for event in STATE.open_event_stream(user, session_id, run_id):
                payload = json.dumps(event, ensure_ascii=False)
                self.wfile.write(f"id: {event.get('id', '')}\n".encode("utf-8"))
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _auth_token(self) -> str:
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header.removeprefix("Bearer ").strip()
        return ""

    def _current_user(self) -> User:
        token = self._auth_token()
        if not token:
            raise PermissionError("未登录")
        return STATE.current_user(token)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_empty()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path)
        try:
            if path.path == "/":
                self._send_json({"service": "fault_assistant_api", "status": "ok"})
                return
            if path.path == "/favicon.ico":
                self._send_empty()
                return
            if path.path == "/api/me":
                user = self._current_user()
                self._send_json({"username": user.username, "role": user.role})
                return
            if path.path == "/api/users":
                user = self._current_user()
                self._send_json({"items": STATE.list_users(user)})
                return
            if path.path == "/api/apps":
                self._send_json({"items": STATE.catalog.list_apps()})
                return
            if path.path == "/api/models/providers":
                self._send_json({"items": [{"id": "gemini"}, {"id": "openai"}, {"id": "aliyun"}]})
                return
            if path.path == "/api/models/profiles":
                self._send_json(STATE.list_models())
                return
            if path.path == "/api/models/gemini/models":
                q = parse_qs(path.query)
                keyword = q.get("q", [""])[0]
                self._send_json({"items": STATE.list_gemini_model_catalog(str(keyword))})
                return
            if path.path == "/api/models/aliyun/models":
                q = parse_qs(path.query)
                keyword = q.get("q", [""])[0]
                profile_id = q.get("profile_id", ["qwen_default"])[0]
                self._send_json({"items": STATE.list_aliyun_model_catalog(str(keyword), str(profile_id))})
                return
            if path.path == "/api/skills":
                self._send_json({"items": STATE.catalog.list_items()})
                return
            if path.path == "/api/sessions":
                user = self._current_user()
                self._send_json(STATE.grouped_sessions(user))
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)$", path.path)
            if m:
                user = self._current_user()
                session = STATE.get_session(user, m.group(1))
                self._send_json(STATE.session_payload(session))
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)/messages", path.path)
            if m:
                user = self._current_user()
                session = STATE.get_session(user, m.group(1))
                self._send_json({"items": [STATE.message_payload(msg) for msg in session.messages]})
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)/records", path.path)
            if m:
                user = self._current_user()
                session = STATE.get_session(user, m.group(1))
                kind = parse_qs(path.query).get("kind", ["all"])[0]
                self._send_json({"items": [STATE.record_payload(record) for record in STATE.list_records(session, kind)]})
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)/events", path.path)
            if m:
                q = parse_qs(path.query)
                token = self._auth_token() or q.get("access_token", [""])[0]
                if not token:
                    raise PermissionError("未登录")
                user = STATE.current_user(str(token))
                run_id = q.get("run_id", [None])[0]
                self._send_sse_stream(user, m.group(1), str(run_id) if run_id else None)
                return
            if path.path == "/api/artifacts":
                user = self._current_user()
                q = parse_qs(path.query)
                raw_items = STATE.list_artifacts(
                    user,
                    session_id=q.get("session_id", [None])[0],
                    artifact_type=q.get("artifact_type", [None])[0],
                )
                self._send_json(
                    {
                        "items": [STATE.artifact_payload(item) for item in raw_items]
                    }
                )
                return
            self._send_json({"message": "Not found"}, status=404)
        except PermissionError as exc:
            self._send_json({"message": str(exc)}, status=401)
        except ValueError as exc:
            self._send_json({"message": str(exc)}, status=400)
        except KeyError as exc:
            self._send_json({"message": f"未找到资源: {exc.args[0]}"}, status=404)
        except Exception as exc:
            self._send_json({"message": str(exc)}, status=500)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path)
        try:
            if path.path == "/api/auth/register":
                body = self._read_json()
                created = STATE.register(str(body.get("username", "")), str(body.get("password", "")))
                self._send_json(created, status=201)
                return
            if path.path == "/api/auth/login":
                body = self._read_json()
                self._send_json(STATE.login(str(body.get("username", "")), str(body.get("password", ""))))
                return
            if path.path == "/api/auth/logout":
                token = self._auth_token()
                if token:
                    STATE.logout(token)
                self._send_empty()
                return
            user = self._current_user()
            if path.path == "/api/me/password":
                body = self._read_json()
                STATE.update_own_password(
                    user,
                    str(body.get("current_password", body.get("old_password", ""))),
                    str(body.get("new_password", "")),
                )
                self._send_empty()
                return
            if path.path == "/api/users":
                body = self._read_json()
                created = STATE.create_user_by_admin(
                    user,
                    str(body.get("username", "")),
                    str(body.get("password", "")),
                    str(body.get("role", "user")),
                )
                self._send_json(created, status=201)
                return
            m = re.fullmatch(r"/api/users/([^/]+)/password$", path.path)
            if m:
                body = self._read_json()
                STATE.reset_user_password_by_admin(
                    user,
                    m.group(1),
                    str(body.get("new_password", "")),
                )
                self._send_empty()
                return
            if path.path == "/api/sessions":
                body = self._read_json()
                session = STATE.create_session(
                    user,
                    str(body.get("app_id", "")),
                    body.get("model_profile_id"),
                    body.get("title"),
                )
                self._send_json(
                    {
                        "session_id": session.id,
                        "title": session.title,
                        "status": STATE.ui_status(session.status),
                        "updated_at": session.updated_at,
                        "model_profile_id": session.model_profile_id,
                        "model_name": session.model_name,
                    },
                    status=201,
                )
                return
            if path.path == "/api/models/profiles":
                if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
                    raise PermissionError("无权限")
                body = self._read_json()
                created = create_profile(
                    str(body.get("profile_id", "")),
                    provider=str(body.get("provider", "")),
                    model_name=str(body.get("model_name", "")),
                    base_url=body.get("base_url"),
                    temperature=body.get("temperature"),
                    top_p=body.get("top_p") if body.get("top_p") is not None else body.get("top_n"),
                    top_k=body.get("top_k"),
                    max_output_tokens=body.get("max_output_tokens"),
                )
                self._send_json(
                    {
                        "profile_id": created["profile_id"],
                        "provider": created["profile"].get("provider"),
                        "model_name": created["profile"].get("model"),
                        "base_url": created["profile"].get("base_url"),
                        "temperature": created["profile"].get("temperature"),
                        "top_p": created["profile"].get("top_p"),
                        "top_k": created["profile"].get("top_k"),
                        "max_output_tokens": created["profile"].get("max_output_tokens"),
                    },
                    status=201,
                )
                return
            m = re.fullmatch(r"/api/models/profiles/([^/]+)/default$", path.path)
            if m:
                if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
                    raise PermissionError("无权限")
                set_default_profile(m.group(1))
                self._send_empty()
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)/messages", path.path)
            if m:
                body = self._read_json()
                self._send_json(STATE.send_message(user, m.group(1), str(body.get("content", ""))), status=201)
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)/control", path.path)
            if m:
                body = self._read_json()
                self._send_json(STATE.control(user, m.group(1), str(body.get("action", ""))))
                return
            self._send_json({"message": "Not found"}, status=404)
        except PermissionError as exc:
            self._send_json({"message": str(exc)}, status=401)
        except ValueError as exc:
            self._send_json({"message": str(exc)}, status=400)
        except KeyError as exc:
            self._send_json({"message": f"未找到资源: {exc.args[0]}"}, status=404)
        except Exception as exc:
            self._send_json({"message": str(exc)}, status=500)

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlparse(self.path)
        try:
            user = self._current_user()
            m = re.fullmatch(r"/api/models/profiles/([^/]+)$", path.path)
            if m:
                if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
                    raise PermissionError("无权限")
                body = self._read_json()
                updated = update_profile(
                    m.group(1),
                    provider=body.get("provider"),
                    model_name=body.get("model_name"),
                    base_url=body.get("base_url"),
                    temperature=body.get("temperature"),
                    top_p=body.get("top_p") if body.get("top_p") is not None else body.get("top_n"),
                    top_k=body.get("top_k"),
                    max_output_tokens=body.get("max_output_tokens"),
                )
                self._send_json(
                    {
                        "profile_id": updated["profile_id"],
                        "provider": updated["profile"].get("provider"),
                        "model_name": updated["profile"].get("model"),
                        "base_url": updated["profile"].get("base_url"),
                        "temperature": updated["profile"].get("temperature"),
                        "top_p": updated["profile"].get("top_p"),
                        "top_k": updated["profile"].get("top_k"),
                        "max_output_tokens": updated["profile"].get("max_output_tokens"),
                    }
                )
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)/archive", path.path)
            if m:
                self._send_json(STATE.control(user, m.group(1), "archive"))
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)/activate", path.path)
            if m:
                self._send_json(STATE.control(user, m.group(1), "activate"))
                return
            m = re.fullmatch(r"/api/users/([^/]+)$", path.path)
            if m:
                body = self._read_json()
                updated_user = STATE.update_user(
                    user,
                    m.group(1),
                    role=body.get("role"),
                    is_disabled=body.get("is_disabled"),
                )
                self._send_json(updated_user)
                return
            if path.path.startswith("/api/skills/"):
                if user.role not in {ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_USER}:
                    raise PermissionError("无权限")
                skill_id = path.path.rsplit("/", 1)[-1]
                body = self._read_json()
                STATE.catalog.update_markdown(skill_id, str(body.get("markdown", "")))
                self._send_json({"status": "ok"})
                return
            self._send_json({"message": "Not found"}, status=404)
        except PermissionError as exc:
            self._send_json({"message": str(exc)}, status=401)
        except ValueError as exc:
            self._send_json({"message": str(exc)}, status=400)
        except KeyError as exc:
            self._send_json({"message": f"未找到资源: {exc.args[0]}"}, status=404)
        except Exception as exc:
            self._send_json({"message": str(exc)}, status=500)

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path)
        try:
            user = self._current_user()
            m = re.fullmatch(r"/api/sessions/([^/]+)$", path.path)
            if m:
                STATE.delete_session(user, m.group(1))
                self._send_empty()
                return
            m = re.fullmatch(r"/api/models/profiles/([^/]+)$", path.path)
            if m:
                if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
                    raise PermissionError("无权限")
                delete_profile(m.group(1))
                STATE._purge_deleted_model_profiles_if_unused()
                self._send_empty()
                return
            m = re.fullmatch(r"/api/users/([^/]+)$", path.path)
            if m:
                STATE.delete_user(user, m.group(1))
                self._send_empty()
                return
            self._send_json({"message": "Not found"}, status=404)
        except PermissionError as exc:
            self._send_json({"message": str(exc)}, status=401)
        except ValueError as exc:
            self._send_json({"message": str(exc)}, status=400)
        except KeyError as exc:
            self._send_json({"message": f"未找到资源: {exc.args[0]}"}, status=404)
        except Exception as exc:
            self._send_json({"message": str(exc)}, status=500)


def main() -> None:
    host = os.getenv("AGENT_API_HOST", "127.0.0.1")
    port = int(os.getenv("AGENT_API_PORT", "8001"))
    server = ThreadingHTTPServer((host, port), AgentRequestHandler)
    print(f"Agent API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
