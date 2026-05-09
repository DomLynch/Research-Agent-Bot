"""Tests for the Phase 5 meta-analysis primitives in agent.meta_analysis
(FE + DerSimonian-Laird random-effects).

Note: a separate `tests/test_meta_analysis.py` covers Codex's older
`scripts/meta_analysis.py` scaffold (different API, different module).
This file is kept distinct to avoid stomping Codex's surface.
"""
from __future__ import annotations

import math

import pytest

from agent.meta_analysis import (
    MIN_STUDIES,
    EffectRow,
    PoolResult,
    assert_poolable,
    pool_fixed_effect,
    pool_random_effects,
)


def _rows(triples) -> list[EffectRow]:
    """Build EffectRow list from (effect, se) pairs."""
    return [
        EffectRow(f"s{i}", e, se, 100, "MD")
        for i, (e, se) in enumerate(triples)
    ]


# ---- EffectRow validation --------------------------------------------------


def test_effect_row_valid() -> None:
    r = EffectRow("a", 0.1, 0.05, 100, "MD")
    assert r.metric == "MD"


@pytest.mark.parametrize("se", [0.0, -0.1, float("inf"), float("nan")])
def test_effect_row_rejects_bad_se(se) -> None:
    with pytest.raises(ValueError, match="se"):
        EffectRow("a", 0.1, se, 100, "MD")


def test_effect_row_rejects_non_finite_effect() -> None:
    with pytest.raises(ValueError, match="effect"):
        EffectRow("a", float("nan"), 0.1, 100, "MD")


def test_effect_row_rejects_non_positive_n() -> None:
    with pytest.raises(ValueError, match="n"):
        EffectRow("a", 0.1, 0.1, 0, "MD")


def test_effect_row_rejects_empty_study_id() -> None:
    with pytest.raises(ValueError, match="study_id"):
        EffectRow("", 0.1, 0.1, 100, "MD")


def test_effect_row_rejects_empty_metric() -> None:
    with pytest.raises(ValueError, match="metric"):
        EffectRow("a", 0.1, 0.1, 100, "")


# ---- assert_poolable -------------------------------------------------------


def test_assert_poolable_rejects_too_few_studies() -> None:
    rows = _rows([(0.1, 0.1), (0.2, 0.1)])
    with pytest.raises(ValueError, match="at least"):
        assert_poolable(rows)


def test_assert_poolable_rejects_mixed_metrics() -> None:
    rows = [
        EffectRow("a", 0.1, 0.1, 100, "MD"),
        EffectRow("b", 0.2, 0.1, 100, "log_RR"),
        EffectRow("c", 0.3, 0.1, 100, "MD"),
    ]
    with pytest.raises(ValueError, match="mixed metrics"):
        assert_poolable(rows)


def test_min_studies_constant_is_three() -> None:
    assert MIN_STUDIES == 3


# ---- Fixed-effect pooling --------------------------------------------------


def test_fixed_effect_identical_effects_zero_heterogeneity() -> None:
    rows = _rows([(0.0, 1.0)] * 3)
    r = pool_fixed_effect(rows)
    assert r.pooled_effect == pytest.approx(0.0)
    assert r.q == pytest.approx(0.0)
    assert r.i_squared == pytest.approx(0.0)
    assert r.tau_squared == pytest.approx(0.0)


def test_fixed_effect_symmetric_effects_pooled_zero_q_two() -> None:
    """Effects {-1, 0, +1}, all SE=1: FE pooled=0, Q=2."""
    rows = _rows([(-1.0, 1.0), (0.0, 1.0), (1.0, 1.0)])
    r = pool_fixed_effect(rows)
    assert r.pooled_effect == pytest.approx(0.0)
    assert r.q == pytest.approx(2.0)
    assert r.pooled_se == pytest.approx(1.0 / math.sqrt(3))
    assert r.df == 2


def test_fixed_effect_textbook_example() -> None:
    """Hand-computed reference: pooled ≈ 0.2115, Q ≈ 3.671, I² ≈ 45.5%."""
    rows = [
        EffectRow("a", 0.1, 0.1, 100, "MD"),
        EffectRow("b", 0.5, 0.2, 50, "MD"),
        EffectRow("c", 0.3, 0.15, 80, "MD"),
    ]
    r = pool_fixed_effect(rows)
    assert r.pooled_effect == pytest.approx(0.21148, abs=1e-3)
    assert r.pooled_se == pytest.approx(0.07685, abs=1e-3)
    assert r.q == pytest.approx(3.6721, abs=1e-2)
    assert r.i_squared == pytest.approx(45.54, abs=1.0)
    assert r.method == "fixed_effect"
    assert r.metric == "MD"
    assert r.n_studies == 3


def test_fixed_effect_ci_bounds_at_95_percent() -> None:
    rows = _rows([(0.5, 0.1), (0.6, 0.1), (0.4, 0.1)])
    r = pool_fixed_effect(rows)
    width = r.ci_upper - r.ci_lower
    expected = 2 * 1.95996 * r.pooled_se
    assert width == pytest.approx(expected, rel=1e-3)


def test_fixed_effect_99_percent_ci_wider_than_95() -> None:
    rows = _rows([(0.5, 0.1), (0.6, 0.1), (0.4, 0.1)])
    r95 = pool_fixed_effect(rows, ci_level=0.95)
    r99 = pool_fixed_effect(rows, ci_level=0.99)
    assert (r99.ci_upper - r99.ci_lower) > (r95.ci_upper - r95.ci_lower)


def test_fixed_effect_invalid_ci_level_raises() -> None:
    rows = _rows([(0.0, 1.0)] * 3)
    with pytest.raises(ValueError, match="ci_level"):
        pool_fixed_effect(rows, ci_level=1.5)


# ---- Random-effects (DerSimonian-Laird) pooling ----------------------------


def test_random_effects_textbook_example() -> None:
    """Hand-computed reference: RE pooled ≈ 0.252, τ² ≈ 0.0176, RE se ≈ 0.113."""
    rows = [
        EffectRow("a", 0.1, 0.1, 100, "MD"),
        EffectRow("b", 0.5, 0.2, 50, "MD"),
        EffectRow("c", 0.3, 0.15, 80, "MD"),
    ]
    r = pool_random_effects(rows)
    assert r.pooled_effect == pytest.approx(0.2519, abs=1e-3)
    assert r.tau_squared == pytest.approx(0.0176, abs=1e-2)
    assert r.pooled_se == pytest.approx(0.1128, abs=1e-2)
    assert r.method == "random_effects"


def test_random_effects_zero_tau_when_homogeneous() -> None:
    """When effects are identical, τ² should be 0 and RE = FE."""
    rows = _rows([(0.5, 0.1)] * 3)
    fe = pool_fixed_effect(rows)
    re = pool_random_effects(rows)
    assert re.tau_squared == pytest.approx(0.0)
    assert re.pooled_effect == pytest.approx(fe.pooled_effect)
    assert re.pooled_se == pytest.approx(fe.pooled_se)


def test_random_effects_tau_squared_non_negative() -> None:
    """τ² must clamp at 0 for any input."""
    rows = _rows([(0.5, 0.1), (0.5, 0.1), (0.5, 0.1)])
    r = pool_random_effects(rows)
    assert r.tau_squared >= 0.0


def test_random_effects_se_at_least_fixed_effect_se() -> None:
    """RE SE is ≥ FE SE in the presence of heterogeneity (textbook fact)."""
    rows = [
        EffectRow("a", 0.1, 0.1, 100, "MD"),
        EffectRow("b", 0.5, 0.2, 50, "MD"),
        EffectRow("c", 0.3, 0.15, 80, "MD"),
    ]
    fe = pool_fixed_effect(rows)
    re = pool_random_effects(rows)
    assert re.pooled_se >= fe.pooled_se


def test_random_effects_inherits_q_and_i2_from_fixed() -> None:
    rows = [
        EffectRow("a", 0.1, 0.1, 100, "MD"),
        EffectRow("b", 0.5, 0.2, 50, "MD"),
        EffectRow("c", 0.3, 0.15, 80, "MD"),
    ]
    fe = pool_fixed_effect(rows)
    re = pool_random_effects(rows)
    assert re.q == pytest.approx(fe.q)
    assert re.i_squared == pytest.approx(fe.i_squared)


# ---- PoolResult validation -------------------------------------------------


def test_pool_result_invalid_method_raises() -> None:
    with pytest.raises(ValueError, match="invalid method"):
        PoolResult(
            method="bogus",  # type: ignore[arg-type]
            n_studies=3, metric="MD",
            pooled_effect=0.0, pooled_se=0.1, ci_lower=-0.1, ci_upper=0.1,
            q=0.0, df=2, i_squared=0.0, tau_squared=0.0, ci_level=0.95,
        )
