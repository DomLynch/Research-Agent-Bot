"""Tests for `agent.settings`.

Two surfaces:

  1. `_load_dotenv_if_present` — stdlib KEY=VALUE parser. Must populate
     os.environ ONLY for unset keys, never override what's already set,
     and survive malformed lines / comments / blanks. The semantic
     contract matches python-dotenv's load_dotenv(override=False) so
     any future swap to that lib is a drop-in replacement.

  2. `load_settings` — defaults wire correctly when nothing is set, and
     dotenv values reach the dataclass when the test repo root has a
     `.env`. Both paths under test_isolation: the test mutates a
     temporary REPO_ROOT, never the real one.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent import settings as settings_module


@pytest.fixture
def isolated_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `_load_dotenv_if_present` at a clean tmp dir and clear all
    keys it might touch. Each test starts from a known-empty env."""
    monkeypatch.setattr(settings_module, "_REPO_ROOT", tmp_path)
    for k in (
        "MINIMAX_API_KEY", "MIMO_API_KEY", "OPENROUTER_API_KEY",
        "MINIMAX_MODEL", "MINIMAX_BASE_URL", "MINIMAX_TIMEOUT_SEC",
        "MIMO_MODEL", "MIMO_BASE_URL", "MIMO_TIMEOUT_SEC",
        "WRITER_MODEL", "WRITER_PROVIDER", "WRITER_TIMEOUT_SEC", "OPENROUTER_BASE_URL",
        "JUDGE_MODEL", "FALLBACK_MODEL",
        "DOTENV_TEST_KEY", "DOTENV_QUOTED", "FINAL_LAYER_REVIEWER_MODEL",
        "DOTENV_OVERRIDE_TEST",
    ):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_dotenv_absent_is_silent_noop(isolated_dotenv: Path) -> None:
    assert not (isolated_dotenv / ".env").exists()
    settings_module._load_dotenv_if_present()  # must not raise
    assert os.environ.get("DOTENV_TEST_KEY") is None


def test_dotenv_populates_unset_keys(isolated_dotenv: Path) -> None:
    (isolated_dotenv / ".env").write_text(
        "DOTENV_TEST_KEY=hello\n"
        'DOTENV_QUOTED="quoted-value"\n',
        encoding="utf-8",
    )
    settings_module._load_dotenv_if_present()
    assert os.environ["DOTENV_TEST_KEY"] == "hello"
    assert os.environ["DOTENV_QUOTED"] == "quoted-value"


def test_dotenv_does_not_override_existing_env(
    isolated_dotenv: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing env wins — CI exporting MIMO_API_KEY=ci-key must not be
    silently replaced by a stale .env on the runner."""
    monkeypatch.setenv("DOTENV_OVERRIDE_TEST", "from-env")
    (isolated_dotenv / ".env").write_text(
        "DOTENV_OVERRIDE_TEST=from-dotenv\n",
        encoding="utf-8",
    )
    settings_module._load_dotenv_if_present()
    assert os.environ["DOTENV_OVERRIDE_TEST"] == "from-env"


def test_dotenv_skips_comments_blanks_and_malformed(
    isolated_dotenv: Path,
) -> None:
    (isolated_dotenv / ".env").write_text(
        "\n"
        "# this is a comment\n"
        "  # indented comment\n"
        "MALFORMED_NO_EQUALS\n"
        "=value-with-no-key\n"
        "DOTENV_TEST_KEY=ok\n",
        encoding="utf-8",
    )
    settings_module._load_dotenv_if_present()
    assert os.environ["DOTENV_TEST_KEY"] == "ok"


def test_load_settings_defaults_when_unset(
    isolated_dotenv: Path,
) -> None:
    """No .env, no env vars — Settings still constructs with documented
    defaults; api_keys are empty strings (the chain skips empty-keyed
    specs, so partial-config is a recoverable state)."""
    s = settings_module.load_settings()
    assert s.minimax_api_key == ""
    assert s.openrouter_api_key == ""
    assert s.minimax_model == "gpt-5.6-sol"
    assert s.minimax_base_url == "codex://chatgpt"
    assert s.judge_model == "gpt-5.6-terra"
    assert s.fallback_model == "z-ai/glm-5.3-flash"
    assert s.final_layer_reviewer_model == "gpt-5.6-terra"


def test_load_settings_reads_dotenv(isolated_dotenv: Path) -> None:
    (isolated_dotenv / ".env").write_text(
        "MIMO_API_KEY=mimo-test-key\n"
        "OPENROUTER_API_KEY=or-test-key\n",
        encoding="utf-8",
    )
    s = settings_module.load_settings()
    assert s.minimax_api_key == ""
    assert s.openrouter_api_key == "or-test-key"


def test_load_settings_never_sends_legacy_keys_to_openrouter(
    isolated_dotenv: Path,
) -> None:
    (isolated_dotenv / ".env").write_text(
        "MINIMAX_API_KEY=minimax-test-key\n"
        "MIMO_API_KEY=mimo-test-key\n",
        encoding="utf-8",
    )
    s = settings_module.load_settings()
    assert s.minimax_api_key == ""


def test_load_settings_ignores_stale_writer_provider_names(
    isolated_dotenv: Path,
) -> None:
    (isolated_dotenv / ".env").write_text(
        "MINIMAX_MODEL=MiniMax-M3\n"
        "MINIMAX_BASE_URL=https://api.minimax.io/anthropic\n"
        "MINIMAX_TIMEOUT_SEC=30\n"
        "MIMO_MODEL=legacy-mimo\n"
        "MIMO_BASE_URL=https://legacy.example/v1\n"
        "MIMO_TIMEOUT_SEC=9\n",
        encoding="utf-8",
    )
    s = settings_module.load_settings()
    assert s.minimax_model == "gpt-5.6-sol"
    assert s.minimax_base_url == "codex://chatgpt"
    assert s.minimax_timeout_sec == 180.0
    assert s.mimo_model == s.minimax_model


def test_load_settings_accepts_explicit_writer_configuration(
    isolated_dotenv: Path,
) -> None:
    (isolated_dotenv / ".env").write_text(
        "WRITER_PROVIDER=openrouter\n"
        "WRITER_MODEL=vendor/writer\n"
        "OPENROUTER_BASE_URL=https://openrouter.example/api/v1\n"
        "WRITER_TIMEOUT_SEC=9\n",
        encoding="utf-8",
    )
    s = settings_module.load_settings()
    assert s.minimax_model == "vendor/writer"
    assert s.minimax_base_url == "https://openrouter.example/api/v1"
    assert s.minimax_timeout_sec == 9.0


@pytest.mark.parametrize("config", ["WRITER_PROVIDER=typo", "WRITER_MODEL=z-ai/glm-5.3-flash"])
def test_codex_route_rejects_stale_or_invalid_configuration(isolated_dotenv: Path, config: str) -> None:
    (isolated_dotenv / ".env").write_text(config)
    with pytest.raises(ValueError, match="WRITER_"):
        settings_module.load_settings()


def test_real_repo_dotenv_loads_when_present() -> None:
    """The real repo's .env (if present) populates the provider key at
    `load_settings()`. This is the integration check that the live
    metformin script can run from a fresh shell without manual export."""
    real_root = Path(__file__).resolve().parent.parent
    if not (real_root / ".env").exists():
        pytest.skip("no .env at repo root — CI environment without local secrets")
    # Don't assert specific values (they're secrets); assert SHAPE: load
    # didn't crash and returned a Settings dataclass.
    s = settings_module.load_settings()
    assert isinstance(s, settings_module.Settings)
