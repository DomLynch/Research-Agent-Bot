"""Effect-size normalization primitives — raw study reports → EffectRow.

Phase 5 upstream complement to `agent.meta_analysis`. Stdlib-only.

Bridges the typical reporting shapes (per-arm mean+SD+n; per-arm events+n;
or pre-computed effect+SE) into the `EffectRow` shape the pooler consumes.
Strict construction-time validation; fail-closed on degenerate inputs.

Supported metrics:
  - "MD"     mean difference for continuous outcomes.
  - "log_RR" log risk ratio for binary outcomes.
  - "log_OR" log odds ratio for binary outcomes.
  - passthrough for any metric label when effect+SE are pre-computed.

No continuity correction is applied for zero-event arms; callers must
apply Haldane (+0.5) or pseudo-count corrections upstream and pass the
adjusted counts. Failing closed beats silently injecting a correction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from agent.meta_analysis import EffectRow

__all__ = [
    "RawContinuous",
    "RawBinary",
    "normalize_md",
    "normalize_log_rr",
    "normalize_log_or",
    "normalize_passthrough",
    "normalize_record",
]


@dataclass(frozen=True, slots=True)
class RawContinuous:
    """Continuous-outcome raw report (per-arm summary statistics)."""

    study_id: str
    mean_t: float
    sd_t: float
    n_t: int
    mean_c: float
    sd_c: float
    n_c: int

    def __post_init__(self) -> None:
        _require_positive_int("n_t", self.n_t)
        _require_positive_int("n_c", self.n_c)
        _require_nonneg_finite("sd_t", self.sd_t)
        _require_nonneg_finite("sd_c", self.sd_c)
        _require_finite("mean_t", self.mean_t)
        _require_finite("mean_c", self.mean_c)
        if not self.study_id:
            raise ValueError("study_id must be non-empty")


@dataclass(frozen=True, slots=True)
class RawBinary:
    """Binary-outcome raw report (per-arm event counts)."""

    study_id: str
    events_t: int
    n_t: int
    events_c: int
    n_c: int

    def __post_init__(self) -> None:
        _require_positive_int("n_t", self.n_t)
        _require_positive_int("n_c", self.n_c)
        if self.events_t < 0 or self.events_c < 0:
            raise ValueError("event counts must be non-negative")
        if self.events_t > self.n_t:
            raise ValueError(f"events_t ({self.events_t}) exceeds n_t ({self.n_t})")
        if self.events_c > self.n_c:
            raise ValueError(f"events_c ({self.events_c}) exceeds n_c ({self.n_c})")
        if not self.study_id:
            raise ValueError("study_id must be non-empty")


def normalize_md(raw: RawContinuous) -> EffectRow:
    """Compute mean difference + SE under independent-samples assumption."""
    if raw.sd_t == 0.0 and raw.sd_c == 0.0:
        raise ValueError(
            f"both arms have zero SD for {raw.study_id!r}; cannot compute SE"
        )
    diff = raw.mean_t - raw.mean_c
    var = (raw.sd_t * raw.sd_t) / raw.n_t + (raw.sd_c * raw.sd_c) / raw.n_c
    se = math.sqrt(var)
    if se <= 0.0:
        raise ValueError(f"computed SE is non-positive for {raw.study_id!r}")
    return EffectRow(
        study_id=raw.study_id,
        effect=diff,
        se=se,
        n=raw.n_t + raw.n_c,
        metric="MD",
    )


def normalize_log_rr(raw: RawBinary) -> EffectRow:
    """Compute log risk ratio + SE. Fails closed on zero-event arms."""
    if raw.events_t == 0 or raw.events_c == 0:
        raise ValueError(
            f"zero-event arm in {raw.study_id!r}; "
            "apply continuity correction upstream and retry"
        )
    p_t = raw.events_t / raw.n_t
    p_c = raw.events_c / raw.n_c
    if p_t >= 1.0 or p_c >= 1.0:
        raise ValueError(
            f"event proportion ≥1 in {raw.study_id!r}; "
            "log RR undefined under saturation"
        )
    log_rr = math.log(p_t / p_c)
    var = 1 / raw.events_t - 1 / raw.n_t + 1 / raw.events_c - 1 / raw.n_c
    if var <= 0.0:
        raise ValueError(f"computed log_RR variance is non-positive for {raw.study_id!r}")
    return EffectRow(
        study_id=raw.study_id,
        effect=log_rr,
        se=math.sqrt(var),
        n=raw.n_t + raw.n_c,
        metric="log_RR",
    )


def normalize_log_or(raw: RawBinary) -> EffectRow:
    """Compute log odds ratio + SE. Fails closed on zero-event/full-event arms."""
    a, b = raw.events_t, raw.n_t - raw.events_t
    c, d = raw.events_c, raw.n_c - raw.events_c
    if 0 in (a, b, c, d):
        raise ValueError(
            f"zero cell in 2x2 for {raw.study_id!r}; "
            "apply continuity correction upstream and retry"
        )
    log_or = math.log((a * d) / (b * c))
    var = 1 / a + 1 / b + 1 / c + 1 / d
    return EffectRow(
        study_id=raw.study_id,
        effect=log_or,
        se=math.sqrt(var),
        n=raw.n_t + raw.n_c,
        metric="log_OR",
    )


def normalize_passthrough(
    *, study_id: str, effect: float, se: float, n: int, metric: str
) -> EffectRow:
    """Trust pre-computed effect + SE. EffectRow construction validates."""
    return EffectRow(study_id=study_id, effect=effect, se=se, n=n, metric=metric)


def normalize_record(record: dict) -> EffectRow:
    """Dispatch normalizer based on which fields the record carries.

    Detection order:
      1. effect + se present → passthrough.
      2. mean_t/sd_t/n_t + mean_c/sd_c/n_c → normalize_md.
      3. events_t + events_c with metric="log_OR" → normalize_log_or.
      4. events_t + events_c (default or metric="log_RR") → normalize_log_rr.

    Records with ambiguous shapes raise ValueError."""
    study_id = str(record.get("study_id", "")).strip()
    if not study_id:
        raise ValueError("record missing study_id")
    has_effect = "effect" in record and "se" in record
    has_continuous = all(
        k in record for k in ("mean_t", "sd_t", "n_t", "mean_c", "sd_c", "n_c")
    )
    has_binary = all(
        k in record for k in ("events_t", "n_t", "events_c", "n_c")
    )
    shapes = sum((has_effect, has_continuous, has_binary))
    if shapes > 1:
        raise ValueError(
            f"record for {study_id!r} has ambiguous effect-size shape"
        )
    if has_effect:
        if not str(record.get("metric") or "").strip():
            raise ValueError(
                f"pre-computed effect for {study_id!r} is missing metric"
            )
        return normalize_passthrough(
            study_id=study_id,
            effect=float(record["effect"]),
            se=float(record["se"]),
            n=int(record.get("n") or record.get("n_total") or 0),
            metric=str(record["metric"]),
        )
    if has_continuous:
        return normalize_md(RawContinuous(
            study_id=study_id,
            mean_t=float(record["mean_t"]), sd_t=float(record["sd_t"]),
            n_t=int(record["n_t"]),
            mean_c=float(record["mean_c"]), sd_c=float(record["sd_c"]),
            n_c=int(record["n_c"]),
        ))
    if has_binary:
        raw = RawBinary(
            study_id=study_id,
            events_t=int(record["events_t"]), n_t=int(record["n_t"]),
            events_c=int(record["events_c"]), n_c=int(record["n_c"]),
        )
        if str(record.get("metric") or "").lower() == "log_or":
            return normalize_log_or(raw)
        return normalize_log_rr(raw)
    raise ValueError(
        f"record for {study_id!r} has no recognised effect-size shape"
    )


# ---- Internal validation helpers ------------------------------------------


def _require_positive_int(name: str, value: int) -> None:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive int, got {value!r}")


def _require_nonneg_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative finite number, got {value!r}")


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
