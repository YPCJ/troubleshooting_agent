from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROFILE_SCHEMA_VERSION = 1


def project_root() -> Path:
    here = Path(__file__).resolve().parent
    for p in [here, *here.parents]:
        if (p / ".env").exists():
            return p
    return here.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def default_profiles() -> dict[str, Any]:
    return {
        "default_profile": "gemini_default",
        "profiles": {
            "gemini_default": {
                "provider": "gemini",
                "model": "gemini-pro-latest",
            },
            "chatgpt_default": {
                "provider": "aliyun",
                "model": "qwen3.7-max",
                "base_url": "${BASE_URL}",
                "api_key_envs": ["DASHSCOPE_API_KEY", "OPENAI_API_KEY", "api_key"],
                "base_url_envs": ["OPENAI_BASE_URL", "BASE_URL", "base_url"],
            },
            "qwen_default": {
                "provider": "aliyun",
                "model": "qwen-max",
                "base_url": "${BASE_URL}",
                "api_key_envs": ["DASHSCOPE_API_KEY", "OPENAI_API_KEY", "api_key"],
                "base_url_envs": ["OPENAI_BASE_URL", "BASE_URL", "base_url"],
            },
            "gemini-test": {
                "provider": "gemini",
                "model": "gemini-3.6-flash",
            },
        },
    }


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in inner.split(",")]
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        try:
            return int(value)
        except ValueError:
            pass
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except ValueError:
            pass
    return value


def _parse_model_profiles(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {"profiles": {}}
    section: str | None = None
    profile_name: str | None = None
    current_list_key: str | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        if indent == 0 and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            section = key
            profile_name = None
            current_list_key = None
            if value:
                data[key] = _parse_scalar(value)
            elif key == "profiles":
                data[key] = {}
            else:
                data[key] = {}
            continue

        if section == "profiles":
            if indent == 2 and line.endswith(":"):
                profile_name = line[:-1].strip()
                data["profiles"][profile_name] = {}
                current_list_key = None
                continue
            if indent == 4 and profile_name and ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                if value:
                    data["profiles"][profile_name][key] = _parse_scalar(value)
                    current_list_key = None
                else:
                    data["profiles"][profile_name][key] = []
                    current_list_key = key
                continue
            if indent >= 6 and profile_name and current_list_key and line.startswith("- "):
                data["profiles"][profile_name].setdefault(current_list_key, []).append(_parse_scalar(line[2:]))
                continue

    if not data["profiles"]:
        return default_profiles()
    default_profile = data.get("default_profile")
    if not isinstance(default_profile, str) or default_profile not in data["profiles"]:
        default_profile = next(iter(data["profiles"].keys()))
    return {"default_profile": default_profile, "profiles": data["profiles"]}


def _legacy_profiles_path() -> Path:
    cfg_path = os.getenv("MODEL_PROFILES_PATH")
    if cfg_path:
        return Path(cfg_path).expanduser()
    return project_root() / "config" / "model_profiles.yaml"


def _profiles_db_path() -> Path:
    cfg_path = os.getenv("MODEL_PROFILES_DB_PATH")
    if cfg_path:
        return Path(cfg_path).expanduser()
    legacy_path = os.getenv("MODEL_PROFILES_PATH")
    if legacy_path:
        candidate = Path(legacy_path).expanduser()
        if candidate.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            return candidate
    return project_root() / "data" / "model_profiles.sqlite3"


def _profiles_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_profiles_payload(data: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        return default_profiles()

    raw_profiles = data.get("profiles")
    profiles: dict[str, dict[str, Any]] = {}
    if isinstance(raw_profiles, Mapping):
        for profile_id, profile in raw_profiles.items():
            pid = str(profile_id).strip()
            if not pid or not isinstance(profile, Mapping):
                continue
            profiles[pid] = dict(profile)

    if not profiles:
        return default_profiles()

    default_profile = str(data.get("default_profile") or "").strip()
    if default_profile not in profiles:
        default_profile = next(iter(profiles.keys()))

    return {"default_profile": default_profile, "profiles": profiles}


def _is_deleted_profile(profile: Mapping[str, Any]) -> bool:
    deleted_at = profile.get("deleted_at")
    return bool(str(deleted_at).strip()) if deleted_at is not None else False


def _active_profiles_payload(data: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_profiles_payload(data)
    active_profiles = {
        profile_id: profile
        for profile_id, profile in normalized["profiles"].items()
        if isinstance(profile, Mapping) and not _is_deleted_profile(profile)
    }
    default_profile = normalized["default_profile"] if normalized["default_profile"] in active_profiles else ""
    if not default_profile and active_profiles:
        default_profile = next(iter(active_profiles.keys()))
    return {"default_profile": default_profile, "profiles": active_profiles}


def _profiles_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_profiles_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _get_profiles_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM model_profile_meta WHERE key = 'schema_version'").fetchone()
    if not row:
        return 0
    try:
        return int(str(row["value"]))
    except ValueError:
        return 0


def _set_profiles_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT INTO model_profile_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )


def _set_profiles_default(conn: sqlite3.Connection, default_profile: str) -> None:
    conn.execute(
        "INSERT INTO model_profile_meta (key, value) VALUES ('default_profile', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (default_profile,),
    )


def _init_profiles_store(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_profile_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_profiles (
            profile_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_model_profiles_updated_at ON model_profiles(updated_at)")
    version = _get_profiles_schema_version(conn)
    if version < PROFILE_SCHEMA_VERSION:
        _set_profiles_schema_version(conn, PROFILE_SCHEMA_VERSION)
    elif version > PROFILE_SCHEMA_VERSION:
        raise RuntimeError(
            f"不支持的 model profile schema 版本: {version}, 期望 {PROFILE_SCHEMA_VERSION}。"
        )


def _load_profiles_from_store(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT profile_id, payload_json
        FROM model_profiles
        ORDER BY profile_id ASC
        """
    ).fetchall()
    profiles: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            profiles[str(row["profile_id"])] = dict(payload)

    default_row = conn.execute(
        "SELECT value FROM model_profile_meta WHERE key = 'default_profile'"
    ).fetchone()
    default_profile = str(default_row["value"]) if default_row and default_row["value"] else ""
    return {"default_profile": default_profile, "profiles": profiles}


def _save_profiles_to_store(conn: sqlite3.Connection, data: Mapping[str, Any]) -> None:
    normalized = _normalize_profiles_payload(data)
    now = _profiles_now()
    existing_rows = conn.execute(
        "SELECT profile_id, created_at FROM model_profiles"
    ).fetchall()
    existing_created_at = {str(row["profile_id"]): str(row["created_at"]) for row in existing_rows}
    current_ids = set(normalized["profiles"].keys())

    for missing_id in set(existing_created_at.keys()) - current_ids:
        conn.execute("DELETE FROM model_profiles WHERE profile_id = ?", (missing_id,))

    for profile_id, profile in normalized["profiles"].items():
        payload_json = json.dumps(profile, ensure_ascii=False, default=str)
        created_at = existing_created_at.get(profile_id, now)
        conn.execute(
            """
            INSERT INTO model_profiles (profile_id, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """
            ,
            (profile_id, payload_json, created_at, now),
        )

    _set_profiles_default(conn, normalized["default_profile"])
    _set_profiles_schema_version(conn, PROFILE_SCHEMA_VERSION)


def load_profiles(include_deleted: bool = True) -> dict[str, Any]:
    db_path = _profiles_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _profiles_db() as conn:
        _init_profiles_store(conn)
        payload = _load_profiles_from_store(conn)
        if payload["profiles"]:
            return _normalize_profiles_payload(payload) if include_deleted else _active_profiles_payload(payload)

        legacy_path = _legacy_profiles_path()
        if legacy_path.exists() and legacy_path != db_path:
            legacy_payload = _normalize_profiles_payload(_parse_model_profiles(legacy_path.read_text(encoding="utf-8")))
            _save_profiles_to_store(conn, legacy_payload)
            return legacy_payload if include_deleted else _active_profiles_payload(legacy_payload)

        default_payload = default_profiles()
        _save_profiles_to_store(conn, default_payload)
        return default_payload if include_deleted else _active_profiles_payload(default_payload)


def save_profiles(data: Mapping[str, Any]) -> None:
    db_path = _profiles_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _profiles_db() as conn:
        _init_profiles_store(conn)
        _save_profiles_to_store(conn, data)


def delete_profile(profile_id: str) -> dict[str, Any]:
    pid = profile_id.strip()
    if not pid:
        raise ValueError("profile_id 不能为空")
    cfg = load_profiles()
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Invalid profiles configuration")
    if pid not in profiles:
        raise ValueError(f"Unknown profile: {pid}")
    profile = profiles[pid]
    if not isinstance(profile, dict):
        raise ValueError(f"Invalid profile object: {pid}")
    if _is_deleted_profile(profile):
        return {"profile_id": pid, "default_profile": str(cfg.get("default_profile") or "").strip()}

    deleted_profile = dict(profile)
    deleted_profile["deleted_at"] = _profiles_now()
    current_default = str(cfg.get("default_profile") or "").strip()
    cfg["profiles"][pid] = deleted_profile
    active_profiles = {
        profile_key: item
        for profile_key, item in cfg["profiles"].items()
        if isinstance(item, dict) and not _is_deleted_profile(item)
    }
    if current_default not in active_profiles:
        next_default = next(iter(active_profiles.keys()), "")
        cfg["default_profile"] = next_default
    save_profiles(cfg)
    return {"profile_id": pid, "default_profile": str(cfg.get("default_profile") or "").strip()}


def hard_delete_profile(profile_id: str) -> None:
    pid = profile_id.strip()
    if not pid:
        raise ValueError("profile_id 不能为空")
    cfg = load_profiles()
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Invalid profiles configuration")
    if pid not in profiles:
        return
    cfg["profiles"] = {profile_key: profile for profile_key, profile in profiles.items() if profile_key != pid}
    current_default = str(cfg.get("default_profile") or "").strip()
    if current_default == pid:
        active_profiles = {
            profile_key: profile
            for profile_key, profile in cfg["profiles"].items()
            if isinstance(profile, dict) and not _is_deleted_profile(profile)
        }
        cfg["default_profile"] = next(iter(active_profiles.keys()), "")
    save_profiles(cfg)


def set_default_profile(profile_id: str) -> dict[str, Any]:
    pid = profile_id.strip()
    if not pid:
        raise ValueError("profile_id 不能为空")
    cfg = load_profiles()
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Invalid profiles configuration")
    profile = profiles.get(pid)
    if not isinstance(profile, dict) or _is_deleted_profile(profile):
        raise ValueError(f"Unknown or deleted profile: {pid}")
    cfg["default_profile"] = pid
    save_profiles(cfg)
    return {"profile_id": pid, "default_profile": pid}


def update_profile(
    profile_id: str,
    *,
    provider: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    api_key_envs: list[str] | None = None,
    base_url_envs: list[str] | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    cfg = load_profiles()
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Invalid profiles configuration")
    if profile_id not in profiles:
        raise ValueError(f"Unknown profile: {profile_id}")
    profile_raw = profiles.get(profile_id)
    if not isinstance(profile_raw, dict):
        raise ValueError(f"Invalid profile object: {profile_id}")
    if _is_deleted_profile(profile_raw):
        raise ValueError(f"Profile deleted: {profile_id}")
    profile = dict(profile_raw)
    if provider is not None:
        profile["provider"] = provider
    if model_name is not None:
        profile["model"] = model_name
    if base_url is not None:
        profile["base_url"] = base_url
    if api_key_envs is not None:
        profile["api_key_envs"] = [str(x) for x in api_key_envs if str(x).strip()]
    if base_url_envs is not None:
        profile["base_url_envs"] = [str(x) for x in base_url_envs if str(x).strip()]
    if temperature is not None:
        profile["temperature"] = float(temperature)
    if top_p is not None:
        profile["top_p"] = float(top_p)
    if top_k is not None:
        profile["top_k"] = int(top_k)
    if max_output_tokens is not None:
        profile["max_output_tokens"] = int(max_output_tokens)
    profiles[profile_id] = profile
    save_profiles(cfg)
    return {"profile_id": profile_id, "profile": profile}


def create_profile(
    profile_id: str,
    *,
    provider: str,
    model_name: str,
    base_url: str | None = None,
    api_key_envs: list[str] | None = None,
    base_url_envs: list[str] | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    pid = profile_id.strip()
    if not pid:
        raise ValueError("profile_id 不能为空")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", pid):
        raise ValueError("profile_id 仅支持字母、数字、下划线和中划线")
    cfg = load_profiles()
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Invalid profiles configuration")
    if pid in profiles:
        raise ValueError(f"Profile already exists: {pid}")
    profile = {
        "provider": provider.strip().lower(),
        "model": model_name.strip(),
    }
    if not profile["provider"]:
        raise ValueError("provider 不能为空")
    if not profile["model"]:
        raise ValueError("model_name 不能为空")
    if base_url is not None and base_url.strip():
        profile["base_url"] = base_url.strip()
    if api_key_envs:
        profile["api_key_envs"] = [str(x) for x in api_key_envs if str(x).strip()]
    if base_url_envs:
        profile["base_url_envs"] = [str(x) for x in base_url_envs if str(x).strip()]
    if temperature is not None:
        profile["temperature"] = float(temperature)
    if top_p is not None:
        profile["top_p"] = float(top_p)
    if top_k is not None:
        profile["top_k"] = int(top_k)
    if max_output_tokens is not None:
        profile["max_output_tokens"] = int(max_output_tokens)
    profiles[pid] = profile
    save_profiles(cfg)
    return {"profile_id": pid, "profile": profile}


def resolve_model_runtime(
    *,
    profile_name: str | None = None,
    provider: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    cfg = load_profiles()
    profiles = cfg["profiles"]
    runtime_profile = (
        profile_name
        or os.getenv("MODEL_PROFILE")
        or cfg["default_profile"]
    )
    profile = profiles.get(runtime_profile)
    if not isinstance(profile, Mapping):
        raise ValueError(f"Unknown model profile: {runtime_profile}")
    resolved_provider = (provider or str(profile.get("provider") or "")).strip().lower()
    resolved_model = (model_name or str(profile.get("model") or "")).strip()
    if not resolved_provider:
        raise ValueError(f"Profile '{runtime_profile}' missing provider")
    if not resolved_model:
        raise ValueError(f"Profile '{runtime_profile}' missing model")

    top_p = profile.get("top_p")
    if top_p is None:
        top_p = profile.get("top_n")
    return {
        "profile_name": runtime_profile,
        "provider": resolved_provider,
        "model_name": resolved_model,
        "temperature": profile.get("temperature"),
        "max_output_tokens": profile.get("max_output_tokens"),
        "top_p": top_p,
        "top_k": profile.get("top_k"),
        "profile": dict(profile),
    }


_load_env_file(project_root() / ".env")
