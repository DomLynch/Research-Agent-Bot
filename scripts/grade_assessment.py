"""Deterministic GRADE certainty scaffold."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping, Sequence

Certainty = Literal["high", "moderate", "low", "very_low"]
RiskOfBias = Literal["low", "some_concerns", "high"]

_SCORES: dict[Certainty, int] = {
    "very_low": 0,
    "low": 1,
    "moderate": 2,
    "high": 3,
}
_CERTAINTY_BY_SCORE: dict[int, Certainty] = {
    0: "very_low",
    1: "low",
    2: "moderate",
    3: "high",
}
_VALID_TIERS = {"A1", "A2", "B", "B1", "B2", "C", "C1", "C2", "mixed"}
_VALID_DIRECTNESS = {
    "direct", "indirect", "mechanistic", "preclinical", "review",
}


@dataclass(frozen=True, slots=True)
class GradeAssessment:
    outcome: str
    certainty: Certainty
    start_certainty: Certainty
    downgrades: tuple[str, ...]
    caps: tuple[str, ...]
    fail_closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return to_stable_json(self)


def assess_grade(outcome: str, evidence: Mapping[str, Any]) -> GradeAssessment:
    """Assess outcome certainty from tier/directness/RoB/GRADE domains."""
    tier = _tier(evidence.get("tier", evidence.get("evidence_tier")))
    directness = _text(evidence.get("directness"))
    if not outcome or tier not in _VALID_TIERS or directness not in _VALID_DIRECTNESS:
        return GradeAssessment(
            outcome=str(outcome or "unknown"),
            certainty="very_low",
            start_certainty="very_low",
            downgrades=("missing_or_invalid_required_fields",),
            caps=(),
            fail_closed=True,
        )

    start = _starting_certainty(tier, directness)
    score = _SCORES[start]
    downgrades = list(_domain_downgrades(evidence))
    score = max(0, score - len(downgrades))

    caps: list[str] = []
    cap = _directness_cap(tier, directness)
    if cap and score > _SCORES[cap]:
        score = _SCORES[cap]
        caps.append(f"{directness}_evidence_cap:{cap}")

    return GradeAssessment(
        outcome=outcome,
        certainty=_CERTAINTY_BY_SCORE[score],
        start_certainty=start,
        downgrades=tuple(downgrades),
        caps=tuple(caps),
    )


def assess_grade_batch(
    receipts_by_outcome: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[GradeAssessment, ...]:
    return tuple(
        _summarize_outcome_grade(str(outcome or "unknown"), receipts)
        for outcome, receipts in sorted(receipts_by_outcome.items())
    )


def assess_grade_batch_json(
    receipts_by_outcome: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    return to_stable_json(assess_grade_batch(receipts_by_outcome))


def to_stable_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _starting_certainty(tier: str, directness: str) -> Certainty:
    if tier == "A1" and directness == "direct":
        return "high"
    if tier in {"A1", "A2", "B1", "B"}:
        return "moderate"
    if tier in {"B2", "mixed"}:
        return "low"
    return "very_low"


def _domain_downgrades(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    downgrades: list[str] = []
    rob = _text(evidence.get("risk_of_bias", evidence.get("rob")))
    if rob == "high":
        downgrades.append("risk_of_bias:serious")
    elif rob == "some_concerns":
        downgrades.append("risk_of_bias:some_concerns")

    for field in ("inconsistency", "imprecision"):
        problem = _text(evidence.get(field))
        if problem in {"serious", "very_serious"}:
            downgrades.append(f"{field}:{problem}")
    return tuple(downgrades)


def _directness_cap(tier: str, directness: str) -> Certainty | None:
    if directness in {"indirect", "review"}:
        return "moderate" if tier in {"A1", "A2"} else "low"
    if directness in {"mechanistic", "preclinical"}:
        return "low"
    return None


def _summarize_outcome_grade(
    outcome: str,
    receipts: Sequence[Mapping[str, Any]],
) -> GradeAssessment:
    grades = [assess_grade(outcome, receipt) for receipt in receipts]
    if not grades:
        return assess_grade(outcome, {})
    worst = min(grades, key=lambda g: _SCORES[g.certainty])
    return GradeAssessment(
        outcome=outcome,
        certainty=worst.certainty,
        start_certainty=max(
            (g.start_certainty for g in grades),
            key=lambda c: _SCORES[c],
        ),
        downgrades=tuple(sorted({d for g in grades for d in g.downgrades})),
        caps=tuple(sorted({c for g in grades for c in g.caps})),
        fail_closed=any(g.fail_closed for g in grades),
    )


def _text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _tier(value: Any) -> str:
    return str(value or "").strip()


def _jsonable(value: Any) -> Any:
    if isinstance(value, GradeAssessment):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value
