from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv_if_present() -> None:
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    # Provider — primary writer
    mimo_api_key: str
    mimo_model: str
    mimo_base_url: str
    mimo_timeout_sec: float

    # OpenRouter — judge primary + shared fallback for writer & judge
    openrouter_api_key: str
    openrouter_base_url: str
    judge_model: str       # Gemma 4 (primary judge)
    fallback_model: str    # Ministral — shared fallback for MiMo writer AND Gemma judge
    final_layer_reviewer_model: str  # final fail-safe reviewer

    # Safety rails
    bot_enabled: bool
    daily_cost_cap_usd: float

    # Dashboard
    dashboard_host: str
    dashboard_port: int

    # Run logging
    runs_dir: str

def load_settings() -> Settings:
    _load_dotenv_if_present()
    return Settings(
        mimo_api_key=os.environ.get("MIMO_API_KEY", "").strip(),
        mimo_model=os.environ.get("MIMO_MODEL", "mimo-v2.5-pro"),
        mimo_base_url=os.environ.get("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
        mimo_timeout_sec=_float("MIMO_TIMEOUT_SEC", 180.0),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", "").strip(),
        openrouter_base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        judge_model=os.environ.get("JUDGE_MODEL", "google/gemma-4-31b-it"),
        fallback_model=os.environ.get("FALLBACK_MODEL", "mistralai/mistral-small-2603"),
        final_layer_reviewer_model=os.environ.get("FINAL_LAYER_REVIEWER_MODEL", "google/gemini-3.1-flash-lite:exacto"),
        bot_enabled=_bool("BOT_ENABLED", True),
        daily_cost_cap_usd=_float("DAILY_COST_CAP_USD", 10.0),
        dashboard_host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        dashboard_port=int(os.environ.get("DASHBOARD_PORT", "8791")),
        runs_dir=os.environ.get("RUNS_DIR", "runs"),
    )
