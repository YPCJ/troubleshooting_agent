from __future__ import annotations

import pytest
from types import SimpleNamespace

from llm import chat_reply
from llm.config import create_profile, resolve_model_runtime
from llm.connections import create_connection, get_connection, list_connections
from llm.providers import create_provider, registered_provider_names
from llm.providers.openai_provider import OpenAIProvider


def test_custom_connection_is_available_to_model_profiles(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROFILES_DB_PATH", str(tmp_path / "profiles.sqlite3"))
    item = create_connection(
        "deepseek_test",
        "DeepSeek Test",
        "openai_chat",
        "https://api.example.test/v1/",
        "DEEPSEEK_TEST_API_KEY",
    )
    assert item["base_url"] == "https://api.example.test/v1"
    assert get_connection("deepseek_test") is not None
    assert "deepseek_test" in registered_provider_names()
    assert any(row["id"] == "deepseek_test" for row in list_connections())

    create_profile("deepseek_model", provider="deepseek_test", model_name="deepseek-v4-pro")
    runtime = resolve_model_runtime(profile_name="deepseek_model")
    provider = create_provider(runtime["provider"], runtime["profile"])
    assert isinstance(provider, OpenAIProvider)
    assert provider._profile["base_url"] == "https://api.example.test/v1"
    assert provider._profile["api_key_envs"] == ["DEEPSEEK_TEST_API_KEY"]


def test_custom_connection_rejects_invalid_transport_and_duplicate_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROFILES_DB_PATH", str(tmp_path / "profiles.sqlite3"))
    with pytest.raises(ValueError, match="HTTPS"):
        create_connection("remote", "Remote", "openai_chat", "http://api.example.test/v1", "TEST_API_KEY")
    with pytest.raises(ValueError, match="协议"):
        create_connection("native", "Native", "gemini_native", "https://example.test", "TEST_API_KEY")
    create_connection("custom", "Custom", "openai_chat", "https://example.test/v1", "TEST_API_KEY")
    with pytest.raises(ValueError, match="已存在"):
        create_connection("custom", "Again", "openai_chat", "https://example.test/v1", "TEST_API_KEY")


def test_trusted_intranet_http_requires_explicit_opt_in(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROFILES_DB_PATH", str(tmp_path / "profiles.sqlite3"))
    monkeypatch.setenv("ALLOW_INSECURE_LLM_HTTP", "1")
    connection = create_connection(
        "intranet", "Intranet", "openai_chat", "http://10.0.0.8:8000/v1", "INTRANET_LLM_API_KEY"
    )
    assert connection["base_url"] == "http://10.0.0.8:8000/v1"


def test_custom_connection_reaches_chat_completions(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROFILES_DB_PATH", str(tmp_path / "profiles.sqlite3"))
    monkeypatch.setenv("CUSTOM_TEST_KEY", "test-secret")
    create_connection("custom_chat", "Custom Chat", "openai_chat", "https://example.test/v1", "CUSTOM_TEST_KEY")
    create_profile("custom_chat_model", provider="custom_chat", model_name="test-model")
    observed: dict[str, object] = {}

    def fake_client(*, api_key: str, base_url: str):
        observed["api_key"] = api_key
        observed["base_url"] = base_url

        def create(**request):
            observed["request"] = request
            message = SimpleNamespace(content="Hello world", tool_calls=[])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr("llm.providers.openai_provider.OpenAI", fake_client)
    reply = chat_reply([{"role": "user", "content": "hello"}], profile_name="custom_chat_model")
    assert reply["content"] == "Hello world"
    assert observed["api_key"] == "test-secret"
    assert observed["base_url"] == "https://example.test/v1"
    assert observed["request"]["model"] == "test-model"
