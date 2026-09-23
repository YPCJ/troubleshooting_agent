from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

from backend import server
from llm.providers.openai_provider import OpenAIProvider


class _FakeCompletions:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        message = SimpleNamespace(content="ok", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def test_openai_reasoning_model_uses_completion_budget_and_verbosity(monkeypatch) -> None:
    completions = _FakeCompletions()
    provider = OpenAIProvider({"provider": "openai"})
    monkeypatch.setattr(
        provider,
        "_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )

    provider.chat(
        [{"role": "user", "content": "hello"}],
        model_name="gpt-5.1",
        max_output_tokens=256,
        verbosity="low",
    )

    request = completions.requests[0]
    assert request["max_completion_tokens"] == 256
    assert "max_tokens" not in request
    assert request["verbosity"] == "low"
    capabilities = provider.get_model_capabilities("gpt-5.1")
    assert capabilities["recommend_provider_defaults"] is True
    assert capabilities["verbosity"]["supported"] is True


def test_openai_compatible_provider_keeps_max_tokens(monkeypatch) -> None:
    completions = _FakeCompletions()
    provider = OpenAIProvider({"provider": "aliyun"})
    monkeypatch.setattr(
        provider,
        "_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )

    provider.chat(
        [{"role": "user", "content": "hello"}],
        model_name="qwen-max",
        max_output_tokens=512,
    )

    request = completions.requests[0]
    assert request["max_tokens"] == 512
    assert "max_completion_tokens" not in request
    assert provider.get_model_capabilities("qwen-max")["verbosity"] == {
        "supported": False,
        "choices": [],
        "default": None,
    }


def test_connection_probe_omits_model_managed_temperature(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class _Provider:
        def get_model_capabilities(self, model_name: str) -> Mapping[str, Any]:
            return {
                "recommend_provider_defaults": True,
                "parameters": {
                    "temperature": {"supported": False},
                    "max_output_tokens": {"supported": True, "max": 64},
                },
                "output": {"counts_reasoning_tokens": True},
            }

        def chat(self, messages: list[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
            captured.update(kwargs)
            return {"content": "Hello world", "tool_calls": []}

    monkeypatch.setattr(server, "create_provider", lambda *_: _Provider())
    state = server.AppState.__new__(server.AppState)

    result = state.test_model_connection(
        provider_name="openai",
        model_name="gpt-5.1",
    )

    assert result["ok"] is True
    assert "temperature" not in captured
    assert "max_output_tokens" not in captured
