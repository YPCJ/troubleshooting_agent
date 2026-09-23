from __future__ import annotations

import json
import hashlib
import hmac
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Any, Iterator
from urllib.parse import parse_qs, quote, urlparse

PROJECT_ROOT = next((p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents] if (p / ".env").exists()), Path(__file__).resolve().parent.parent)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.config import (
    create_profile,
    delete_profile,
    generation_style_for_sampling_mode,
    hard_delete_profile,
    infer_output_mode,
    infer_sampling_mode,
    load_profiles,
    set_default_profile,
    update_profile,
)
from llm.providers import create_provider, registered_provider_names
from llm.connections import create_connection, list_connections
from llm.model_management import discover_models, probe_model, read_capabilities

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

ALIYUN_TOKEN_PLAN_BASE_URL = (
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)
ALIYUN_TOKEN_PLAN_API_KEY_ENVS = [
    "TOKEN_PLAN_API_KEY",
    "BAILIAN_TOKEN_PLAN_API_KEY",
    "api_key",
    "OPENAI_API_KEY",
    "DASHSCOPE_API_KEY",
]

ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
MANAGEABLE_ROLES = {ROLE_ADMIN, ROLE_USER}
SUPER_ADMIN_USERNAME = "YPCJ"
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "20201214")
SESSION_SCHEMA_VERSION = 1


def _model_profile_api_item(profile_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    sampling_mode = infer_sampling_mode(profile)
    return {
        "profile_id": profile_id,
        "provider": profile.get("provider"),
        "model_name": profile.get("model"),
        "base_url": profile.get("base_url"),
        "sampling_mode": sampling_mode,
        "output_mode": infer_output_mode(profile),
        "generation_style": generation_style_for_sampling_mode(sampling_mode),
        "verbosity": profile.get("verbosity"),
        "temperature": profile.get("temperature"),
        "top_p": profile.get("top_p") if profile.get("top_p") is not None else profile.get("top_n"),
        "top_k": profile.get("top_k"),
        "max_output_tokens": profile.get("max_output_tokens"),
    }


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
        self.sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._tool_state_lock = threading.RLock()
        self._event_cond = threading.Condition(self._lock)
        self._run_events: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._run_state: dict[tuple[str, str], str] = {}
        self._latest_run_by_session: dict[str, str] = {}
        self._sbc_selection_claims: set[str] = set()
        self._tool_enabled: dict[str, bool] = {}
        self._model_capabilities_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
        self.auth_db_path = _auth_db_path()
        self.session_db_path = _session_db_path()
        self._init_auth_store()
        self._init_session_store()
        self.catalog = ServiceCatalog(enabled_checker=self.is_tool_enabled)
        self._bootstrap_tool_states()
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
                    SELECT position, payload_json FROM session_records
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
                        payload["id"] = self._session_record_id(int(record_row["position"]))
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_states (
                    tool_name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
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

    def _bootstrap_tool_states(self) -> None:
        tool_names = self.catalog.list_tool_names()
        now = _now()
        with self._db() as conn:
            for tool_name in tool_names:
                conn.execute(
                    "INSERT INTO tool_states (tool_name, enabled, updated_at) VALUES (?, 1, ?) "
                    "ON CONFLICT(tool_name) DO NOTHING",
                    (tool_name, now),
                )
            rows = conn.execute("SELECT tool_name, enabled FROM tool_states").fetchall()
        with self._tool_state_lock:
            self._tool_enabled = {
                str(row["tool_name"]): bool(int(row["enabled"]))
                for row in rows
                if str(row["tool_name"]) in tool_names
            }

    def is_tool_enabled(self, tool_name: str) -> bool:
        clean_name = tool_name.strip()
        with self._tool_state_lock:
            value = self._tool_enabled.get(clean_name)
        return True if value is None else bool(value)

    def list_tools(self) -> list[dict[str, Any]]:
        return self.catalog.list_tools()

    def update_tool_enabled(self, requester: User, tool_name: str, enabled: bool) -> dict[str, Any]:
        if requester.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
            raise PermissionError("无权限")
        clean_name = tool_name.strip()
        known_names = set(self.catalog.list_tool_names())
        if clean_name not in known_names:
            raise KeyError(clean_name)
        now = _now()
        with self._db() as conn:
            conn.execute(
                "INSERT INTO tool_states (tool_name, enabled, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(tool_name) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at",
                (clean_name, 1 if enabled else 0, now),
            )
        with self._tool_state_lock:
            self._tool_enabled[clean_name] = bool(enabled)
        for item in self.catalog.list_tools():
            if str(item.get("tool_name")) == clean_name:
                return item
        raise KeyError(clean_name)

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
        latest_run_id = self._latest_run_by_session.get(session.id)
        active_run_id = (
            latest_run_id
            if latest_run_id
            and self._run_state.get((session.id, latest_run_id)) == "running"
            else None
        )
        return {
            "session_id": session.id,
            "title": session.title,
            "status": self.ui_status(session.status),
            "run_status": session.status,
            "active_run_id": active_run_id,
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
            "round_summary": message.get("round_summary"),
        }

    @staticmethod
    def _apply_round_summary(messages: list[dict[str, Any]], start_index: int, summary: dict[str, Any] | None) -> dict[str, Any] | None:
        if not summary:
            return None
        for idx in range(len(messages) - 1, start_index - 1, -1):
            message = messages[idx]
            if message.get("role") == "assistant" and message.get("kind") == "text" and str(message.get("content", "")).strip():
                message["round_summary"] = summary
                return message
        return None

    def record_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        source_kind, source_name, source_path = self._record_source(record)
        return {
            "record_id": record.get("id"),
            "record_type": record.get("type"),
            "label": record.get("label", ""),
            "source_kind": source_kind or None,
            "source_name": source_name or None,
            "source_path": source_path or None,
        }

    @staticmethod
    def _session_record_id(position: int) -> str:
        return f"rec_{position:06d}"

    def _append_session_record(self, session: Session, record: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(record)
        normalized["id"] = self._session_record_id(len(session.records) + 1)
        session.records.append(normalized)
        return normalized

    def _record_source(self, record: dict[str, Any]) -> tuple[str, str, str]:
        source_kind = str(record.get("source_kind") or "")
        source_name = str(record.get("source_name") or "")
        source_path = str(record.get("source_path") or "")
        if source_kind in {"file", "skill"} and source_path:
            return source_kind, source_name, source_path

        tool_name, arguments = self._parse_record_label(str(record.get("label", "")))
        if tool_name in {"read_file", "write_file", "edit_file"}:
            source_path = str(arguments.get("path", "")).strip()
            return ("file", Path(source_path).name or source_path, source_path) if source_path else ("", "", "")
        if tool_name == "load_skills":
            skill_name = str(arguments.get("name", "")).strip()
            skill_path = PROJECT_ROOT / "skills" / skill_name / "SKILL.md"
            if skill_name and skill_path.is_file():
                return "skill", skill_name, str(skill_path)
        return "", "", ""

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

    def artifact_file(self, user: User, session_id: str, artifact_id: str) -> Path:
        session = self.get_session(user, session_id)
        artifact = next(
            (
                item
                for item in session.artifacts
                if str(item.get("id")) == artifact_id
            ),
            None,
        )
        if not artifact:
            raise KeyError(artifact_id)
        resolved = self._safe_workspace_path(str(artifact.get("path", "")))
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        return resolved

    def list_models(self) -> dict[str, Any]:
        profiles = load_profiles(include_deleted=False)
        items = []
        for profile_id, profile in profiles["profiles"].items():
            items.append(_model_profile_api_item(profile_id, profile))
        return {"items": items, "default_profile": profiles["default_profile"]}

    def list_provider_model_catalog(
        self,
        provider_name: str,
        query: str = "",
        profile_id: str | None = None,
    ) -> list[str]:
        """Discover models through the same provider registry used for chat calls."""
        provider_id = provider_name.strip().lower()
        profiles = load_profiles(include_deleted=False).get("profiles", {})
        profile: dict[str, Any] | None = None
        if profile_id:
            candidate = profiles.get(profile_id)
            if not isinstance(candidate, dict):
                raise ValueError(f"Unknown model profile: {profile_id}")
            candidate_provider = str(candidate.get("provider", "")).strip().lower()
            if candidate_provider != provider_id:
                raise ValueError(
                    f"Profile '{profile_id}' belongs to provider '{candidate_provider}', not '{provider_id}'"
                )
            profile = dict(candidate)
        elif provider_id == "aliyun":
            # The model-management catalog for Aliyun reflects the user's
            # Token Plan subscription, not the generic DashScope catalog.
            profile = {
                "provider": "aliyun",
                "base_url": ALIYUN_TOKEN_PLAN_BASE_URL,
                "api_key_envs": ALIYUN_TOKEN_PLAN_API_KEY_ENVS,
            }
        else:
            for candidate in profiles.values():
                if (
                    isinstance(candidate, dict)
                    and str(candidate.get("provider", "")).strip().lower() == provider_id
                ):
                    profile = dict(candidate)
                    break
        profile = profile or {"provider": provider_id}
        try:
            return discover_models(create_provider(provider_id, profile), query)
        except Exception as exc:
            raise RuntimeError(
                f"查询 provider '{provider_id}' 的实时模型目录失败：{exc}"
            ) from exc

    def model_capabilities(
        self,
        provider_name: str,
        model_name: str,
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        provider_id = provider_name.strip().lower()
        model = model_name.strip()
        profile: dict[str, Any] = {"provider": provider_id, "model": model}
        if profile_id:
            profiles = load_profiles(include_deleted=False).get("profiles", {})
            candidate = profiles.get(profile_id)
            if not isinstance(candidate, dict):
                raise ValueError(f"Unknown model profile: {profile_id}")
            profile = dict(candidate)
            provider_id = str(profile.get("provider") or "").strip().lower()
            model = str(profile.get("model") or "").strip()
        if not provider_id or not model:
            raise ValueError("provider 和 model_name 不能为空")
        cache_key = (provider_id, model, profile_id or "")
        cached = self._model_capabilities_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 21600:
            return dict(cached[1])
        provider = create_provider(provider_id, profile)
        result = read_capabilities(provider, provider_id, model)
        self._model_capabilities_cache[cache_key] = (time.monotonic(), result)
        return dict(result)

    def test_model_connection(
        self,
        *,
        profile_id: str | None = None,
        provider_name: str = "",
        model_name: str = "",
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Verify an exact model entry with a minimal real inference call."""
        profile: dict[str, Any]
        if profile_id:
            profiles = load_profiles(include_deleted=False).get("profiles", {})
            candidate = profiles.get(profile_id)
            if not isinstance(candidate, dict):
                raise ValueError(f"Unknown model profile: {profile_id}")
            profile = dict(candidate)
        else:
            provider_id = provider_name.strip().lower()
            model = model_name.strip()
            if not provider_id:
                raise ValueError("provider 不能为空")
            if not model:
                raise ValueError("model_name 不能为空")
            profile = {"provider": provider_id, "model": model}
            if base_url and base_url.strip():
                profile["base_url"] = base_url.strip()
        provider_id = str(profile.get("provider") or "").strip().lower()
        model = str(profile.get("model") or "").strip()
        if not provider_id or not model:
            raise ValueError("模型入口缺少 provider 或 model_name")
        provider = create_provider(provider_id, profile)
        return probe_model(provider, provider_id, model)

    # Compatibility wrappers for existing API consumers.
    def list_aliyun_model_catalog(self, query: str = "", profile_id: str = "qwen_default") -> list[str]:
        try:
            return self.list_provider_model_catalog("aliyun", query, profile_id)
        except Exception:
            keyword = query.strip().lower()
            models = sorted(set(FALLBACK_ALIYUN_MODELS))
            return [model for model in models if not keyword or keyword in model.lower()]

    def list_aliyun_token_plan_model_catalog(self, query: str = "") -> list[str]:
        return self.list_provider_model_catalog("aliyun", query)

    def list_gemini_model_catalog(self, query: str = "") -> list[str]:
        return self.list_provider_model_catalog("gemini", query)

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

    @staticmethod
    def _safe_workspace_path(raw_path: str) -> Path:
        candidate = Path(raw_path)
        resolved = candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)
        resolved = resolved.resolve()
        if not resolved.is_relative_to(PROJECT_ROOT):
            raise ValueError(f"Path escapes workspace: {raw_path}")
        return resolved

    @staticmethod
    def _read_text_preview(path: Path) -> str:
        for enc in ("utf-8", "gbk", "gb2312", "gb18030"):
            try:
                return path.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="ignore")

    def _execute_run(
        self,
        session_id: str,
        run_id: str,
        user_content: str,
        selected_event_id: str | None = None,
        holds_selection_claim: bool = False,
    ) -> None:
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                if selected_event_id or holds_selection_claim:
                    self._sbc_selection_claims.discard(session_id)
                self._set_run_state(session_id, run_id, "error")
                self._emit_event(session_id, run_id, "run.error", {"message": "session 已不存在"})
                return
            app_id = session.app_id
            model_profile_id = session.model_profile_id
            model_name = session.model_name
            messages_snapshot = list(session.messages)
            run_start_index = len(session.messages)

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
                persisted_record = self._append_session_record(sess, rec)
                self._persist_session(sess)
            self._emit_event(session_id, run_id, "record.created", self.record_payload(persisted_record))
            if persisted_record.get("type") in {"tool", "skill"}:
                tool_name, arguments = self._parse_record_label(str(persisted_record.get("label", "")))
                self._emit_event(
                    session_id,
                    run_id,
                    "tool.call",
                    {"name": tool_name or "unknown", "arguments": arguments, **self.record_payload(persisted_record)},
                )
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
            elif app_id == "sbc_network_troubleshooting":
                result = self.catalog.sbc_network_troubleshooting_agent.run_turn(
                    messages_snapshot,
                    model_profile=model_profile_id,
                    on_trace=stream_trace,
                    on_record=stream_record,
                    on_assistant_message=stream_assistant,
                    session_id=session_id,
                    selected_event_id=selected_event_id,
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
                if app_id not in {
                    "fault_diagnoses",
                    "sbc_network_troubleshooting",
                    "log_transform",
                }:
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
                        persisted_record = self._append_session_record(session, record)
                        if persisted_record.get("type") in {"tool", "skill"}:
                            tool_name, arguments = self._parse_record_label(str(persisted_record.get("label", "")))
                            self._emit_event(
                                session_id,
                                run_id,
                                "tool.call",
                                {"name": tool_name or "unknown", "arguments": arguments, **self.record_payload(persisted_record)},
                            )
                            self._emit_event(session_id, run_id, "tool.result", {"name": tool_name or "unknown", "status": "ok"})

                # Process new artifacts (for all app types)
                new_artifacts = []
                for artifact in result.get("artifacts", []):
                    artifact_payload = dict(artifact)
                    artifact_payload["session_id"] = session.id
                    session.artifacts.append(artifact_payload)
                    new_artifacts.append(artifact_payload)

                model_calls = int(result.get("model_calls", 0) or 0)
                total_tokens = int(((result.get("usage") or {}).get("total_tokens")) or 0)
                summary_payload = {"model_calls": model_calls, "total_tokens": total_tokens} if model_calls > 0 else None
                summary_message = self._apply_round_summary(session.messages, run_start_index, summary_payload)

                waiting_for_selection = (
                    app_id == "sbc_network_troubleshooting"
                    and result.get("status") == "awaiting_selection"
                    and isinstance(result.get("selection_request"), dict)
                )
                session.status = "awaiting_input" if waiting_for_selection else "completed"
                session.updated_at = _now()
                self._persist_session(session)

            if summary_message:
                self._emit_event(session_id, run_id, "message.delta", {"message": self.message_payload(summary_message)})
            for artifact_payload in new_artifacts:
                self._emit_event(session_id, run_id, "artifact.created", self.artifact_payload(artifact_payload))
            if waiting_for_selection:
                self._emit_event(
                    session_id,
                    run_id,
                    "sbc.selection.requested",
                    dict(result["selection_request"]),
                )

            self._set_run_state(session_id, run_id, "done")
            self._emit_event(
                session_id,
                run_id,
                "run.done",
                {"status": "awaiting_input" if waiting_for_selection else "completed"},
            )
        except Exception as exc:
            error_text = str(exc).strip() or exc.__class__.__name__
            if len(error_text) > 2000:
                error_text = f"{error_text[:2000]}…"
            error_message = f"执行失败：{error_text}"
            error_payload: dict[str, Any] = {"message": error_message}
            with self._lock:
                session = self.sessions.get(session_id)
                if session:
                    message = self._append_assistant_message(
                        session,
                        content=error_message,
                        kind="error",
                        model=session.model_profile_id,
                        tokens=_estimate_tokens(error_message),
                    )
                    error_payload["message_id"] = message["id"]
                    self._emit_event(
                        session_id,
                        run_id,
                        "message.delta",
                        {"message": self.message_payload(message)},
                    )
                    session.status = "failed"
                    session.updated_at = _now()
                    self._persist_session(session)
            self._set_run_state(session_id, run_id, "error")
            self._emit_event(session_id, run_id, "run.error", error_payload)
        finally:
            if selected_event_id or holds_selection_claim:
                with self._lock:
                    self._sbc_selection_claims.discard(session_id)

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

        claimed = False
        try:
            with self._lock:
                session = self.get_session(user, session_id)
                # A typed reply can also resolve a pending SBC event selection, so it
                # must take the same claim as the button path to avoid two threads
                # resuming one LangGraph interrupt.
                needs_claim = (
                    session.app_id == "sbc_network_troubleshooting"
                    and self.get_sbc_event_selection(user, session_id) is not None
                )
                if needs_claim:
                    if session_id in self._sbc_selection_claims:
                        # Held by an in-flight run; reject without touching it.
                        raise ValueError("当前中断事件已经开始排查，请勿重复提交")
                    self._sbc_selection_claims.add(session_id)
                    claimed = True
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
                args=(session_id, run_id, text, None, claimed),
                daemon=True,
            )
            worker.start()
        except Exception:
            # Only _execute_run releases the claim; if it never starts, drop the
            # claim this call took so the session does not stay blocked forever.
            if claimed:
                with self._lock:
                    self._sbc_selection_claims.discard(session_id)
            raise
        return {
            "message_id": user_message_id,
            "run_id": run_id,
            "status": "running",
        }

    def get_sbc_event_selection(
        self,
        user: User,
        session_id: str,
    ) -> dict[str, Any] | None:
        session = self.get_session(user, session_id)
        if session.app_id != "sbc_network_troubleshooting":
            return None
        return self.catalog.sbc_network_troubleshooting_agent.pending_selection(
            session_id,
        )

    def select_sbc_event(
        self,
        user: User,
        session_id: str,
        event_id: str,
    ) -> dict[str, Any]:
        selected_event_id = event_id.strip()
        if not selected_event_id:
            raise ValueError("event_id 不能为空")
        claimed = False
        try:
            with self._lock:
                session = self.get_session(user, session_id)
                if session.app_id != "sbc_network_troubleshooting":
                    raise ValueError("当前Session不是SBC故障排查会话")
                if session_id in self._sbc_selection_claims:
                    raise ValueError("当前中断事件已经开始排查，请勿重复提交")
                selection = self.get_sbc_event_selection(user, session_id)
                if selection is None:
                    raise ValueError("当前Session没有等待选择的中断事件")
                valid_ids = {
                    str(item.get("event_id", ""))
                    for item in selection.get("candidates", [])
                }
                if selected_event_id not in valid_ids:
                    raise ValueError("所选中断事件不属于当前Session的候选事件")
                self._sbc_selection_claims.add(session_id)
                claimed = True
                content = f"选择中断事件 `{selected_event_id}` 继续排查"
                user_message_id = f"{session_id}_u_{len(session.messages)+1}"
                session.messages.append(
                    {
                        "id": user_message_id,
                        "role": "user",
                        "content": content,
                        "kind": "text",
                    }
                )
                session.updated_at = _now()
                session.status = "running"
                run_id = f"run_{uuid.uuid4().hex[:8]}"
                key = (session_id, run_id)
                self._run_events[key] = []
                self._run_state[key] = "running"
                self._latest_run_by_session[session_id] = run_id
                self._emit_event(
                    session_id,
                    run_id,
                    "run.accepted",
                    {"status": "running"},
                )
                self._emit_event(
                    session_id,
                    run_id,
                    "sbc.selection.resumed",
                    {"event_id": selected_event_id},
                )
                self._persist_session(session)

            worker = threading.Thread(
                target=self._execute_run,
                args=(session_id, run_id, content, selected_event_id),
                daemon=True,
            )
            worker.start()
        except Exception:
            # Only _execute_run releases the claim; if it never starts, drop it
            # here so the session does not stay blocked forever.
            if claimed:
                with self._lock:
                    self._sbc_selection_claims.discard(session_id)
            raise
        return {
            "message_id": user_message_id,
            "run_id": run_id,
            "status": "running",
        }

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

    def preview_record(self, user: User, session_id: str, record_id: str) -> dict[str, Any]:
        session = self.get_session(user, session_id)
        record = next((item for item in session.records if str(item.get("id")) == record_id), None)
        if not record:
            raise KeyError(record_id)
        source_kind, source_name, source_path = self._record_source(record)
        if source_kind not in {"file", "skill"} or not source_path:
            raise ValueError("该记录没有可预览内容")
        resolved = self._safe_workspace_path(source_path)
        content = self._read_text_preview(resolved)
        content_kind = "markdown" if source_kind == "skill" or resolved.suffix.lower() in {".md", ".markdown"} else "text"
        return {
            "record_id": record_id,
            "source_kind": source_kind,
            "source_name": source_name or resolved.name,
            "source_path": source_path,
            "title": source_name or resolved.name,
            "content": content,
            "content_kind": content_kind,
        }

    def delete_session(self, user: User, session_id: str) -> None:
        with self._lock:
            session = self.get_session(user, session_id)
            del self.sessions[session.id]
            self._sbc_selection_claims.discard(session.id)
            self._delete_session_from_store(session.id)
        self._purge_deleted_model_profiles_if_unused()


def _validate_deployment_credentials() -> None:
    host = os.getenv("AGENT_API_HOST", "127.0.0.1")
    if host in {"127.0.0.1", "localhost", "::1"} or os.getenv("AGENT_SERVE_FRONTEND") != "1":
        return
    if not os.getenv("ADMIN_PASSWORD") or not os.getenv("SUPER_ADMIN_PASSWORD"):
        raise RuntimeError("LAN deployment requires ADMIN_PASSWORD and SUPER_ADMIN_PASSWORD")
    if os.getenv("ADMIN_PASSWORD") == "20210426" or SUPER_ADMIN_PASSWORD == "20201214":
        raise RuntimeError("LAN deployment requires non-default admin passwords")
    if os.getenv("AGENT_APP_MODE") == "sbc":
        for name in ("INTRANET_LLM_BASE_URL", "INTRANET_LLM_MODEL", "INTRANET_LLM_API_KEY"):
            if not os.getenv(name):
                raise RuntimeError(f"LAN deployment requires {name}")


_validate_deployment_credentials()
STATE = AppState()


class AgentRequestHandler(BaseHTTPRequestHandler):
    server_version = "TroubleshootingAgent/0.1"

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

    def _send_file(self, path: Path) -> None:
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or path.suffix.lower() in {".md", ".markdown", ".json"}:
            content_type = f"{content_type}; charset=utf-8"
        self.send_response(200)
        self._set_cors()
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition",
            f"inline; filename*=UTF-8''{quote(path.name)}",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_frontend(self, request_path: str) -> bool:
        if os.getenv("AGENT_SERVE_FRONTEND") != "1" or request_path.startswith("/api/"):
            return False
        dist = PROJECT_ROOT / "frontend" / "dist"
        if request_path == "/":
            target = dist / "index.html"
        else:
            target = (dist / request_path.lstrip("/")).resolve()
            if not target.is_relative_to(dist.resolve()):
                self._send_json({"message": "Not found"}, status=404)
                return True
            if not target.is_file() and "." not in Path(request_path).name:
                target = dist / "index.html"
        if target.is_file():
            self._send_file(target)
        else:
            self._send_json({"message": "Not found"}, status=404)
        return True

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
            if self._send_frontend(path.path):
                return
            if path.path == "/":
                self._send_json({"service": "troubleshooting_agent_api", "status": "ok"})
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
                _ = self._current_user()
                items = list_connections()
                known = {item["id"] for item in items}
                items.extend(
                    {"id": name, "display_name": name, "protocol": "plugin", "builtin": True}
                    for name in registered_provider_names() if name not in known
                )
                self._send_json({"items": items})
                return
            if path.path == "/api/models/profiles":
                self._send_json(STATE.list_models())
                return
            if path.path == "/api/models/gemini/models":
                q = parse_qs(path.query)
                keyword = q.get("q", [""])[0]
                self._send_json({"items": STATE.list_gemini_model_catalog(str(keyword))})
                return
            if path.path == "/api/models/catalog":
                q = parse_qs(path.query)
                provider_name = str(q.get("provider", [""])[0])
                if not provider_name:
                    raise ValueError("provider 不能为空")
                keyword = str(q.get("q", [""])[0])
                profile_id = str(q.get("profile_id", [""])[0]).strip() or None
                self._send_json(
                    {
                        "items": STATE.list_provider_model_catalog(
                            provider_name,
                            keyword,
                            profile_id,
                        )
                    }
                )
                return
            if path.path == "/api/models/capabilities":
                _ = self._current_user()
                q = parse_qs(path.query)
                self._send_json(
                    STATE.model_capabilities(
                        str(q.get("provider", [""])[0]),
                        str(q.get("model_name", [""])[0]),
                        str(q.get("profile_id", [""])[0]).strip() or None,
                    )
                )
                return
            if path.path == "/api/models/aliyun/models":
                q = parse_qs(path.query)
                keyword = q.get("q", [""])[0]
                profile_id = q.get("profile_id", ["qwen_default"])[0]
                self._send_json({"items": STATE.list_aliyun_model_catalog(str(keyword), str(profile_id))})
                return
            if path.path == "/api/models/aliyun/token-plan/models":
                q = parse_qs(path.query)
                keyword = q.get("q", [""])[0]
                self._send_json(
                    {"items": STATE.list_aliyun_token_plan_model_catalog(str(keyword))}
                )
                return
            if path.path == "/api/skills":
                self._send_json({"items": STATE.catalog.list_items()})
                return
            if path.path == "/api/tools":
                _ = self._current_user()
                self._send_json({"items": STATE.list_tools()})
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
            m = re.fullmatch(
                r"/api/sessions/([^/]+)/sbc-event-selection",
                path.path,
            )
            if m:
                user = self._current_user()
                self._send_json(
                    {
                        "selection": STATE.get_sbc_event_selection(
                            user,
                            m.group(1),
                        )
                    }
                )
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)/records", path.path)
            if m:
                user = self._current_user()
                session = STATE.get_session(user, m.group(1))
                kind = parse_qs(path.query).get("kind", ["all"])[0]
                self._send_json({"items": [STATE.record_payload(record) for record in STATE.list_records(session, kind)]})
                return
            m = re.fullmatch(r"/api/sessions/([^/]+)/preview", path.path)
            if m:
                user = self._current_user()
                q = parse_qs(path.query)
                record_id = q.get("record_id", [""])[0]
                if not record_id:
                    raise ValueError("record_id 不能为空")
                self._send_json(STATE.preview_record(user, m.group(1), record_id))
                return
            m = re.fullmatch(
                r"/api/sessions/([^/]+)/artifacts/([^/]+)/content",
                path.path,
            )
            if m:
                user = self._current_user()
                self._send_file(STATE.artifact_file(user, m.group(1), m.group(2)))
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
            if path.path == "/api/models/providers":
                if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
                    raise PermissionError("无权限")
                body = self._read_json()
                self._send_json(
                    create_connection(
                        str(body.get("id") or ""),
                        str(body.get("display_name") or ""),
                        str(body.get("protocol") or ""),
                        str(body.get("base_url") or ""),
                        str(body.get("api_key_env") or ""),
                    ),
                    status=201,
                )
                return
            if path.path == "/api/models/test-connection":
                if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
                    raise PermissionError("无权限")
                body = self._read_json()
                self._send_json(
                    STATE.test_model_connection(
                        profile_id=str(body.get("profile_id") or "").strip() or None,
                        provider_name=str(body.get("provider") or ""),
                        model_name=str(body.get("model_name") or ""),
                        base_url=body.get("base_url"),
                    )
                )
                return
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
                    sampling_mode=body.get("sampling_mode"),
                    output_mode=body.get("output_mode"),
                    generation_style=body.get("generation_style"),
                    verbosity=body.get("verbosity"),
                    temperature=body.get("temperature"),
                    top_p=body.get("top_p") if body.get("top_p") is not None else body.get("top_n"),
                    top_k=body.get("top_k"),
                    max_output_tokens=body.get("max_output_tokens"),
                )
                self._send_json(
                    _model_profile_api_item(created["profile_id"], created["profile"]),
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
            m = re.fullmatch(
                r"/api/sessions/([^/]+)/sbc-event-selection",
                path.path,
            )
            if m:
                body = self._read_json()
                self._send_json(
                    STATE.select_sbc_event(
                        user,
                        m.group(1),
                        str(body.get("event_id", "")),
                    ),
                    status=201,
                )
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
                generation_kwargs: dict[str, Any] = {}
                for request_key in ("sampling_mode", "output_mode", "generation_style", "verbosity"):
                    if request_key in body:
                        generation_kwargs[request_key] = body.get(request_key)
                updated = update_profile(
                    m.group(1),
                    provider=body.get("provider"),
                    model_name=body.get("model_name"),
                    base_url=body.get("base_url"),
                    temperature=body.get("temperature"),
                    top_p=body.get("top_p") if body.get("top_p") is not None else body.get("top_n"),
                    top_k=body.get("top_k"),
                    max_output_tokens=body.get("max_output_tokens"),
                    clear_generation_overrides=body.get("generation_mode") == "provider_default",
                    replace_generation_overrides=body.get("generation_mode") == "custom",
                    **generation_kwargs,
                )
                self._send_json(_model_profile_api_item(updated["profile_id"], updated["profile"]))
                return
            m = re.fullmatch(r"/api/tools/([^/]+)$", path.path)
            if m:
                body = self._read_json()
                enabled_value = body.get("enabled")
                if not isinstance(enabled_value, bool):
                    raise ValueError("enabled 字段不能为空")
                updated_tool = STATE.update_tool_enabled(
                    user,
                    m.group(1),
                    enabled_value,
                )
                self._send_json(updated_tool)
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
