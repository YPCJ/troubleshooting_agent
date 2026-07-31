from __future__ import annotations

from typing import Any, Iterator, Mapping, Protocol


class LLMProvider(Protocol):
    def chat(
        self,
        messages: list[Mapping[str, Any]],
        *,
        tools: Any = None,
        model_name: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = 4096,
    ) -> Mapping[str, Any]:
        ...

    def chat_stream(
        self,
        messages: list[Mapping[str, Any]],
        *,
        tools: Any = None,
        model_name: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = 4096,
    ) -> Iterator[dict[str, Any]]:
        ...
