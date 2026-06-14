"""Advisory risk-of-bias self-consistency check, built on the rubric tree.

Stdlib-only, no LLM, deterministic. The first ADOPTION of `agent/rubric_tree`:
it expresses a `StudyAssessment`'s per-domain ratings as a SEQUENTIAL rubric
tree (weakest-link = worst domain) and flags when the *stated* `overall_rating`
is LESS SEVERE than the worst domain — a logical violation of the RoB-2 /
ROBINS-I / SYRCLE "overall = worst domain" rule.

This is genuinely live-relevant: `scripts/render_quality_tables.studies_from_json`
parses `domains` and `overall_rating` independently from upstream input, so the
two can disagree. This module is ADVISORY only — a pure detector. It is not a
gate and nothing in the live pipeline imports it yet; surfacing it (e.g. as a
P3 advisory issue in final_consistency_audit) is a separate, reviewed step.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.risk_of_bias_schema import StudyAssessment
from agent.rubric_tree import AggregationStrategy, VerificationNode, aggregate, leaf

__all__ = ["RobConsistency", "study_as_rubric_tree", "rob_overall_consistency",
           "inconsistent_studies"]

# Rating -> [0,1] score for the tree (higher = lower risk). "unclear"/"no
# information" is treated as no-better-than some_concerns (conservative).
_RATING_SCORE: dict[str, float] = {
    "low": 1.0, "some_concerns": 0.5, "unclear": 0.5, "high": 0.0,
}
# Severity order for the consistency decision (higher = worse).
_SEVERITY: dict[str, int] = {
    "low": 0, "some_concerns": 1, "unclear": 1, "high": 2,
}


@dataclass(frozen=True, slots=True)
class RobConsistency:
    study_id: str
    consistent: bool
    stated_rating: str
    worst_domain_rating: str
    worst_domain: str
    tree_score: float
    message: str


def study_as_rubric_tree(study: StudyAssessment) -> VerificationNode:
    """Express a study's domains as a SEQUENTIAL (worst-domain) rubric tree."""
    leaves = [
        leaf(d.domain, _RATING_SCORE.get(d.rating, 0.0), desc=d.rationale)
        for d in study.domains
    ]
    return aggregate(
        study.study_id, leaves,
        desc=f"{study.tool} overall (worst-domain)",
        strategy=AggregationStrategy.SEQUENTIAL,
    )


def rob_overall_consistency(study: StudyAssessment) -> RobConsistency:
    """Flag when the stated overall_rating is less severe than the worst domain."""
    tree = study_as_rubric_tree(study)
    worst = min(study.domains, key=lambda d: _RATING_SCORE.get(d.rating, 0.0))
    consistent = _SEVERITY[study.overall_rating] >= _SEVERITY[worst.rating]
    message = (
        "consistent" if consistent else
        f"stated overall '{study.overall_rating}' is less severe than worst "
        f"domain '{worst.domain}'='{worst.rating}' — worst-domain rule violated"
    )
    return RobConsistency(
        study_id=study.study_id,
        consistent=consistent,
        stated_rating=study.overall_rating,
        worst_domain_rating=worst.rating,
        worst_domain=worst.domain,
        tree_score=tree.score,
        message=message,
    )


def inconsistent_studies(
    studies: list[StudyAssessment],
) -> list[RobConsistency]:
    """Return only the studies whose stated overall understates their worst domain."""
    results = (rob_overall_consistency(s) for s in studies)
    return [r for r in results if not r.consistent]
