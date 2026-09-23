from __future__ import annotations

from typing import Any, Iterator, Mapping, Protocol


class LLMProvider(Protocol):
    def list_models(self) -> list[str]:
        ...

    def get_model_capabilities(self, model_name: str) -> Mapping[str, Any]:
        ...

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
        ...

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
        ...
