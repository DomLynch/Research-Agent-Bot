"""Deterministic meta-analysis primitives — fixed-effect + DerSimonian-Laird
random-effects pooling.

Phase 5 of the WORLDCLASS rapamycin sprint. Stdlib-only; depends only on
`math` and `statistics`. No new external dependencies.

Inputs are already-normalized effect rows: each EffectRow carries one
study's point estimate and standard error on a single comparable metric
(mean difference, log risk ratio, log hazard ratio — opaque label).

Output: PoolResult with pooled effect, SE, CI, plus heterogeneity
diagnostics (Cochran's Q, I², τ²).

Fail-closed:
  - fewer than 3 studies → ValueError
  - inconsistent metrics across rows → ValueError
  - missing / non-positive / non-finite SE → ValueError
  - non-finite or non-positive sample size → ValueError
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

__all__ = [
    "EffectRow",
    "PoolResult",
    "assert_poolable",
    "pool_fixed_effect",
    "pool_random_effects",
    "MIN_STUDIES",
]

PoolMethod = Literal["fixed_effect", "random_effects"]
MIN_STUDIES: int = 3
_VALID_METHODS: frozenset[str] = frozenset(("fixed_effect", "random_effects"))


@dataclass(frozen=True, slots=True)
class EffectRow:
    """One study's normalized effect estimate. metric is an opaque label
    (e.g. "MD", "log_RR") — pooling refuses to mix metrics."""

    study_id: str
    effect: float
    se: float
    n: int
    metric: str

    def __post_init__(self) -> None:
        if not self.study_id:
            raise ValueError("study_id must be a non-empty string")
        if not math.isfinite(self.effect):
            raise ValueError(f"effect must be finite, got {self.effect}")
        if not math.isfinite(self.se) or self.se <= 0:
            raise ValueError(f"se must be a positive finite number, got {self.se}")
        if self.n <= 0:
            raise ValueError(f"n must be positive, got {self.n}")
        if not self.metric:
            raise ValueError("metric must be a non-empty string")


@dataclass(frozen=True, slots=True)
class PoolResult:
    """Pooled effect with heterogeneity diagnostics.

    method        — "fixed_effect" or "random_effects".
    n_studies     — number of studies in the pool (k).
    metric        — passed through unchanged from the EffectRow inputs.
    pooled_effect — weighted-mean point estimate.
    pooled_se     — standard error of the pooled effect.
    ci_lower/upper— Wald confidence interval at ci_level.
    q             — Cochran's Q heterogeneity statistic.
    df            — degrees of freedom for Q (= k − 1).
    i_squared     — Higgins I² (0–100, percent).
    tau_squared   — between-study variance estimate (0 for fixed-effect).
    ci_level      — confidence level used for CI (default 0.95).
    """

    method: PoolMethod
    n_studies: int
    metric: str
    pooled_effect: float
    pooled_se: float
    ci_lower: float
    ci_upper: float
    q: float
    df: int
    i_squared: float
    tau_squared: float
    ci_level: float

    def __post_init__(self) -> None:
        if self.method not in _VALID_METHODS:
            raise ValueError(
                f"invalid method {self.method!r}; must be one of {sorted(_VALID_METHODS)}"
            )


def assert_poolable(rows: Sequence[EffectRow]) -> None:
    """Validate a row sequence is poolable. Raises ValueError on:
    fewer than MIN_STUDIES rows, mixed metrics, or any non-positive SE."""
    if len(rows) < MIN_STUDIES:
        raise ValueError(
            f"need at least {MIN_STUDIES} studies to pool, got {len(rows)}"
        )
    metrics = {r.metric for r in rows}
    if len(metrics) > 1:
        raise ValueError(
            f"cannot pool across mixed metrics: {sorted(metrics)}"
        )
    if any(r.se <= 0 or not math.isfinite(r.se) for r in rows):
        raise ValueError("all rows must have a positive finite SE")


def _z_for_ci(ci_level: float) -> float:
    """Two-tailed z critical value for a given CI level (e.g. 0.95 → 1.95996)."""
    if not (0.0 < ci_level < 1.0):
        raise ValueError(f"ci_level must be in (0,1), got {ci_level}")
    alpha = 1.0 - ci_level
    return NormalDist().inv_cdf(1.0 - alpha / 2.0)


def _fixed_pooled(rows: Sequence[EffectRow]) -> tuple[float, float, list[float]]:
    """Return (pooled_effect, pooled_se, weights) for fixed-effect."""
    weights = [1.0 / (r.se * r.se) for r in rows]
    sum_w = sum(weights)
    pooled = sum(w * r.effect for w, r in zip(weights, rows)) / sum_w
    pooled_se = 1.0 / math.sqrt(sum_w)
    return pooled, pooled_se, weights


def _q_and_i2(rows: Sequence[EffectRow], pooled: float, weights: Sequence[float]) -> tuple[float, float]:
    """Cochran's Q and Higgins I² (0–100). df = k − 1."""
    q = sum(w * (r.effect - pooled) ** 2 for w, r in zip(weights, rows))
    df = len(rows) - 1
    if q <= 0 or df <= 0:
        return q, 0.0
    i2 = max(0.0, (q - df) / q) * 100.0
    return q, i2


def _ci_bounds(point: float, se: float, ci_level: float) -> tuple[float, float]:
    z = _z_for_ci(ci_level)
    return point - z * se, point + z * se


def pool_fixed_effect(
    rows: Sequence[EffectRow], *, ci_level: float = 0.95
) -> PoolResult:
    """Inverse-variance fixed-effect pool."""
    assert_poolable(rows)
    pooled, pooled_se, weights = _fixed_pooled(rows)
    q, i2 = _q_and_i2(rows, pooled, weights)
    lo, hi = _ci_bounds(pooled, pooled_se, ci_level)
    return PoolResult(
        method="fixed_effect",
        n_studies=len(rows),
        metric=rows[0].metric,
        pooled_effect=pooled,
        pooled_se=pooled_se,
        ci_lower=lo,
        ci_upper=hi,
        q=q,
        df=len(rows) - 1,
        i_squared=i2,
        tau_squared=0.0,
        ci_level=ci_level,
    )


def pool_random_effects(
    rows: Sequence[EffectRow], *, ci_level: float = 0.95
) -> PoolResult:
    """DerSimonian-Laird random-effects pool (uses FE Q for τ² estimate)."""
    assert_poolable(rows)
    fe_pooled, _, fe_weights = _fixed_pooled(rows)
    q, _ = _q_and_i2(rows, fe_pooled, fe_weights)
    df = len(rows) - 1
    sum_w = sum(fe_weights)
    sum_w_sq = sum(w * w for w in fe_weights)
    c = sum_w - sum_w_sq / sum_w
    tau_sq = max(0.0, (q - df) / c) if c > 0 else 0.0

    re_weights = [1.0 / (r.se * r.se + tau_sq) for r in rows]
    sum_re_w = sum(re_weights)
    pooled_re = sum(w * r.effect for w, r in zip(re_weights, rows)) / sum_re_w
    pooled_re_se = 1.0 / math.sqrt(sum_re_w)

    # I² is conventionally reported relative to the FE Q + df, not the RE pool.
    i2 = max(0.0, (q - df) / q) * 100.0 if q > 0 and df > 0 else 0.0
    lo, hi = _ci_bounds(pooled_re, pooled_re_se, ci_level)
    return PoolResult(
        method="random_effects",
        n_studies=len(rows),
        metric=rows[0].metric,
        pooled_effect=pooled_re,
        pooled_se=pooled_re_se,
        ci_lower=lo,
        ci_upper=hi,
        q=q,
        df=df,
        i_squared=i2,
        tau_squared=tau_sq,
        ci_level=ci_level,
    )
