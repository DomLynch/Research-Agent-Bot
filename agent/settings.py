"""Runtime configuration via environment variables.

Single source of truth for every env var the V1 runtime reads. Defaults are
sensible for local dev; production overrides come from the systemd unit's
EnvironmentFile. For local dev a `.env` at the repo root is loaded into
os.environ at `load_settings()` time — already-set vars always win, so
CI / test envs that export keys explicitly are unaffected.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv_if_present() -> None:
    """Read `.env` at REPO_ROOT and populate os.environ for UNSET keys.

    Stdlib-only KEY=VALUE parser. Existing env vars are NEVER overridden,
    so test isolation and explicit `export FOO=bar` always win. Lines
    starting with `#`, blank lines, and lines without `=` are skipped;
    surrounding quotes on values are stripped. Silent no-op if no .env
    exists — the systemd unit on production sets vars via EnvironmentFile,
    no .env there.
    """
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
    final_layer_reviewer_model: str  # Grok 4.3 — final fail-safe

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
        mimo_base_url=os.environ.get(
            "MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"
        ),
        # Day 10.16h: bumped 60→180. The original 60s ceiling was set
        # for short fact-extraction calls (a few hundred output tokens).
        # Day 10.16's full-paper writer asks for 1,500-1,800 word
        # sections — 2,000+ output tokens at MiMo's tokenization. Those
        # routinely take 60-120s of generation time on the production
        # endpoint, so the 60s httpx timeout was killing the request
        # before MiMo finished, forcing the chain to fall back to
        # Ministral (smaller, faster, but worse prose). 180s gives MiMo
        # the headroom to complete on its first attempt.
        mimo_timeout_sec=_float("MIMO_TIMEOUT_SEC", 180.0),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", "").strip(),
        openrouter_base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        judge_model=os.environ.get("JUDGE_MODEL", "google/gemma-4-31b-it"),
        fallback_model=os.environ.get("FALLBACK_MODEL", "mistralai/mistral-small-2603"),
        final_layer_reviewer_model=os.environ.get(
            "FINAL_LAYER_REVIEWER_MODEL", "x-ai/grok-4.3"
        ),
        bot_enabled=_bool("BOT_ENABLED", True),
        daily_cost_cap_usd=_float("DAILY_COST_CAP_USD", 10.0),
        dashboard_host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        dashboard_port=int(os.environ.get("DASHBOARD_PORT", "8791")),
        runs_dir=os.environ.get("RUNS_DIR", "runs"),
    )
