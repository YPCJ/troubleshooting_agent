"""Catalog, capabilities, and exact-model probes for the management UI."""

from __future__ import annotations

import time
from typing import Any, Mapping

from .providers.base import LLMProvider


def discover_models(provider: LLMProvider, query: str = "") -> list[str]:
    keyword = query.strip().lower()
    models = sorted(set(provider.list_models()))
    return [model for model in models if not keyword or keyword in model.lower()]


def read_capabilities(provider: LLMProvider, provider_id: str, model: str) -> dict[str, Any]:
    getter = getattr(provider, "get_model_capabilities", None)
    if callable(getter):
        return dict(getter(model))
    return {
        "provider": provider_id,
        "model": model,
        "parameters": {},
        "exclusive_groups": [],
        "defaults_source": "unknown",
        "recommend_provider_defaults": True,
        "sampling_presets": [],
        "verbosity": {"supported": False, "choices": [], "default": None},
        "output": {
            "omission_supported": True,
            "counts_reasoning_tokens": False,
            "recommended": None,
        },
    }


def probe_model(provider: LLMProvider, provider_id: str, model: str) -> dict[str, Any]:
    """Make a small real inference call, not merely a catalog or auth request."""
    capabilities = read_capabilities(provider, provider_id, model)
    parameters = capabilities.get("parameters") if isinstance(capabilities.get("parameters"), dict) else {}
    temperature_capability = parameters.get("temperature") if isinstance(parameters.get("temperature"), dict) else {}
    output_capability = parameters.get("max_output_tokens") if isinstance(parameters.get("max_output_tokens"), dict) else {}
    output_metadata = capabilities.get("output") if isinstance(capabilities.get("output"), dict) else {}
    call_options: dict[str, Any] = {}
    if temperature_capability.get("supported", True) and not capabilities.get("recommend_provider_defaults"):
        call_options["temperature"] = 0
    if output_capability.get("supported", True) and not output_metadata.get("counts_reasoning_tokens") and capabilities.get("defaults_source") != "unknown":
        model_max = output_capability.get("max")
        call_options["max_output_tokens"] = min(128, int(model_max)) if model_max else 128
    started_at = time.perf_counter()
    response = provider.chat(
        [{"role": "user", "content": "请只回复：Hello world"}],
        model_name=model,
        **call_options,
    )
    latency_ms = round((time.perf_counter() - started_at) * 1000)
    content = str(response.get("content") or "").strip()
    if not content:
        raise RuntimeError("模型调用成功但未返回可展示内容")
    raw_usage = response.get("usage")
    usage = dict(raw_usage) if isinstance(raw_usage, Mapping) else {}
    return {
        "ok": True,
        "provider": provider_id,
        "model_name": model,
        "response": content,
        "latency_ms": latency_ms,
        "usage": usage,
    }
