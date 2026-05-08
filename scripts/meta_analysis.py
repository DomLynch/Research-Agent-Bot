"""Deterministic meta-analysis scaffold.

Fixed-effect inverse-variance pooling only. Fails closed unless at least
two compatible, non-high-RoB numeric effect sizes are present.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class MetaAnalysisResult:
    label: str
    outcome: str
    effect_measure: str
    k: int
    pooled_effect: float | None
    ci_low: float | None
    ci_high: float | None
    model: str
    reason: str
    fail_closed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def pool_fixed_effect(
    outcome: str,
    receipts: Sequence[Mapping[str, Any]],
) -> MetaAnalysisResult:
    rows = [_effect_row(outcome, receipt) for receipt in receipts]
    invalid = [reason for row, reason in rows if row is None for reason in (reason,)]
    effects = [row for row, _ in rows if row is not None]
    measures = {row[1] for row in effects}
    if any(reason == "high_risk_of_bias" for reason in invalid):
        return _closed(outcome, measures, "high_risk_of_bias_excluded")
    if len(effects) < 2:
        return _closed(outcome, measures, "insufficient_compatible_effect_sizes")
    if len(measures) != 1:
        return _closed(outcome, measures, "mixed_effect_measures")

    weights = [1 / (se * se) for _, _, effect, se in effects]
    pooled = sum(w * row[2] for w, row in zip(weights, effects)) / sum(weights)
    pooled_se = math.sqrt(1 / sum(weights))
    return MetaAnalysisResult(
        label="fixed_effect_inverse_variance_scaffold",
        outcome=outcome or "unknown",
        effect_measure=measures.pop(),
        k=len(effects),
        pooled_effect=round(pooled, 6),
        ci_low=round(pooled - 1.96 * pooled_se, 6),
        ci_high=round(pooled + 1.96 * pooled_se, 6),
        model="fixed_effect_inverse_variance",
        reason="compatible_effect_sizes_present",
        fail_closed=False,
    )


def forest_plot_contract(result: MetaAnalysisResult) -> dict[str, Any]:
    return {
        "plot_type": "forest",
        "status": "placeholder_no_plotting_dependency",
        "requires": ["study_effect", "standard_error", "effect_measure"],
        "result": result.to_dict(),
    }


def funnel_plot_contract(result: MetaAnalysisResult) -> dict[str, Any]:
    return {
        "plot_type": "funnel",
        "status": "placeholder_no_plotting_dependency",
        "requires": ["study_effect", "standard_error", "effect_measure"],
        "result": result.to_dict(),
    }


def _effect_row(
    outcome: str,
    receipt: Mapping[str, Any],
) -> tuple[tuple[str, str, float, float] | None, str]:
    if _text(receipt.get("outcome", receipt.get("outcome_class"))) != _text(outcome):
        return None, "outcome_mismatch"
    if _text(receipt.get("risk_of_bias", receipt.get("rob"))) == "high":
        return None, "high_risk_of_bias"
    measure = str(receipt.get("effect_measure") or "").strip()
    effect = _float(receipt.get("effect"))
    se = _float(receipt.get("standard_error", receipt.get("se")))
    if not measure or effect is None or se is None or se <= 0:
        return None, "missing_effect_or_standard_error"
    return (str(receipt.get("receipt_id") or "unknown"), measure, effect, se), "ok"


def _closed(
    outcome: str,
    measures: set[str],
    reason: str,
) -> MetaAnalysisResult:
    return MetaAnalysisResult(
        label="fixed_effect_inverse_variance_scaffold",
        outcome=outcome or "unknown",
        effect_measure=sorted(measures)[0] if len(measures) == 1 else "unknown",
        k=0,
        pooled_effect=None,
        ci_low=None,
        ci_high=None,
        model="none",
        reason=reason,
        fail_closed=True,
    )


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")
