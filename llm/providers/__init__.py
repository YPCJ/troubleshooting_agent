from .base import LLMProvider
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAIProvider
from .registry import (
    create_provider,
    is_provider_registered,
    load_provider_plugins,
    register_provider,
    registered_provider_names,
    unregister_provider,
)

__all__ = [
    "LLMProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "create_provider",
    "is_provider_registered",
    "load_provider_plugins",
    "register_provider",
    "registered_provider_names",
    "unregister_provider",
]

# Load optional extensions only after the package has exposed register_provider;
# plugin modules can therefore safely import it from ``llm.providers``.
load_provider_plugins()
