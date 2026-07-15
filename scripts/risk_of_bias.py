"""Deterministic risk-of-bias screening scaffold.

This is a derived screening aid for receipt-like dicts. It is not a
full Cochrane RoB 2 signaling questionnaire.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping, Sequence

RiskLevel = Literal["low", "some_concerns", "high"]

SCREENING_LABEL = (
    "derived_screening_not_full_cochrane_rob2_signaling_questionnaire"
)

_VALID_TIERS = {"A1", "A2", "B", "B1", "B2", "C", "C1", "C2", "mixed"}
_VALID_DIRECTNESS = {
    "direct", "indirect", "mechanistic", "preclinical", "review",
}
_LOW_HINTS = {"low", "low_risk", "low risk"}
_HIGH_HINTS = {"high", "serious", "critical", "high_risk", "high risk"}
_CONCERN_HINTS = {"some_concerns", "moderate", "unclear", "some concerns"}


@dataclass(frozen=True, slots=True)
class RiskOfBiasAssessment:
    label: str
    overall: RiskLevel
    domains: dict[str, RiskLevel]
    basis: tuple[str, ...]
    fail_closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return to_stable_json(self)


def assess_risk_of_bias(receipt: Mapping[str, Any]) -> RiskOfBiasAssessment:
    """Derive a conservative RoB screen from structured receipt fields."""
    tier = _tier(_pick(receipt, "tier", "evidence_tier"))
    directness = _text(_pick(receipt, "directness"))
    design = _text(_pick(receipt, "study_design", "design_tier"))
    hint = _risk_hint(receipt)

    if tier not in _VALID_TIERS or directness not in _VALID_DIRECTNESS:
        return _assessment(
            "high",
            ("missing_or_invalid_tier_or_directness",),
            fail_closed=True,
        )

    if hint:
        return _assessment(hint, (f"explicit_metadata_hint:{hint}",))

    if "rct" in design or "randomized" in design or tier == "A1":
        base: RiskLevel = "low"
        basis: tuple[str, ...] = ("randomized_or_top_tier_default",)
    elif tier in {"A2", "B1", "B"} or directness == "review":
        base = "some_concerns"
        basis = ("nonrandomized_or_secondary_evidence_default",)
    else:
        base = "high"
        basis = ("low_tier_default",)

    if directness in {"mechanistic", "preclinical"} and base == "low":
        base = "some_concerns"
        basis += ("mechanistic_preclinical_bias_floor",)
    return _assessment(base, basis)


def assess_risk_of_bias_batch(
    receipts_by_outcome: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, tuple[RiskOfBiasAssessment, ...]]:
    return {
        str(outcome or "unknown"): tuple(
            assess_risk_of_bias(receipt) for receipt in receipts
        )
        for outcome, receipts in sorted(receipts_by_outcome.items())
    }


def assess_risk_of_bias_batch_json(
    receipts_by_outcome: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    return to_stable_json(assess_risk_of_bias_batch(receipts_by_outcome))


def to_stable_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _assessment(
    overall: RiskLevel,
    basis: tuple[str, ...],
    *,
    fail_closed: bool = False,
) -> RiskOfBiasAssessment:
    domains = {
        "randomization_or_selection": overall,
        "deviations_from_intended_evidence": overall,
        "missing_or_incomplete_data": overall,
        "outcome_measurement": overall,
        "selective_reporting": overall,
    }
    return RiskOfBiasAssessment(
        label=SCREENING_LABEL,
        overall=overall,
        domains=domains,
        basis=basis,
        fail_closed=fail_closed,
    )


def _pick(receipt: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in receipt:
            return receipt[key]
    metadata = receipt.get("metadata")
    if isinstance(metadata, Mapping):
        for key in keys:
            if key in metadata:
                return metadata[key]
    return None


def _risk_hint(receipt: Mapping[str, Any]) -> RiskLevel | None:
    raw = _pick(receipt, "risk_of_bias", "rob", "risk_of_bias_hint")
    if raw is None:
        return None
    value = _text(raw)
    if value in _LOW_HINTS:
        return "low"
    if value in _HIGH_HINTS:
        return "high"
    if value in _CONCERN_HINTS:
        return "some_concerns"
    return None


def _text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _tier(value: Any) -> str:
    return str(value or "").strip()


def _jsonable(value: Any) -> Any:
    if isinstance(value, RiskOfBiasAssessment):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value
