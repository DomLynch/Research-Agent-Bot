"""Tests for agent.effect_normalizer — raw study reports → EffectRow."""
from __future__ import annotations

import math

import pytest

from agent.effect_normalizer import (
    RawBinary,
    RawContinuous,
    normalize_log_or,
    normalize_log_rr,
    normalize_md,
    normalize_passthrough,
    normalize_record,
)


# ---- RawContinuous validation ---------------------------------------------


def test_raw_continuous_valid() -> None:
    r = RawContinuous("S", 5.0, 1.0, 30, 3.0, 1.0, 30)
    assert r.n_t == 30


@pytest.mark.parametrize("n_t", [0, -1])
def test_raw_continuous_rejects_non_positive_n(n_t) -> None:
    with pytest.raises(ValueError, match="n_t"):
        RawContinuous("S", 5.0, 1.0, n_t, 3.0, 1.0, 30)


def test_raw_continuous_rejects_negative_sd() -> None:
    with pytest.raises(ValueError, match="sd_t"):
        RawContinuous("S", 5.0, -0.1, 30, 3.0, 1.0, 30)


def test_raw_continuous_rejects_nan_mean() -> None:
    with pytest.raises(ValueError, match="mean_t"):
        RawContinuous("S", float("nan"), 1.0, 30, 3.0, 1.0, 30)


def test_raw_continuous_rejects_empty_study_id() -> None:
    with pytest.raises(ValueError, match="study_id"):
        RawContinuous("", 5.0, 1.0, 30, 3.0, 1.0, 30)


# ---- RawBinary validation -------------------------------------------------


def test_raw_binary_valid() -> None:
    r = RawBinary("S", 20, 100, 10, 100)
    assert r.events_t == 20


def test_raw_binary_rejects_events_exceeding_n() -> None:
    with pytest.raises(ValueError, match="exceeds n_t"):
        RawBinary("S", 200, 100, 10, 100)


def test_raw_binary_rejects_negative_events() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        RawBinary("S", -1, 100, 10, 100)


# ---- normalize_md ---------------------------------------------------------


def test_normalize_md_textbook() -> None:
    """mean_t=10±2 (n=50) vs mean_c=8±2 (n=50) → diff=2, SE=0.4."""
    r = normalize_md(RawContinuous("S", 10.0, 2.0, 50, 8.0, 2.0, 50))
    assert r.effect == pytest.approx(2.0)
    assert r.se == pytest.approx(0.4)
    assert r.metric == "MD"
    assert r.n == 100


def test_normalize_md_unequal_arms() -> None:
    """SE formula handles unequal arm SDs and sample sizes."""
    r = normalize_md(RawContinuous("S", 10.0, 2.0, 40, 8.0, 3.0, 60))
    expected_se = math.sqrt(4 / 40 + 9 / 60)
    assert r.se == pytest.approx(expected_se)


def test_normalize_md_rejects_dual_zero_sd() -> None:
    with pytest.raises(ValueError, match="zero SD"):
        normalize_md(RawContinuous("S", 5.0, 0.0, 30, 3.0, 0.0, 30))


def test_normalize_md_allows_one_zero_sd_other_nonzero() -> None:
    """One arm exactly known is rare but mathematically defined."""
    r = normalize_md(RawContinuous("S", 5.0, 0.0, 30, 3.0, 1.0, 30))
    assert r.se == pytest.approx(math.sqrt(1 / 30))


# ---- normalize_log_rr -----------------------------------------------------


def test_normalize_log_rr_textbook() -> None:
    """events 20/100 vs 10/100 → log(2) ≈ 0.6931, SE = sqrt(0.13)."""
    r = normalize_log_rr(RawBinary("S", 20, 100, 10, 100))
    assert r.effect == pytest.approx(math.log(2))
    assert r.se == pytest.approx(math.sqrt(0.13))
    assert r.metric == "log_RR"


def test_normalize_log_rr_zero_event_arm_rejected() -> None:
    with pytest.raises(ValueError, match="zero-event arm"):
        normalize_log_rr(RawBinary("S", 0, 100, 10, 100))
    with pytest.raises(ValueError, match="zero-event arm"):
        normalize_log_rr(RawBinary("S", 10, 100, 0, 100))


def test_normalize_log_rr_full_event_rate_rejected() -> None:
    with pytest.raises(ValueError, match="≥1"):
        normalize_log_rr(RawBinary("S", 100, 100, 10, 100))


# ---- normalize_log_or -----------------------------------------------------


def test_normalize_log_or_textbook() -> None:
    """events 20/100 vs 10/100 → log(2.25) ≈ 0.8109, SE ≈ 0.4167."""
    r = normalize_log_or(RawBinary("S", 20, 100, 10, 100))
    assert r.effect == pytest.approx(math.log(2.25))
    assert r.se == pytest.approx(math.sqrt(1 / 20 + 1 / 80 + 1 / 10 + 1 / 90))
    assert r.metric == "log_OR"


def test_normalize_log_or_zero_cell_rejected() -> None:
    """Saturated treatment arm (b=0) is a zero cell."""
    with pytest.raises(ValueError, match="zero cell"):
        normalize_log_or(RawBinary("S", 100, 100, 10, 100))


# ---- passthrough + dispatch ------------------------------------------------


def test_normalize_passthrough_preserves_metric_label() -> None:
    r = normalize_passthrough(study_id="S", effect=0.5, se=0.1, n=80, metric="HR")
    assert r.metric == "HR"
    assert r.effect == pytest.approx(0.5)


def test_normalize_record_dispatches_passthrough() -> None:
    r = normalize_record(
        {"study_id": "A", "effect": 0.3, "se": 0.1, "n": 40, "metric": "MD"}
    )
    assert r.metric == "MD"


def test_normalize_record_dispatches_continuous() -> None:
    r = normalize_record({
        "study_id": "B", "mean_t": 5, "sd_t": 1, "n_t": 30,
        "mean_c": 3, "sd_c": 1, "n_c": 30,
    })
    assert r.metric == "MD"
    assert r.effect == pytest.approx(2.0)


def test_normalize_record_dispatches_binary_log_rr_default() -> None:
    r = normalize_record({
        "study_id": "C", "events_t": 30, "n_t": 100,
        "events_c": 20, "n_c": 100,
    })
    assert r.metric == "log_RR"


def test_normalize_record_dispatches_binary_log_or_when_requested() -> None:
    r = normalize_record({
        "study_id": "D", "events_t": 30, "n_t": 100,
        "events_c": 20, "n_c": 100, "metric": "log_OR",
    })
    assert r.metric == "log_OR"


def test_normalize_record_rejects_ambiguous_shape() -> None:
    with pytest.raises(ValueError, match="no recognised effect-size shape"):
        normalize_record({"study_id": "Z", "irrelevant": 1})


def test_normalize_record_rejects_missing_study_id() -> None:
    with pytest.raises(ValueError, match="study_id"):
        normalize_record({"effect": 0.1, "se": 0.05})


def test_normalize_record_rejects_precomputed_effect_without_metric() -> None:
    with pytest.raises(ValueError, match="missing metric"):
        normalize_record({"study_id": "E", "effect": 99.0, "se": 0.5, "n": 40})


def test_normalize_record_rejects_ambiguous_shapes() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        normalize_record({
            "study_id": "F", "effect": 99.0, "se": 0.5, "n": 40, "metric": "MD",
            "mean_t": 5, "sd_t": 1, "n_t": 20, "mean_c": 3, "sd_c": 1, "n_c": 20,
        })
