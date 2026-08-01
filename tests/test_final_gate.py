"""Tests for the Phase 8 deterministic final-cert gate."""
from __future__ import annotations

from typing import Any

import pytest

from agent.final_gate import (
    DEFAULT_THRESHOLDS,
    GateInputs,
    GateResult,
    GateThresholds,
    evaluate_final_gate,
    landscape_thresholds,
)


def _green_inputs(**overrides: Any) -> GateInputs:
    """All-green inputs that pass DEFAULT_THRESHOLDS; override fields as needed."""
    base: dict[str, Any] = dict(
        numeric_coverage=1.0,
        audit_gates_passed=True,
        journal_surface_passed=True,
        citation_registry_complete=True,
        rob_coverage=1.0,
        grade_coverage=1.0,
        n_tensions=5,
        n_receipts=34,
        unresolved_reviewer_p1_count=0,
        template_language_blocking=False,
    )
    base.update(overrides)
    return GateInputs(**base)


# ---- GateThresholds validation --------------------------------------------


def test_default_thresholds_construct() -> None:
    assert DEFAULT_THRESHOLDS.min_numeric_coverage == 1.0
    assert DEFAULT_THRESHOLDS.min_receipts == 12


@pytest.mark.parametrize("field,bad", [
    ("min_numeric_coverage", 1.5),
    ("min_numeric_coverage", -0.1),
    ("min_rob_coverage", 2.0),
    ("min_grade_coverage", -0.5),
])
def test_thresholds_reject_out_of_range_coverage(field, bad) -> None:
    with pytest.raises(ValueError, match=field):
        GateThresholds(**{field: bad})


def test_thresholds_reject_negative_min_tensions() -> None:
    with pytest.raises(ValueError, match="min_tensions"):
        GateThresholds(min_tensions=-1)


def test_thresholds_reject_warn_below_min_receipts() -> None:
    with pytest.raises(ValueError, match="warn_below_receipts"):
        GateThresholds(min_receipts=20, warn_below_receipts=10)


# ---- GateInputs validation -------------------------------------------------


def test_inputs_reject_negative_coverage() -> None:
    with pytest.raises(ValueError, match="numeric_coverage"):
        _green_inputs(numeric_coverage=-0.1)


def test_inputs_reject_coverage_above_one() -> None:
    with pytest.raises(ValueError, match="rob_coverage"):
        _green_inputs(rob_coverage=1.1)


def test_inputs_reject_negative_counts() -> None:
    with pytest.raises(ValueError, match="n_tensions"):
        _green_inputs(n_tensions=-1)
    with pytest.raises(ValueError, match="n_receipts"):
        _green_inputs(n_receipts=-1)
    with pytest.raises(ValueError, match="unresolved_reviewer_p1_count"):
        _green_inputs(unresolved_reviewer_p1_count=-1)


# ---- evaluate_final_gate: pass cases --------------------------------------


def test_all_green_passes() -> None:
    r = evaluate_final_gate(_green_inputs())
    assert r.passed
    assert r.failures == ()


def test_passes_with_p2_warning_when_receipts_below_recommendation() -> None:
    r = evaluate_final_gate(_green_inputs(n_receipts=15))
    assert r.passed
    assert any("15 below recommended" in w for w in r.warnings)


def test_summary_string_for_pass_includes_counts() -> None:
    r = evaluate_final_gate(_green_inputs())
    assert "PASS" in r.summary
    assert "34 receipts" in r.summary


# ---- evaluate_final_gate: P1 failure cases --------------------------------


def test_numeric_coverage_below_threshold_fails() -> None:
    r = evaluate_final_gate(_green_inputs(numeric_coverage=0.95))
    assert not r.passed
    assert any("numeric_coverage" in f for f in r.failures)


def test_audit_gate_failure_fails() -> None:
    r = evaluate_final_gate(_green_inputs(audit_gates_passed=False))
    assert not r.passed
    assert "audit_gates_failed" in r.failures


def test_journal_surface_failure_fails() -> None:
    r = evaluate_final_gate(_green_inputs(journal_surface_passed=False))
    assert not r.passed
    assert "journal_surface_failed" in r.failures


def test_unresolved_reviewer_p1_fails() -> None:
    r = evaluate_final_gate(_green_inputs(unresolved_reviewer_p1_count=1))
    assert not r.passed
    assert "unresolved_reviewer_p1_count=1" in r.failures


def test_incomplete_citation_registry_fails() -> None:
    r = evaluate_final_gate(_green_inputs(citation_registry_complete=False))
    assert not r.passed
    assert "citation_registry_incomplete" in r.failures


def test_rob_coverage_below_threshold_fails() -> None:
    r = evaluate_final_gate(_green_inputs(rob_coverage=0.5))
    assert not r.passed
    assert any("rob_coverage" in f for f in r.failures)


def test_grade_coverage_below_threshold_fails() -> None:
    r = evaluate_final_gate(_green_inputs(grade_coverage=0.7))
    assert not r.passed
    assert any("grade_coverage" in f for f in r.failures)


def test_zero_tensions_fails() -> None:
    r = evaluate_final_gate(_green_inputs(n_tensions=0))
    assert not r.passed
    assert any("n_tensions" in f for f in r.failures)


def test_thin_corpus_below_min_fails() -> None:
    r = evaluate_final_gate(_green_inputs(n_receipts=11))
    assert not r.passed
    assert any("n_receipts" in f for f in r.failures)


def test_template_language_blocking_fails() -> None:
    r = evaluate_final_gate(_green_inputs(template_language_blocking=True))
    assert not r.passed
    assert "template_language_gate_blocking" in r.failures


def test_all_gates_failing_lists_every_failure() -> None:
    inputs = GateInputs(
        numeric_coverage=0.0, audit_gates_passed=False,
        journal_surface_passed=False, citation_registry_complete=False,
        rob_coverage=0.0, grade_coverage=0.0,
        n_tensions=0, n_receipts=0, unresolved_reviewer_p1_count=1,
        template_language_blocking=True,
    )
    r = evaluate_final_gate(inputs)
    assert not r.passed
    assert len(r.failures) == 10  # all P1 gates fired


def test_failure_summary_lists_blocker_count() -> None:
    inputs = GateInputs(
        numeric_coverage=0.0, audit_gates_passed=True,
        journal_surface_passed=True, citation_registry_complete=False,
        rob_coverage=1.0, grade_coverage=1.0,
        n_tensions=5, n_receipts=34, unresolved_reviewer_p1_count=0,
        template_language_blocking=False,
    )
    r = evaluate_final_gate(inputs)
    assert "FAIL" in r.summary
    assert "2 blocker" in r.summary


# ---- Custom-thresholds use cases ------------------------------------------


def test_custom_relaxed_thresholds_pass_thin_corpus() -> None:
    """AAA-SCOP-style relaxation: thin corpus passes a relaxed gate."""
    custom = GateThresholds(
        min_rob_coverage=0.5, min_receipts=2, min_tensions=0,
        warn_below_receipts=5,
    )
    inputs = GateInputs(
        numeric_coverage=1.0, audit_gates_passed=True,
        journal_surface_passed=True, citation_registry_complete=True,
        rob_coverage=0.5, grade_coverage=1.0,
        n_tensions=0, n_receipts=3, unresolved_reviewer_p1_count=0,
        template_language_blocking=False,
    )
    r = evaluate_final_gate(inputs, thresholds=custom)
    assert r.passed


def test_template_language_gate_can_be_disabled_via_thresholds() -> None:
    custom = GateThresholds(template_language_must_pass=False)
    inputs = _green_inputs(template_language_blocking=True)
    r = evaluate_final_gate(inputs, thresholds=custom)
    assert r.passed


def test_default_thresholds_used_when_none_passed() -> None:
    r1 = evaluate_final_gate(_green_inputs())
    r2 = evaluate_final_gate(_green_inputs(), thresholds=DEFAULT_THRESHOLDS)
    assert r1.passed == r2.passed
    assert r1.summary == r2.summary


# ---- GateResult shape ------------------------------------------------------


def test_gate_result_failures_are_tuple() -> None:
    r = evaluate_final_gate(_green_inputs())
    assert isinstance(r, GateResult)
    assert isinstance(r.failures, tuple)
    assert isinstance(r.warnings, tuple)


# --- evidence_map zero-tension landscape relaxation (publish-consistency fix) -

def test_landscape_thresholds_relaxes_only_tension_for_zero_tension() -> None:
    th = landscape_thresholds(
        n_receipts=12, n_tensions=0, declared_review_type="evidence_map",
    )
    assert th is not None and th.min_tensions == 0
    # every other integrity threshold is unchanged from the default
    assert th.min_numeric_coverage == DEFAULT_THRESHOLDS.min_numeric_coverage
    assert th.min_rob_coverage == DEFAULT_THRESHOLDS.min_rob_coverage
    assert th.min_grade_coverage == DEFAULT_THRESHOLDS.min_grade_coverage
    assert th.min_receipts == DEFAULT_THRESHOLDS.min_receipts


def test_landscape_thresholds_none_for_tensioned_or_empty() -> None:
    assert landscape_thresholds(
        n_receipts=12, n_tensions=3, declared_review_type="evidence_map",
    ) is None
    assert landscape_thresholds(
        n_receipts=0, n_tensions=0, declared_review_type="evidence_map",
    ) is None
    assert landscape_thresholds(n_receipts=12, n_tensions=0) is None
    assert landscape_thresholds(
        n_receipts=12, n_tensions=0, declared_review_type="evidence_brief",
    ) is None


def test_zero_tension_corpus_blocked_by_default_but_passes_as_landscape() -> None:
    inputs = _green_inputs(n_tensions=0, n_receipts=12)
    assert evaluate_final_gate(inputs).passed is False  # default min_tensions=1 blocks
    th = landscape_thresholds(
        inputs.n_receipts,
        inputs.n_tensions,
        declared_review_type="evidence_map",
    )
    assert evaluate_final_gate(inputs, thresholds=th).passed is True


def test_landscape_relaxation_does_not_waive_other_integrity_failures() -> None:
    # A zero-tension corpus that also fails an integrity check still fails —
    # landscape lifts ONLY the tension floor, nothing else.
    inputs = _green_inputs(n_tensions=0, n_receipts=12, rob_coverage=0.1)
    th = landscape_thresholds(
        inputs.n_receipts,
        inputs.n_tensions,
        declared_review_type="evidence_map",
    )
    result = evaluate_final_gate(inputs, thresholds=th)
    assert result.passed is False
    assert any("rob_coverage" in f for f in result.failures)
    assert not any("n_tensions" in f for f in result.failures)
