"""Runtime configuration via environment variables.

Single source of truth for every env var the V1 runtime reads. Defaults are
sensible for local dev; production overrides come from the systemd unit's
EnvironmentFile.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    # Provider
    mimo_api_key: str
    mimo_model: str
    mimo_base_url: str
    mimo_timeout_sec: float

    # Safety rails
    bot_enabled: bool
    daily_cost_cap_usd: float

    # Dashboard
    dashboard_host: str
    dashboard_port: int

    # Run logging
    runs_dir: str


def load_settings() -> Settings:
    return Settings(
        mimo_api_key=os.environ.get("MIMO_API_KEY", "").strip(),
        mimo_model=os.environ.get("MIMO_MODEL", "mimo-v2.5-pro"),
        mimo_base_url=os.environ.get(
            "MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"
        ),
        mimo_timeout_sec=_float("MIMO_TIMEOUT_SEC", 60.0),
        bot_enabled=_bool("BOT_ENABLED", True),
        daily_cost_cap_usd=_float("DAILY_COST_CAP_USD", 10.0),
        dashboard_host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        dashboard_port=int(os.environ.get("DASHBOARD_PORT", "8791")),
        runs_dir=os.environ.get("RUNS_DIR", "runs"),
    )
