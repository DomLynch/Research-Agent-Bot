"""Tests for the advisory RoB self-consistency check (agent/rob_consistency.py)."""
from __future__ import annotations

from agent.risk_of_bias_schema import (
    ROB2_DOMAINS,
    DomainAssessment,
    Rating,
    StudyAssessment,
)
from agent.rob_consistency import (
    inconsistent_studies,
    rob_overall_consistency,
    study_as_rubric_tree,
)


def _rob2(overall: Rating, **domain_ratings: Rating) -> StudyAssessment:
    domains = tuple(
        DomainAssessment(domain=d, rating=domain_ratings.get(d, "low"))
        for d in ROB2_DOMAINS
    )
    return StudyAssessment(
        study_id="s1", design="rct", tool="rob2",
        domains=domains, overall_rating=overall,
    )


def test_consistent_when_overall_matches_worst() -> None:
    r = rob_overall_consistency(_rob2("low"))  # all domains low
    assert r.consistent
    assert r.worst_domain_rating == "low"
    assert r.tree_score == 1.0


def test_inconsistent_when_overall_understates_worst() -> None:
    # a high-risk domain but overall claimed 'low' — worst-domain rule violated
    r = rob_overall_consistency(_rob2("low", outcome_measurement="high"))
    assert not r.consistent
    assert r.worst_domain_rating == "high"
    assert r.worst_domain == "outcome_measurement"
    assert r.tree_score == 0.0
    assert "worst-domain rule violated" in r.message


def test_overall_more_severe_than_worst_is_allowed() -> None:
    # conservative overrating (overall worse than worst domain) is NOT flagged
    r = rob_overall_consistency(_rob2("high"))  # all domains low, overall high
    assert r.consistent


def test_tree_is_worst_domain_not_mean() -> None:
    study = _rob2("some_concerns", randomization="some_concerns")  # one 0.5, rest 1.0
    tree = study_as_rubric_tree(study)
    assert tree.score == 0.5  # SEQUENTIAL min, not mean
    assert rob_overall_consistency(study).consistent


def test_inconsistent_studies_filters() -> None:
    good = _rob2("some_concerns", randomization="some_concerns")
    bad = _rob2("low", deviations="high")
    out = inconsistent_studies([good, bad])
    assert len(out) == 1
    assert out[0].worst_domain == "deviations"
