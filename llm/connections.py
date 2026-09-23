"""User-defined model service connections.

Connections describe transport and credentials; model profiles describe one
model and its generation settings. API keys stay in environment variables.
"""

from __future__ import annotations

import re
import os
import sqlite3
from contextlib import closing
from typing import Any
from urllib.parse import urlparse

from .config import _profiles_db_path

SUPPORTED_PROTOCOLS = {"openai_chat"}
BUILTIN_PROVIDER_IDS = {"aliyun", "gemini", "openai"}


def _database() -> sqlite3.Connection:
    path = _profiles_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_connections (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            base_url TEXT NOT NULL,
            api_key_env TEXT NOT NULL
        )
        """
    )
    return connection


def list_connections() -> list[dict[str, Any]]:
    builtins = [
        {"id": "aliyun", "display_name": "阿里云百炼", "protocol": "openai_chat", "builtin": True},
        {"id": "gemini", "display_name": "Google Gemini", "protocol": "gemini_native", "builtin": True},
        {"id": "openai", "display_name": "OpenAI", "protocol": "openai_chat", "builtin": True},
    ]
    with closing(_database()) as conn:
        rows = conn.execute(
            "SELECT id, display_name, protocol, base_url, api_key_env FROM provider_connections ORDER BY id"
        ).fetchall()
    return builtins + [{**dict(row), "builtin": False} for row in rows]


def get_connection(provider_id: str) -> dict[str, Any] | None:
    with closing(_database()) as conn:
        row = conn.execute(
            "SELECT id, display_name, protocol, base_url, api_key_env FROM provider_connections WHERE id = ?",
            (provider_id.strip().lower(),),
        ).fetchone()
    return dict(row) if row else None


def create_connection(
    provider_id: str,
    display_name: str,
    protocol: str,
    base_url: str,
    api_key_env: str,
) -> dict[str, Any]:
    provider_id = provider_id.strip().lower()
    display_name = display_name.strip()
    protocol = protocol.strip().lower()
    base_url = base_url.strip().rstrip("/")
    api_key_env = api_key_env.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", provider_id):
        raise ValueError("provider ID 须为 2–64 位小写字母、数字、下划线或中划线，并以字母开头")
    from .providers.registry import is_provider_registered

    if provider_id in BUILTIN_PROVIDER_IDS or is_provider_registered(provider_id):
        raise ValueError(f"provider ID 已存在：{provider_id}")
    if not display_name or len(display_name) > 80:
        raise ValueError("provider 名称须为 1–80 个字符")
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"暂不支持的调用协议：{protocol}")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base_url 须为有效的 HTTP(S) API 根地址，不能包含用户名、查询参数或片段")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        if os.getenv("ALLOW_INSECURE_LLM_HTTP") != "1":
            raise ValueError("远程 provider 的 base_url 须使用 HTTPS；可信内网可设置 ALLOW_INSECURE_LLM_HTTP=1")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
        raise ValueError("API Key 环境变量名无效")
    item = {
        "id": provider_id,
        "display_name": display_name,
        "protocol": protocol,
        "base_url": base_url,
        "api_key_env": api_key_env,
    }
    try:
        with closing(_database()) as conn, conn:
            conn.execute(
                "INSERT INTO provider_connections (id, display_name, protocol, base_url, api_key_env) VALUES (?, ?, ?, ?, ?)",
                tuple(item.values()),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"provider ID 已存在：{provider_id}") from exc
    return {**item, "builtin": False}
