"""Tests for the publication-readiness scorer (panel rubric)."""
from __future__ import annotations

import pytest

from agent.publication_scorer import (
    ACCEPT_TOTAL_FLOOR,
    RubricScore,
    ScorecardResult,
    ScoreInputs,
    score_publication,
)


def _green_inputs(**overrides) -> ScoreInputs:
    """All-green inputs that yield ACCEPT (30/30); override per test."""
    base = dict(
        n_receipts=42, n_outcome_classes=4, n_tensions=5,
        rob_coverage=0.85, grade_coverage=1.0, numeric_coverage=1.0,
        citation_registry_complete=True, audit_gates_passed=True,
        template_language_blocking=False,
        field_engagements_supported=4, field_engagements_total=5,
        has_explicit_thesis=True, has_limitations_section=True,
        has_clinical_practice_statement=True,
        unresolved_reviewer_p1_count=0,
    )
    base.update(overrides)
    return ScoreInputs(**base)


# ---- ScoreInputs validation ----------------------------------------------


@pytest.mark.parametrize("field,bad", [
    ("rob_coverage", 1.5),
    ("rob_coverage", -0.1),
    ("grade_coverage", 2.0),
    ("numeric_coverage", -0.5),
])
def test_inputs_reject_out_of_range_coverage(field, bad) -> None:
    with pytest.raises(ValueError, match=field):
        _green_inputs(**{field: bad})


def test_inputs_reject_negative_counts() -> None:
    with pytest.raises(ValueError, match="must be >=0"):
        _green_inputs(n_receipts=-1)


# ---- Verdict matrix ------------------------------------------------------


def test_clean_post_fix_paper_yields_accept() -> None:
    r = score_publication(_green_inputs())
    assert r.verdict == "accept"
    assert r.rubric.total == 30
    assert r.claim_support == "supported"
    assert r.overclaim == "none"
    assert r.blockers == ()


def test_aaa4_baseline_yields_revise() -> None:
    """3 receipts + no RoB/GRADE + no clinical-practice statement."""
    inputs = _green_inputs(
        n_receipts=3, n_outcome_classes=1,
        rob_coverage=0.0, grade_coverage=0.0,
        field_engagements_supported=0,
        has_clinical_practice_statement=False,
    )
    r = score_publication(inputs)
    assert r.verdict == "revise"
    assert r.rubric.total < ACCEPT_TOTAL_FLOOR
    assert any("accept floor" in b for b in r.blockers)


def test_template_language_blocking_demotes_to_revise() -> None:
    """All other gates green but template gate trips to REVISE due overclaim."""
    inputs = _green_inputs(template_language_blocking=True)
    r = score_publication(inputs)
    assert r.verdict in ("revise", "reject")
    assert r.overclaim != "none"


def test_unresolved_reviewer_p1_demotes_claim_support() -> None:
    inputs = _green_inputs(unresolved_reviewer_p1_count=2)
    r = score_publication(inputs)
    assert r.claim_support != "supported"


def test_catastrophic_inputs_yield_reject() -> None:
    inputs = _green_inputs(
        n_receipts=0, n_outcome_classes=0, n_tensions=0,
        rob_coverage=0.0, grade_coverage=0.0, numeric_coverage=0.0,
        citation_registry_complete=False, audit_gates_passed=False,
        template_language_blocking=True,
        field_engagements_supported=0, has_explicit_thesis=False,
        has_limitations_section=False, has_clinical_practice_statement=False,
        unresolved_reviewer_p1_count=5,
    )
    r = score_publication(inputs)
    assert r.verdict == "reject"
    assert r.rubric.total < 18
    assert r.claim_support == "unsupported"


# ---- Per-dimension scoring -----------------------------------------------


def test_research_question_scores_higher_with_multi_outcome() -> None:
    one = score_publication(_green_inputs(n_outcome_classes=1)).rubric.research_question
    multi = score_publication(_green_inputs(n_outcome_classes=4)).rubric.research_question
    assert multi > one


def test_synthesis_scales_with_receipt_count() -> None:
    thin = score_publication(_green_inputs(n_receipts=3)).rubric.synthesis
    mid = score_publication(_green_inputs(n_receipts=15)).rubric.synthesis
    fat = score_publication(_green_inputs(n_receipts=30)).rubric.synthesis
    assert thin < mid < fat or thin <= mid <= fat


def test_synthesis_zero_tensions_drops_score() -> None:
    with_tensions = score_publication(_green_inputs(n_tensions=5)).rubric.synthesis
    without = score_publication(_green_inputs(n_tensions=0)).rubric.synthesis
    assert with_tensions > without


def test_claim_evidence_caps_at_3_when_numeric_coverage_below_one() -> None:
    """Even with audit_pass + clean template, numeric coverage <1.0 caps the score."""
    inputs = _green_inputs(numeric_coverage=0.95)
    r = score_publication(inputs)
    assert r.rubric.claim_evidence < 5


def test_limitations_drops_without_clinical_practice_statement() -> None:
    """Bug 3 fix lives here: missing clinical-practice line dings limitations."""
    with_cp = score_publication(_green_inputs(has_clinical_practice_statement=True))
    without_cp = score_publication(_green_inputs(has_clinical_practice_statement=False))
    assert with_cp.rubric.limitations > without_cp.rubric.limitations
    # Note string surfaces the gap
    assert any("clinical-practice" in n for n in without_cp.notes)


def test_source_grounding_drops_with_incomplete_citation_registry() -> None:
    inputs = _green_inputs(citation_registry_complete=False)
    r = score_publication(inputs)
    assert r.rubric.source_grounding < 5


# ---- Boolean gates -------------------------------------------------------


def test_claim_support_supported_requires_all_gates_clean() -> None:
    r = score_publication(_green_inputs())
    assert r.claim_support == "supported"


def test_claim_support_partially_when_numeric_coverage_lower_but_above_85() -> None:
    inputs = _green_inputs(numeric_coverage=0.90)
    r = score_publication(inputs)
    assert r.claim_support == "partially_supported"


def test_claim_support_unsupported_when_numeric_coverage_low() -> None:
    inputs = _green_inputs(numeric_coverage=0.5)
    r = score_publication(inputs)
    assert r.claim_support == "unsupported"


def test_overclaim_severity_escalates_with_combined_signals() -> None:
    mild = score_publication(_green_inputs(template_language_blocking=True))
    severe = score_publication(_green_inputs(
        template_language_blocking=True, unresolved_reviewer_p1_count=1
    ))
    assert mild.overclaim == "mild"
    assert severe.overclaim == "severe"


# ---- ScorecardResult shape -----------------------------------------------


def test_scorecard_result_is_typed() -> None:
    r = score_publication(_green_inputs())
    assert isinstance(r, ScorecardResult)
    assert isinstance(r.rubric, RubricScore)
    assert isinstance(r.blockers, tuple)
    assert isinstance(r.notes, tuple)


def test_summary_string_carries_verdict_and_total() -> None:
    r = score_publication(_green_inputs())
    assert "ACCEPT" in r.summary
    assert "30/30" in r.summary


def test_summary_for_revise_lists_blocker_count() -> None:
    inputs = _green_inputs(n_receipts=3, has_clinical_practice_statement=False)
    r = score_publication(inputs)
    assert "REVISE" in r.summary
    assert "blocker" in r.summary


def test_rubric_total_equals_sum_of_dimensions() -> None:
    r = score_publication(_green_inputs())
    m = r.rubric.as_mapping()
    assert r.rubric.total == sum(m.values())


def test_rubric_dimensions_capped_at_5() -> None:
    """No dimension can exceed 5 even with hyper-positive inputs."""
    inputs = _green_inputs(
        n_receipts=1000, n_outcome_classes=20, n_tensions=50,
        field_engagements_supported=20, field_engagements_total=20,
    )
    r = score_publication(inputs)
    for dim, score in r.rubric.as_mapping().items():
        assert 0 <= score <= 5, f"{dim} = {score} out of [0,5]"


# ---- Determinism ---------------------------------------------------------


def test_scorer_is_deterministic() -> None:
    inputs = _green_inputs()
    r1 = score_publication(inputs)
    r2 = score_publication(inputs)
    assert r1.verdict == r2.verdict
    assert r1.rubric.total == r2.rubric.total
    assert r1.summary == r2.summary
