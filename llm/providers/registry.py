from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Mapping
from typing import Any

from .base import LLMProvider

ProviderFactory = Callable[[Mapping[str, Any]], LLMProvider]

_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {}


def register_provider(
    name: str,
    factory: ProviderFactory,
    *,
    replace: bool = False,
) -> None:
    """Register an LLM provider constructor under a stable provider id."""
    provider_id = name.strip().lower()
    if not provider_id:
        raise ValueError("provider name cannot be empty")
    if provider_id in _PROVIDER_FACTORIES and not replace:
        raise ValueError(f"Provider already registered: {provider_id}")
    _PROVIDER_FACTORIES[provider_id] = factory


def create_provider(name: str, profile: Mapping[str, Any] | None = None) -> LLMProvider:
    provider_id = name.strip().lower()
    factory = _PROVIDER_FACTORIES.get(provider_id)
    connection = None
    if factory is None:
        from llm.connections import get_connection
        from .openai_provider import OpenAIProvider

        connection = get_connection(provider_id)
        if connection and connection["protocol"] == "openai_chat":
            factory = OpenAIProvider
    if factory is None:
        available = ", ".join(registered_provider_names()) or "<none>"
        raise ValueError(f"Unsupported model provider: {provider_id}; available: {available}")
    settings = dict(profile or {})
    if connection:
        # Connection-owned transport fields take precedence over profile data.
        settings.update(
            provider=provider_id,
            base_url=connection["base_url"],
            api_key_envs=[connection["api_key_env"]],
            base_url_envs=[],
        )
    return factory(settings)


def registered_provider_names() -> list[str]:
    from llm.connections import list_connections

    return sorted(set(_PROVIDER_FACTORIES) | {item["id"] for item in list_connections()})


def unregister_provider(name: str) -> None:
    _PROVIDER_FACTORIES.pop(name.strip().lower(), None)


def is_provider_registered(name: str) -> bool:
    provider_id = name.strip().lower()
    if provider_id in _PROVIDER_FACTORIES:
        return True
    from llm.connections import get_connection

    return get_connection(provider_id) is not None


def load_provider_plugins(module_names: list[str] | None = None) -> None:
    """Import provider plugins which register themselves on module import.

    Deployments can set ``LLM_PROVIDER_MODULES`` to a comma-separated module
    list, allowing a new provider to be added without editing the factory.
    """
    names = module_names
    if names is None:
        names = [part.strip() for part in os.getenv("LLM_PROVIDER_MODULES", "").split(",")]
    for module_name in names:
        if module_name:
            importlib.import_module(module_name)


def _register_builtin_providers() -> None:
    from .gemini_provider import GeminiProvider
    from .openai_provider import OpenAIProvider

    register_provider("gemini", GeminiProvider)
    register_provider("openai", OpenAIProvider)
    # Aliyun's OpenAI-compatible endpoint shares the transport adapter while
    # retaining a distinct provider id for profile/catalog configuration.
    register_provider("aliyun", OpenAIProvider)


_register_builtin_providers()
