from __future__ import annotations

from typing import Any, Iterator, Mapping

from .gemini_impl import chat_reply as gemini_chat_reply
from .gemini_impl import chat_reply_stream as gemini_chat_reply_stream
from .gemini_impl import get_gemini_model_capabilities, list_gemini_models


class GeminiProvider:
    def __init__(self, profile: Mapping[str, Any] | None = None):
        self._profile = dict(profile or {})

    def list_models(self) -> list[str]:
        return list_gemini_models(profile=self._profile)

    def get_model_capabilities(self, model_name: str) -> Mapping[str, Any]:
        return get_gemini_model_capabilities(model_name, profile=self._profile)

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
        return gemini_chat_reply(
            messages,
            tools=tools,
            model_name=model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            top_p=top_p,
            top_k=top_k,
            profile=self._profile,
        )

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
        yield from gemini_chat_reply_stream(
            messages,
            tools=tools,
            model_name=model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            top_p=top_p,
            top_k=top_k,
            profile=self._profile,
        )
