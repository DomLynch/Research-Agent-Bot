"""Tests for agent/retrieval_modes.py — Slice 6 step 1.

Foundation tests: retrieval-mode resolution + safety cap +
marginal-yield stopper. Universal across topics + domains.
"""
from __future__ import annotations

import pytest

from agent.retrieval_modes import (
    DEFAULT_PAGE_SIZE,
    GLOBAL_SAFETY_CAP,
    MarginalYieldStopper,
    SMOKE_TEST_LIMIT,
    VALID_MODES,
    resolve_params,
)


# ---------- constants ------------------------------------------------

def test_global_safety_cap_is_200k():
    """Universal circuit breaker — must be exactly 200,000.
    Hardcoded in tests on purpose so a silent change is caught."""
    assert GLOBAL_SAFETY_CAP == 200_000


def test_smoke_test_limit_is_100():
    assert SMOKE_TEST_LIMIT == 100


def test_default_page_size_is_100():
    assert DEFAULT_PAGE_SIZE == 100


# ---------- resolve_params: each mode --------------------------------

def test_calibrated_is_the_default_mode():
    """Default = calibrated (wave-based + marginal-yield stop)."""
    p = resolve_params()
    assert p.mode == "calibrated"
    assert p.safety_cap == GLOBAL_SAFETY_CAP
    assert p.use_marginal_yield_stop is True
    assert p.use_wave_orchestration is True
    assert p.page_size == DEFAULT_PAGE_SIZE


def test_smoke_mode_uses_small_cap_no_waves():
    p = resolve_params(mode="smoke")
    assert p.is_smoke is True
    assert p.safety_cap == SMOKE_TEST_LIMIT
    assert p.use_marginal_yield_stop is False
    assert p.use_wave_orchestration is False


def test_exhaustive_mode_skips_marginal_yield_stop():
    """Exhaustive pulls until source-exhaustion; no early stop."""
    p = resolve_params(mode="exhaustive")
    assert p.use_marginal_yield_stop is False
    assert p.use_wave_orchestration is True
    assert p.safety_cap == GLOBAL_SAFETY_CAP


def test_snowball_mode_uses_yield_stop_no_wave():
    """Snowball follows refs/cited-by — wave orchestration not
    applicable, but marginal-yield stop still bounds the chain."""
    p = resolve_params(mode="snowball")
    assert p.use_wave_orchestration is False
    assert p.use_marginal_yield_stop is True


# ---------- overrides -----------------------------------------------

def test_safety_cap_override_applies():
    p = resolve_params(mode="calibrated", safety_cap_override=10_000)
    assert p.safety_cap == 10_000
    # Other settings unchanged
    assert p.use_marginal_yield_stop is True


def test_page_size_override_applies():
    p = resolve_params(
        mode="calibrated", page_size_override=50,
    )
    assert p.page_size == 50


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        resolve_params(mode="totally_unknown_mode")  # type: ignore[arg-type]


def test_valid_modes_set_is_explicit():
    assert VALID_MODES == frozenset((
        "smoke", "calibrated", "exhaustive", "snowball",
    ))


def test_params_dataclass_is_frozen():
    """RetrievalParams is frozen — caller can't accidentally mutate
    cap mid-run."""
    from dataclasses import FrozenInstanceError
    p = resolve_params()
    with pytest.raises(FrozenInstanceError):
        p.safety_cap = 1  # type: ignore[misc]


def test_description_describes_mode():
    assert "calibrated" in resolve_params("calibrated").description
    assert "exhaustive" in resolve_params("exhaustive").description
    assert "smoke" in resolve_params("smoke").description.lower()
    assert "snowball" in resolve_params("snowball").description


# ---------- MarginalYieldStopper -----------------------------------

def test_stopper_does_not_stop_below_window_size():
    """No stop until we've seen at least window_size pages."""
    s = MarginalYieldStopper(window_size=5)
    for _ in range(4):
        s.record_page(seen=100, new_deduped=0, core_candidates=0)
    stop, reason = s.should_stop()
    assert not stop and not reason


def test_stopper_triggers_on_low_new_dedup():
    """Last 5 pages avg <2% new-deduped → STOP."""
    s = MarginalYieldStopper(window_size=5,
                              new_dedup_pct_floor=0.02)
    for _ in range(5):
        s.record_page(
            seen=100, new_deduped=1, core_candidates=10,
        )
    stop, reason = s.should_stop()
    assert stop
    assert "marginal yield" in reason
    assert "1.0%" in reason


def test_stopper_triggers_on_low_core_yield():
    """Last 5 pages avg <1% core_candidate → STOP, even when new
    dedup is healthy (the dedup-only path is still finding NEW
    papers but they're all off-thesis noise)."""
    s = MarginalYieldStopper(
        window_size=5,
        new_dedup_pct_floor=0.0,  # disable new-dedup floor
        core_candidate_pct_floor=0.01,
    )
    for _ in range(5):
        s.record_page(
            seen=100, new_deduped=80, core_candidates=0,
        )
    stop, reason = s.should_stop()
    assert stop
    assert "core candidate yield" in reason


def test_stopper_does_not_trigger_when_yield_healthy():
    s = MarginalYieldStopper(window_size=5)
    for _ in range(5):
        s.record_page(
            seen=100, new_deduped=80, core_candidates=20,
        )
    stop, reason = s.should_stop()
    assert not stop


def test_stopper_stats_summary():
    s = MarginalYieldStopper(window_size=5)
    for _ in range(3):
        s.record_page(seen=100, new_deduped=50, core_candidates=10)
    stats = s.stats()
    assert stats["pages"] == 3
    assert stats["total_seen"] == 300
    assert stats["total_new_deduped"] == 150
    assert stats["total_core_candidates"] == 30


def test_stopper_stats_zero_pages():
    s = MarginalYieldStopper()
    assert s.stats() == {"pages": 0, "total_seen": 0}
