from backend.fault_diagnoses_agent import _discover_app_cards
from llm.config import default_profiles


def test_sbc_offline_mode_has_only_sbc_app_and_intranet_default(monkeypatch):
    monkeypatch.setenv("AGENT_APP_MODE", "sbc")
    monkeypatch.setenv("INTRANET_LLM_MODEL", "internal-model")
    assert [item["app_id"] for item in _discover_app_cards()] == ["sbc_network_troubleshooting"]
    defaults = default_profiles()
    assert defaults["default_profile"] == "intranet_default"
    profile = defaults["profiles"]["intranet_default"]
    assert profile["provider"] == "openai"
    assert profile["model"] == "internal-model"
    assert profile["base_url"] == "${INTRANET_LLM_BASE_URL}"
    assert profile["api_key_envs"] == ["INTRANET_LLM_API_KEY"]
