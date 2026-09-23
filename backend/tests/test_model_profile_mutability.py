from __future__ import annotations

import pytest

from llm.config import create_profile, resolve_model_runtime, update_profile


def test_existing_profile_only_allows_sampling_updates(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROFILES_DB_PATH", str(tmp_path / "profiles.sqlite3"))
    create_profile(
        "immutable_entry",
        provider="gemini",
        model_name="gemini-test-model",
        base_url="https://example.invalid",
        temperature=0.2,
    )

    updated = update_profile(
        "immutable_entry",
        top_p=0.9,
        replace_generation_overrides=True,
    )
    assert "temperature" not in updated["profile"]
    assert updated["profile"]["top_p"] == 0.9

    inherited = update_profile("immutable_entry", clear_generation_overrides=True)
    assert "top_p" not in inherited["profile"]

    with pytest.raises(ValueError, match="provider 不可修改"):
        update_profile("immutable_entry", provider="aliyun")
    with pytest.raises(ValueError, match="model_name 不可修改"):
        update_profile("immutable_entry", model_name="another-model")
    with pytest.raises(ValueError, match="base_url 不可修改"):
        update_profile("immutable_entry", base_url="https://another.invalid")


def test_sampling_and_output_modes_are_independent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROFILES_DB_PATH", str(tmp_path / "profiles.sqlite3"))
    created = create_profile(
        "semantic_settings",
        provider="gemini",
        model_name="gemini-test-model",
        sampling_mode="stable",
        output_mode="custom_limit",
        max_output_tokens=2048,
        verbosity="low",
    )

    assert created["profile"]["sampling_mode"] == "stable"
    assert created["profile"]["temperature"] == 0.2
    assert created["profile"]["output_mode"] == "custom_limit"
    assert created["profile"]["max_output_tokens"] == 2048
    assert created["profile"]["verbosity"] == "low"

    sampling_default = update_profile(
        "semantic_settings",
        sampling_mode="provider_default",
    )
    assert "sampling_mode" not in sampling_default["profile"]
    assert "temperature" not in sampling_default["profile"]
    assert sampling_default["profile"]["output_mode"] == "custom_limit"
    assert sampling_default["profile"]["max_output_tokens"] == 2048
    assert sampling_default["profile"]["verbosity"] == "low"

    update_profile(
        "semantic_settings",
        sampling_mode="flexible",
    )
    output_default = update_profile(
        "semantic_settings",
        output_mode="provider_default",
    )
    assert output_default["profile"]["sampling_mode"] == "flexible"
    assert output_default["profile"]["temperature"] == 0.8
    assert "output_mode" not in output_default["profile"]
    assert "max_output_tokens" not in output_default["profile"]

    runtime = resolve_model_runtime(profile_name="semantic_settings")
    assert runtime["sampling_mode"] == "flexible"
    assert runtime["output_mode"] == "provider_default"
    assert runtime["generation_style"] == "flexible"
    assert runtime["verbosity"] == "low"

    cleared_verbosity = update_profile("semantic_settings", verbosity=None)
    assert "verbosity" not in cleared_verbosity["profile"]


def test_generation_style_alias_and_legacy_clear_remove_semantic_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROFILES_DB_PATH", str(tmp_path / "profiles.sqlite3"))
    created = create_profile(
        "legacy_generation_mode",
        provider="gemini",
        model_name="gemini-test-model",
        generation_style="custom",
        temperature=0.4,
        output_mode="custom_limit",
        max_output_tokens=512,
        verbosity="high",
    )
    assert created["profile"]["sampling_mode"] == "custom"

    cleared = update_profile(
        "legacy_generation_mode",
        clear_generation_overrides=True,
    )
    for key in (
        "sampling_mode",
        "generation_style",
        "temperature",
        "top_p",
        "top_k",
        "output_mode",
        "max_output_tokens",
        "verbosity",
    ):
        assert key not in cleared["profile"]

    runtime = resolve_model_runtime(profile_name="legacy_generation_mode")
    assert runtime["sampling_mode"] == "provider_default"
    assert runtime["generation_style"] == "recommended"
    assert runtime["output_mode"] == "provider_default"
    assert runtime["verbosity"] is None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sampling_mode", "random", "sampling_mode"),
        ("output_mode", "random", "output_mode"),
        ("verbosity", "random", "verbosity"),
    ],
)
def test_generation_setting_enums_are_validated(
    tmp_path,
    monkeypatch,
    field: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv("MODEL_PROFILES_DB_PATH", str(tmp_path / "profiles.sqlite3"))
    kwargs = {field: value}
    with pytest.raises(ValueError, match=message):
        create_profile(
            "invalid_settings",
            provider="gemini",
            model_name="gemini-test-model",
            **kwargs,
        )
