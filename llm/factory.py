from __future__ import annotations

import json
import ssl
import time
from typing import Any, Iterator, Mapping

from .config import resolve_model_runtime
from .providers.gemini_provider import GeminiProvider
from .providers.openai_provider import OpenAIProvider


def _is_transient_llm_error(exc: BaseException) -> bool:
    try:
        import httpx  # type: ignore
    except Exception:  # pragma: no cover - optional dependency at runtime
        httpx = None

    retryable_types: tuple[type[BaseException], ...] = tuple(
        t
        for t in (
            ssl.SSLError,
            getattr(httpx, "ConnectError", None) if httpx else None,
            getattr(httpx, "ReadError", None) if httpx else None,
            getattr(httpx, "ReadTimeout", None) if httpx else None,
            getattr(httpx, "WriteError", None) if httpx else None,
            getattr(httpx, "RemoteProtocolError", None) if httpx else None,
        )
        if isinstance(t, type) and issubclass(t, BaseException)
    )
    if retryable_types and isinstance(exc, retryable_types):
        return True
    message = str(exc).upper()
    return (
        "UNEXPECTED_EOF_WHILE_READING" in message
        or "EOF OCCURRED IN VIOLATION OF PROTOCOL" in message
        or "SERVER DISCONNECTED" in message
        or "CONNECTION RESET BY PEER" in message
    )


def _call_with_transient_retry(fn: Any, *, max_attempts: int = 4) -> Any:
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            if not _is_transient_llm_error(exc):
                raise
            if attempt >= max_attempts - 1:
                raise RuntimeError(f"LLM transient failure after {max_attempts} attempts: {exc}") from exc
            time.sleep(min(0.6 * (2**attempt), 3.0))
    raise RuntimeError("LLM call failed without exception details")


def _build_provider(runtime: Mapping[str, Any]):
    provider_name = str(runtime["provider"])
    if provider_name == "gemini":
        return GeminiProvider()
    if provider_name in {"openai", "aliyun"}:
        return OpenAIProvider(runtime["profile"])
    raise ValueError(f"Unsupported model provider: {provider_name}")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def chat_reply_stream(
    messages: list[Mapping[str, Any]],
    *,
    tools: Any = None,
    model_name: str | None = None,
    profile_name: str | None = None,
    provider: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
) -> Iterator[dict[str, Any]]:
    runtime = resolve_model_runtime(
        profile_name=profile_name,
        provider=provider,
        model_name=model_name,
    )
    model = runtime["model_name"]
    effective_temperature = temperature if temperature is not None else (_to_float(runtime.get("temperature")) or 0.7)
    effective_max_output_tokens = max_output_tokens if max_output_tokens is not None else (_to_int(runtime.get("max_output_tokens")) or 4096)
    effective_top_p = top_p if top_p is not None else _to_float(runtime.get("top_p"))
    effective_top_k = top_k if top_k is not None else _to_int(runtime.get("top_k"))
    provider_impl = _build_provider(runtime)

    def _create_stream() -> Iterator[dict[str, Any]]:
        return provider_impl.chat_stream(
            messages,
            tools=tools,
            model_name=model,
            temperature=effective_temperature,
            max_output_tokens=effective_max_output_tokens,
            top_p=effective_top_p,
            top_k=effective_top_k,
        )

    stream = _call_with_transient_retry(_create_stream)
    yield from stream


def chat_reply(
    messages: list[Mapping[str, Any]],
    *,
    tools: Any = None,
    model_name: str | None = None,
    profile_name: str | None = None,
    provider: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
) -> Mapping[str, Any]:
    runtime = resolve_model_runtime(
        profile_name=profile_name,
        provider=provider,
        model_name=model_name,
    )
    model = runtime["model_name"]
    effective_temperature = temperature if temperature is not None else (_to_float(runtime.get("temperature")) or 0.7)
    effective_max_output_tokens = max_output_tokens if max_output_tokens is not None else (_to_int(runtime.get("max_output_tokens")) or 4096)
    effective_top_p = top_p if top_p is not None else _to_float(runtime.get("top_p"))
    effective_top_k = top_k if top_k is not None else _to_int(runtime.get("top_k"))
    provider_impl = _build_provider(runtime)

    def _call() -> Mapping[str, Any]:
        return provider_impl.chat(
            messages,
            tools=tools,
            model_name=model,
            temperature=effective_temperature,
            max_output_tokens=effective_max_output_tokens,
            top_p=effective_top_p,
            top_k=effective_top_k,
        )

    return _call_with_transient_retry(_call)


def profile_summary(profile_name: str | None = None) -> str:
    runtime = resolve_model_runtime(profile_name=profile_name)
    return json.dumps(
        {
            "profile": runtime["profile_name"],
            "provider": runtime["provider"],
            "model": runtime["model_name"],
        },
        ensure_ascii=False,
    )
