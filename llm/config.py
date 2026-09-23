from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROFILE_SCHEMA_VERSION = 1

SAMPLING_MODES = {"provider_default", "stable", "flexible", "custom"}
OUTPUT_MODES = {"provider_default", "custom_limit"}
VERBOSITY_LEVELS = {"low", "medium", "high"}
_UNSET = object()


def infer_sampling_mode(profile: Mapping[str, Any]) -> str:
    """Return the canonical sampling mode, including for legacy profiles."""
    configured = str(profile.get("sampling_mode") or "").strip().lower()
    if configured in SAMPLING_MODES:
        return configured
    legacy_style = str(profile.get("generation_style") or "").strip().lower()
    if legacy_style == "recommended":
        return "provider_default"
    if legacy_style in {"stable", "flexible", "custom"}:
        return legacy_style
    if any(profile.get(key) is not None for key in ("temperature", "top_p", "top_n", "top_k")):
        return "custom"
    return "provider_default"


def infer_output_mode(profile: Mapping[str, Any]) -> str:
    """Return the canonical output-budget mode, including for legacy profiles."""
    configured = str(profile.get("output_mode") or "").strip().lower()
    if configured in OUTPUT_MODES:
        return configured
    return "custom_limit" if profile.get("max_output_tokens") is not None else "provider_default"


def generation_style_for_sampling_mode(sampling_mode: str) -> str:
    """Expose the former semantic field as a compatibility alias."""
    return "recommended" if sampling_mode == "provider_default" else sampling_mode


def _normalize_sampling_mode(
    sampling_mode: Any = _UNSET,
    generation_style: Any = _UNSET,
) -> str | None:
    normalized_mode: str | None = None
    if sampling_mode is not _UNSET and sampling_mode is not None:
        normalized_mode = str(sampling_mode).strip().lower()
        if normalized_mode not in SAMPLING_MODES:
            raise ValueError(
                "sampling_mode 必须是 provider_default、stable、flexible 或 custom"
            )
    if generation_style is not _UNSET and generation_style is not None:
        normalized_style = str(generation_style).strip().lower()
        style_mode = "provider_default" if normalized_style == "recommended" else normalized_style
        if style_mode not in SAMPLING_MODES:
            raise ValueError(
                "generation_style 必须是 recommended、stable、flexible 或 custom"
            )
        if normalized_mode is not None and normalized_mode != style_mode:
            raise ValueError("sampling_mode 与 generation_style 不一致")
        normalized_mode = style_mode
    return normalized_mode


def _normalize_output_mode(output_mode: Any = _UNSET) -> str | None:
    if output_mode is _UNSET or output_mode is None:
        return None
    normalized = str(output_mode).strip().lower()
    if normalized not in OUTPUT_MODES:
        raise ValueError("output_mode 必须是 provider_default 或 custom_limit")
    return normalized


def _normalize_verbosity(verbosity: Any) -> str | None:
    if verbosity is None:
        return None
    normalized = str(verbosity).strip().lower()
    if normalized not in VERBOSITY_LEVELS:
        raise ValueError("verbosity 必须是 low、medium 或 high")
    return normalized


def _clear_sampling_settings(profile: dict[str, Any]) -> None:
    for key in ("temperature", "top_p", "top_n", "top_k", "sampling_mode", "generation_style"):
        profile.pop(key, None)


def _clear_output_settings(profile: dict[str, Any]) -> None:
    for key in ("max_output_tokens", "output_mode"):
        profile.pop(key, None)


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
    if os.getenv("AGENT_APP_MODE") == "sbc":
        return {
            "default_profile": "intranet_default",
            "profiles": {
                "intranet_default": {
                    "provider": "openai",
                    "model": os.getenv("INTRANET_LLM_MODEL", "intranet-model"),
                    "base_url": "${INTRANET_LLM_BASE_URL}",
                    "api_key_envs": ["INTRANET_LLM_API_KEY"],
                    "base_url_envs": ["INTRANET_LLM_BASE_URL"],
                }
            },
        }
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


def _profiles_db_path() -> Path:
    cfg_path = os.getenv("MODEL_PROFILES_DB_PATH")
    if cfg_path:
        return Path(cfg_path).expanduser()
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
    with closing(_profiles_db()) as conn, conn:
        _init_profiles_store(conn)
        payload = _load_profiles_from_store(conn)
        if payload["profiles"]:
            return _normalize_profiles_payload(payload) if include_deleted else _active_profiles_payload(payload)

        default_payload = default_profiles()
        _save_profiles_to_store(conn, default_payload)
        return default_payload if include_deleted else _active_profiles_payload(default_payload)


def save_profiles(data: Mapping[str, Any]) -> None:
    db_path = _profiles_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_profiles_db()) as conn, conn:
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
    sampling_mode: Any = _UNSET,
    output_mode: Any = _UNSET,
    generation_style: Any = _UNSET,
    verbosity: Any = _UNSET,
    clear_generation_overrides: bool = False,
    replace_generation_overrides: bool = False,
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
        normalized_provider = provider.strip().lower()
        from .providers import is_provider_registered

        if not is_provider_registered(normalized_provider):
            raise ValueError(f"Unsupported model provider: {normalized_provider}")
        if normalized_provider != str(profile.get("provider") or "").strip().lower():
            raise ValueError("已创建模型入口的 provider 不可修改，请复制为新入口")
    if model_name is not None:
        normalized_model = model_name.strip()
        if normalized_model != str(profile.get("model") or "").strip():
            raise ValueError("已创建模型入口的 model_name 不可修改，请复制为新入口")
    if base_url is not None:
        normalized_base_url = base_url.strip()
        existing_base_url = str(profile.get("base_url") or "").strip()
        if normalized_base_url != existing_base_url:
            raise ValueError("已创建模型入口的 base_url 不可修改，请复制为新入口")
    if api_key_envs is not None:
        normalized_api_key_envs = [str(x) for x in api_key_envs if str(x).strip()]
        if normalized_api_key_envs != list(profile.get("api_key_envs") or []):
            raise ValueError("已创建模型入口的 api_key_envs 不可修改，请复制为新入口")
    if base_url_envs is not None:
        normalized_base_url_envs = [str(x) for x in base_url_envs if str(x).strip()]
        if normalized_base_url_envs != list(profile.get("base_url_envs") or []):
            raise ValueError("已创建模型入口的 base_url_envs 不可修改，请复制为新入口")
    normalized_sampling_mode = _normalize_sampling_mode(sampling_mode, generation_style)
    normalized_output_mode = _normalize_output_mode(output_mode)
    if clear_generation_overrides or replace_generation_overrides:
        _clear_sampling_settings(profile)
        _clear_output_settings(profile)
        profile.pop("verbosity", None)
    if normalized_sampling_mode is not None:
        _clear_sampling_settings(profile)
    if normalized_output_mode is not None:
        _clear_output_settings(profile)
    if temperature is not None and not 0 <= float(temperature) <= 2:
        raise ValueError("temperature 必须在 0 到 2 之间")
    if top_p is not None and not 0 <= float(top_p) <= 1:
        raise ValueError("top_p 必须在 0 到 1 之间")
    if temperature is not None and top_p is not None:
        raise ValueError("temperature 和 top_p 请选择一个进行覆盖")
    if top_k is not None and int(top_k) < 1:
        raise ValueError("top_k 必须大于等于 1")
    if max_output_tokens is not None and int(max_output_tokens) < 1:
        raise ValueError("max_output_tokens 必须大于等于 1")
    sampling_is_default = clear_generation_overrides or normalized_sampling_mode == "provider_default"
    if not sampling_is_default:
        if temperature is not None:
            profile["temperature"] = float(temperature)
            profile.pop("top_p", None)
            profile.pop("top_n", None)
        if top_p is not None:
            profile["top_p"] = float(top_p)
            profile.pop("temperature", None)
        if top_k is not None:
            profile["top_k"] = int(top_k)
        if normalized_sampling_mode in {"stable", "flexible"}:
            if temperature is None and top_p is None:
                profile["temperature"] = 0.2 if normalized_sampling_mode == "stable" else 0.8
            profile["sampling_mode"] = normalized_sampling_mode
        elif normalized_sampling_mode == "custom":
            profile["sampling_mode"] = "custom"
        elif any(value is not None for value in (temperature, top_p, top_k)):
            profile["sampling_mode"] = "custom"

    output_is_default = clear_generation_overrides or normalized_output_mode == "provider_default"
    if not output_is_default and max_output_tokens is not None:
        profile["max_output_tokens"] = int(max_output_tokens)
        profile["output_mode"] = "custom_limit"
    elif normalized_output_mode == "custom_limit":
        raise ValueError("output_mode 为 custom_limit 时必须提供 max_output_tokens")

    if verbosity is not _UNSET and not clear_generation_overrides:
        normalized_verbosity = _normalize_verbosity(verbosity)
        if normalized_verbosity is None:
            profile.pop("verbosity", None)
        else:
            profile["verbosity"] = normalized_verbosity
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
    sampling_mode: str | None = None,
    output_mode: str | None = None,
    generation_style: str | None = None,
    verbosity: str | None = None,
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
    from .providers import is_provider_registered

    if not is_provider_registered(profile["provider"]):
        raise ValueError(f"Unsupported model provider: {profile['provider']}")
    if not profile["model"]:
        raise ValueError("model_name 不能为空")
    if base_url is not None and base_url.strip():
        profile["base_url"] = base_url.strip()
    if api_key_envs:
        profile["api_key_envs"] = [str(x) for x in api_key_envs if str(x).strip()]
    if base_url_envs:
        profile["base_url_envs"] = [str(x) for x in base_url_envs if str(x).strip()]
    normalized_sampling_mode = _normalize_sampling_mode(sampling_mode, generation_style)
    normalized_output_mode = _normalize_output_mode(output_mode)
    if temperature is not None and not 0 <= float(temperature) <= 2:
        raise ValueError("temperature 必须在 0 到 2 之间")
    if top_p is not None and not 0 <= float(top_p) <= 1:
        raise ValueError("top_p 必须在 0 到 1 之间")
    if temperature is not None and top_p is not None:
        raise ValueError("temperature 和 top_p 请选择一个进行覆盖")
    if top_k is not None and int(top_k) < 1:
        raise ValueError("top_k 必须大于等于 1")
    if max_output_tokens is not None and int(max_output_tokens) < 1:
        raise ValueError("max_output_tokens 必须大于等于 1")
    if normalized_sampling_mode != "provider_default":
        if temperature is not None:
            profile["temperature"] = float(temperature)
        if top_p is not None:
            profile["top_p"] = float(top_p)
        if top_k is not None:
            profile["top_k"] = int(top_k)
        if normalized_sampling_mode in {"stable", "flexible"}:
            if temperature is None and top_p is None:
                profile["temperature"] = 0.2 if normalized_sampling_mode == "stable" else 0.8
            profile["sampling_mode"] = normalized_sampling_mode
        elif normalized_sampling_mode == "custom":
            profile["sampling_mode"] = "custom"
        elif any(value is not None for value in (temperature, top_p, top_k)):
            profile["sampling_mode"] = "custom"
    if normalized_output_mode != "provider_default" and max_output_tokens is not None:
        profile["max_output_tokens"] = int(max_output_tokens)
        profile["output_mode"] = "custom_limit"
    elif normalized_output_mode == "custom_limit":
        raise ValueError("output_mode 为 custom_limit 时必须提供 max_output_tokens")
    normalized_verbosity = _normalize_verbosity(verbosity)
    if normalized_verbosity is not None:
        profile["verbosity"] = normalized_verbosity
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
    sampling_mode = infer_sampling_mode(profile)
    return {
        "profile_name": runtime_profile,
        "provider": resolved_provider,
        "model_name": resolved_model,
        "temperature": profile.get("temperature"),
        "max_output_tokens": profile.get("max_output_tokens"),
        "top_p": top_p,
        "top_k": profile.get("top_k"),
        "sampling_mode": sampling_mode,
        "output_mode": infer_output_mode(profile),
        "generation_style": generation_style_for_sampling_mode(sampling_mode),
        "verbosity": profile.get("verbosity"),
        "profile": dict(profile),
    }


_load_env_file(project_root() / ".env")
