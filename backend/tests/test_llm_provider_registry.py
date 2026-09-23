from __future__ import annotations

from typing import Any, Iterator, Mapping

from llm.providers import create_provider, register_provider, registered_provider_names, unregister_provider


class _TestProvider:
    def __init__(self, profile: Mapping[str, Any]):
        self.profile = dict(profile)

    def list_models(self) -> list[str]:
        return ["test-model"]

    def chat(self, messages: list[Mapping[str, Any]], **_: Any) -> Mapping[str, Any]:
        return {"content": str(self.profile.get("marker", "")), "tool_calls": []}

    def chat_stream(self, messages: list[Mapping[str, Any]], **_: Any) -> Iterator[dict[str, Any]]:
        yield {"type": "done", "content": "", "tool_calls": []}


def test_builtin_providers_are_registered() -> None:
    assert {"aliyun", "gemini", "openai"}.issubset(registered_provider_names())


def test_custom_provider_can_be_added_without_factory_changes() -> None:
    register_provider("unit_test_provider", _TestProvider, replace=True)
    try:
        provider = create_provider("unit_test_provider", {"marker": "registry-ok"})

        assert provider.list_models() == ["test-model"]
        assert provider.chat([])["content"] == "registry-ok"
    finally:
        unregister_provider("unit_test_provider")


def test_factory_preserves_explicit_zero_temperature(monkeypatch) -> None:
    from llm import factory

    captured: dict[str, Any] = {}

    class _CapturingProvider(_TestProvider):
        def chat(self, messages: list[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
            captured.update(kwargs)
            return {"content": "ok", "tool_calls": []}

    monkeypatch.setattr(
        factory,
        "resolve_model_runtime",
        lambda **_: {
            "provider": "unit",
            "model_name": "test-model",
            "temperature": 0,
            "max_output_tokens": None,
            "top_p": None,
            "top_k": None,
            "verbosity": None,
            "profile": {},
        },
    )
    monkeypatch.setattr(factory, "create_provider", lambda *_: _CapturingProvider({}))

    factory.chat_reply([{"role": "user", "content": "hello"}])

    assert captured["temperature"] == 0
    assert captured["max_output_tokens"] is None
    assert captured["verbosity"] is None


def test_factory_forwards_profile_verbosity(monkeypatch) -> None:
    from llm import factory

    captured: dict[str, Any] = {}

    class _CapturingProvider(_TestProvider):
        def chat(self, messages: list[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
            captured.update(kwargs)
            return {"content": "ok", "tool_calls": []}

    monkeypatch.setattr(
        factory,
        "resolve_model_runtime",
        lambda **_: {
            "provider": "unit",
            "model_name": "test-model",
            "temperature": None,
            "max_output_tokens": None,
            "top_p": None,
            "top_k": None,
            "verbosity": "high",
            "profile": {},
        },
    )
    monkeypatch.setattr(factory, "create_provider", lambda *_: _CapturingProvider({}))

    factory.chat_reply([{"role": "user", "content": "hello"}])

    assert captured["verbosity"] == "high"
