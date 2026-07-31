from __future__ import annotations

from typing import Any, Iterator, Mapping

from ai_gemini import chat_reply as gemini_chat_reply
from ai_gemini import chat_reply_stream as gemini_chat_reply_stream
from ai_gemini import list_gemini_models


class GeminiProvider:
    def list_models(self) -> list[str]:
        return list_gemini_models()

    def chat(
        self,
        messages: list[Mapping[str, Any]],
        *,
        tools: Any = None,
        model_name: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = 4096,
        top_p: float | None = None,
        top_k: int | None = None,
    ) -> Mapping[str, Any]:
        return gemini_chat_reply(
            messages,
            tools=tools,
            model_name=model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            top_p=top_p,
            top_k=top_k,
        )

    def chat_stream(
        self,
        messages: list[Mapping[str, Any]],
        *,
        tools: Any = None,
        model_name: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = 4096,
        top_p: float | None = None,
        top_k: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        yield from gemini_chat_reply_stream(
            messages,
            tools=tools,
            model_name=model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            top_p=top_p,
            top_k=top_k,
        )
