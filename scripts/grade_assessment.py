"""Deterministic GRADE certainty scaffold."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping

Certainty = Literal["high", "moderate", "low", "very_low"]
Problem = Literal["not_serious", "serious", "very_serious"]
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


def _text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _tier(value: Any) -> str:
    return str(value or "").strip()
