from __future__ import annotations

from pathlib import Path

import pytest

from agent import settings as settings_module


@pytest.fixture
def clean_granite_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module, "_REPO_ROOT", tmp_path)
    for key in (
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "GRANITE_ARBITRATOR_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_granite_defaults_and_no_key_disabled(clean_granite_env: None) -> None:
    settings = settings_module.load_settings()
    assert settings.granite_arbitrator_api_key == ""
    assert settings.granite_arbitrator_enabled is False
    assert settings.granite_arbitrator_base_url == "https://openrouter.ai/api/v1"
    assert settings.granite_arbitrator_model == "ibm-granite/granite-4.1-8b"


def test_granite_env_overrides_enable_scaffold(
    clean_granite_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "granite-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("GRANITE_ARBITRATOR_MODEL", "custom/granite")
    settings = settings_module.load_settings()
    assert settings.granite_arbitrator_api_key == "granite-key"
    assert settings.granite_arbitrator_enabled is True
    assert settings.granite_arbitrator_base_url == "https://example.test/v1"
    assert settings.granite_arbitrator_model == "custom/granite"
