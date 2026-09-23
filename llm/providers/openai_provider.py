from __future__ import annotations

from typing import Any, Iterator, Mapping

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - fallback when SDK is not installed
    OpenAI = None


def _first_env_value(names: list[str]) -> str | None:
    import os

    for name in names:
        v = os.getenv(name)
        if v:
            return v
    return None


def _resolve_env_reference(value: str) -> str | None:
    import os

    raw = value.strip()
    if not raw:
        return None
    def _env(name: str) -> str | None:
        return os.getenv(name) or os.getenv(name.lower()) or os.getenv(name.upper())

    if raw.startswith("${") and raw.endswith("}") and len(raw) > 3:
        return _env(raw[2:-1].strip())
    if raw.startswith("env:") and len(raw) > 4:
        return _env(raw[4:].strip())
    return raw


def _openai_client_from_profile(profile: Mapping[str, Any]) -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("openai SDK is not installed")
    key_names = profile.get("api_key_envs")
    if not isinstance(key_names, list):
        key_names = ["OPENAI_API_KEY", "api_key"]
    base_url_names = profile.get("base_url_envs")
    if not isinstance(base_url_names, list):
        base_url_names = ["OPENAI_BASE_URL", "BASE_URL", "base_url"]
    api_key = _first_env_value([str(x) for x in key_names])
    if not api_key:
        raise RuntimeError(f"OpenAI API key not found in envs: {key_names}")
    profile_base_url = profile.get("base_url")
    if isinstance(profile_base_url, str) and profile_base_url.strip():
        resolved_profile_base_url = _resolve_env_reference(profile_base_url)
        if resolved_profile_base_url:
            return OpenAI(api_key=api_key, base_url=resolved_profile_base_url)
    base_url = _first_env_value([str(x) for x in base_url_names])
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _normalize_openai_tool_call(call: Any) -> dict[str, Any]:
    function = getattr(call, "function", None)
    return {
        "id": str(getattr(call, "id", "") or ""),
        "type": "function",
        "function": {
            "name": str(getattr(function, "name", "") or ""),
            "arguments": str(getattr(function, "arguments", "") or "{}"),
        },
    }


class OpenAIProvider:
    def __init__(self, profile: Mapping[str, Any]):
        self._profile = profile

    def _client(self) -> OpenAI:
        return _openai_client_from_profile(self._profile)

    def list_models(self) -> list[str]:
        client = self._client()
        response = client.models.list()
        data = getattr(response, "data", None) or []
        model_ids: list[str] = []
        for item in data:
            model_id = getattr(item, "id", None)
            if isinstance(model_id, str) and model_id.strip():
                model_ids.append(model_id.strip())
        return sorted(set(model_ids))

    def _uses_completion_token_budget(self, model_name: str) -> bool:
        provider_id = str(self._profile.get("provider") or "openai").strip().lower()
        model_id = model_name.strip().lower()
        return provider_id == "openai" and model_id.startswith(("o1", "o3", "o4", "gpt-5", "gpt-6"))

    def get_model_capabilities(self, model_name: str) -> Mapping[str, Any]:
        provider_id = str(self._profile.get("provider") or "openai").strip().lower()
        model_id = model_name.strip().lower()
        model_managed_sampling = self._uses_completion_token_budget(model_name)
        unknown_compatible_service = provider_id not in {"openai", "aliyun"}
        sampling_supported = not model_managed_sampling
        verbosity_supported = provider_id == "openai" and model_id.startswith(("gpt-5", "gpt-6"))
        return {
            "provider": provider_id,
            "model": model_name,
            "parameters": {
                "temperature": {"supported": sampling_supported, "min": 0, "max": 2, "step": 0.1, "default": None},
                "top_p": {"supported": sampling_supported, "min": 0, "max": 1, "step": 0.05, "default": None},
                "top_k": {"supported": False, "default": None},
                "max_output_tokens": {"supported": True, "min": 1, "max": None, "step": 1, "default": None},
            },
            "exclusive_groups": [["temperature", "top_p"]],
            "defaults_source": "unknown" if unknown_compatible_service else "provider",
            "recommend_provider_defaults": model_managed_sampling or unknown_compatible_service,
            "sampling_presets": [] if model_managed_sampling or unknown_compatible_service else [
                {"id": "stable", "temperature": 0.2},
                {"id": "flexible", "temperature": 0.8},
            ],
            "verbosity": {
                "supported": verbosity_supported,
                "choices": ["low", "medium", "high"] if verbosity_supported else [],
                "default": "medium" if verbosity_supported else None,
            },
            "output": {
                "omission_supported": True,
                "counts_reasoning_tokens": model_managed_sampling,
                "recommended": None,
            },
        }

    def chat(
        self,
        messages: list[Mapping[str, Any]],
        *,
        tools: Any = None,
        model_name: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        verbosity: str | None = None,
    ) -> Mapping[str, Any]:
        if not model_name:
            raise ValueError("OpenAI model_name is required")
        client = self._client()
        request: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
        }
        if max_output_tokens is not None:
            token_parameter = "max_completion_tokens" if self._uses_completion_token_budget(model_name) else "max_tokens"
            request[token_parameter] = max_output_tokens
        if temperature is not None:
            request["temperature"] = temperature
        if top_p is not None:
            request["top_p"] = top_p
        if verbosity is not None:
            request["verbosity"] = verbosity
        if tools:
            request["tools"] = tools
            request["tool_choice"] = "auto"
        resp = client.chat.completions.create(**request)
        if not resp.choices:
            return {"content": "", "tool_calls": []}
        msg = resp.choices[0].message
        content = msg.content or ""
        tool_calls = [_normalize_openai_tool_call(c) for c in (msg.tool_calls or [])]
        usage = getattr(resp, "usage", None)
        payload = {"content": content, "tool_calls": tool_calls}
        if usage is not None:
            payload["usage"] = {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
        return payload

    def chat_stream(
        self,
        messages: list[Mapping[str, Any]],
        *,
        tools: Any = None,
        model_name: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        verbosity: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        if not model_name:
            raise ValueError("OpenAI model_name is required")
        client = self._client()
        request: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": True,
        }
        if max_output_tokens is not None:
            token_parameter = "max_completion_tokens" if self._uses_completion_token_budget(model_name) else "max_tokens"
            request[token_parameter] = max_output_tokens
        if temperature is not None:
            request["temperature"] = temperature
        if top_p is not None:
            request["top_p"] = top_p
        if verbosity is not None:
            request["verbosity"] = verbosity
        if tools:
            request["tools"] = tools
            request["tool_choice"] = "auto"
        stream = client.chat.completions.create(**request)
        content_buffer = ""
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            chunk_text = getattr(delta, "content", None) or ""
            if chunk_text:
                content_buffer += chunk_text
            chunk_tool_calls: list[dict[str, Any]] = []
            delta_calls = getattr(delta, "tool_calls", None) or []
            for tc in delta_calls:
                idx = int(getattr(tc, "index", 0) or 0)
                current = tool_calls_by_index.setdefault(
                    idx,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                tc_id = getattr(tc, "id", None)
                if tc_id:
                    current["id"] += str(tc_id)
                fn = getattr(tc, "function", None)
                if fn is not None:
                    fn_name = getattr(fn, "name", None)
                    if fn_name:
                        current["function"]["name"] += str(fn_name)
                    fn_args = getattr(fn, "arguments", None)
                    if fn_args:
                        current["function"]["arguments"] += str(fn_args)
                chunk_tool_calls.append(
                    {
                        "id": current["id"] or f"openai_call_{idx}",
                        "type": "function",
                        "function": {
                            "name": current["function"]["name"],
                            "arguments": current["function"]["arguments"] or "{}",
                        },
                    }
                )
            yield {"type": "chunk", "content": chunk_text, "tool_calls": chunk_tool_calls}
        final_calls: list[dict[str, Any]] = []
        for idx in sorted(tool_calls_by_index.keys()):
            call = tool_calls_by_index[idx]
            final_calls.append(
                {
                    "id": call["id"] or f"openai_call_{idx}",
                    "type": "function",
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"] or "{}",
                    },
                }
            )
        yield {"type": "done", "content": content_buffer, "tool_calls": final_calls}
