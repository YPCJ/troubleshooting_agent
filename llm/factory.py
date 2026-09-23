from __future__ import annotations

import json
import random
import ssl
import time
from typing import Any, Iterator, Mapping

from .config import resolve_model_runtime
from .providers.registry import create_provider


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


def _call_with_transient_retry(fn: Any, *, max_attempts: int = 6) -> Any:
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            if not _is_transient_llm_error(exc):
                raise
            if attempt >= max_attempts - 1:
                raise RuntimeError(f"LLM transient failure after {max_attempts} attempts: {exc}") from exc
            # Jitter keeps repeated reconnects from lining up on the same
            # upstream window after an SSL/EOF drop.
            backoff = min(0.8 * (2**attempt), 12.0)
            time.sleep(backoff * (0.75 + random.random() * 0.5))
    raise RuntimeError("LLM call failed without exception details")


def _build_provider(runtime: Mapping[str, Any]):
    return create_provider(str(runtime["provider"]), runtime["profile"])


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
    verbosity: str | None = None,
) -> Iterator[dict[str, Any]]:
    runtime = resolve_model_runtime(
        profile_name=profile_name,
        provider=provider,
        model_name=model_name,
    )
    model = runtime["model_name"]
    profile_temperature = _to_float(runtime.get("temperature"))
    profile_max_output_tokens = _to_int(runtime.get("max_output_tokens"))
    effective_temperature = temperature if temperature is not None else profile_temperature
    effective_max_output_tokens = max_output_tokens if max_output_tokens is not None else profile_max_output_tokens
    effective_top_p = top_p if top_p is not None else _to_float(runtime.get("top_p"))
    effective_top_k = top_k if top_k is not None else _to_int(runtime.get("top_k"))
    effective_verbosity = verbosity if verbosity is not None else runtime.get("verbosity")
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
            verbosity=effective_verbosity,
        )

    def _start_stream() -> tuple[list[dict[str, Any]], Iterator[dict[str, Any]]]:
        # chat_stream is a generator function, so the network call only runs on
        # the first next(). Pull that chunk here to keep the connection attempt
        # inside the retry loop; retrying later would duplicate emitted content.
        iterator = _create_stream()
        try:
            return [next(iterator)], iterator
        except StopIteration:
            return [], iterator

    first_chunks, stream = _call_with_transient_retry(_start_stream)
    yield from first_chunks
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
    verbosity: str | None = None,
) -> Mapping[str, Any]:
    runtime = resolve_model_runtime(
        profile_name=profile_name,
        provider=provider,
        model_name=model_name,
    )
    model = runtime["model_name"]
    profile_temperature = _to_float(runtime.get("temperature"))
    profile_max_output_tokens = _to_int(runtime.get("max_output_tokens"))
    effective_temperature = temperature if temperature is not None else profile_temperature
    effective_max_output_tokens = max_output_tokens if max_output_tokens is not None else profile_max_output_tokens
    effective_top_p = top_p if top_p is not None else _to_float(runtime.get("top_p"))
    effective_top_k = top_k if top_k is not None else _to_int(runtime.get("top_k"))
    effective_verbosity = verbosity if verbosity is not None else runtime.get("verbosity")
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
            verbosity=effective_verbosity,
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
