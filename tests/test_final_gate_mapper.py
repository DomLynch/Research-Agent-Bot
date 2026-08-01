"""Tests for the Phase 8 final-gate input mapper."""
from __future__ import annotations

import pytest

from agent.final_gate import GateInputs, evaluate_final_gate
from agent.final_gate_mapper import (
    build_gate_inputs,
    build_gate_inputs_from_artifacts,
    extract_audit_gates_passed,
    extract_journal_surface_passed,
    extract_unresolved_reviewer_p1_count,
)
from agent.quality_methods_bundle import build_quality_methods_bundle
from agent.risk_of_bias_schema import ROB2_DOMAINS
from agent.template_gate_adapter import evaluate_template_gate


def _rob_json(study_id: str) -> dict:
    return {
        "study_id": study_id, "design": "rct", "tool": "rob2",
        "overall_rating": "low",
        "domains": [{"domain": d, "rating": "low"} for d in ROB2_DOMAINS],
    }


def _full_quality_bundle(receipt_count: int = 34, outcome_count: int = 1):
    return build_quality_methods_bundle(
        rob_payload=[_rob_json(f"S{i}") for i in range(receipt_count)],
        grade_payload=[{"outcome": "x", "starting_certainty": "high"}],
        receipt_count=receipt_count, outcome_count=outcome_count,
    )


# ---- extract_audit_gates_passed ------------------------------------------


def test_audit_all_pass_true_returns_true() -> None:
    assert extract_audit_gates_passed({"all_pass": True}) is True


def test_audit_p1_pass_without_counts_fails_closed() -> None:
    assert extract_audit_gates_passed(
        {"p1_pass": True, "score": 10, "max_score": 10}
    ) is False


def test_audit_p1_pass_with_partial_score_fails_closed() -> None:
    assert extract_audit_gates_passed(
        {"p1_pass": True, "score": 8.5, "max_score": 10}
    ) is False


def test_audit_pass_rate_string_without_counts_fails_closed() -> None:
    assert extract_audit_gates_passed(
        {"p1_pass": True, "pass_rate": "14/14"}
    ) is False
    assert extract_audit_gates_passed(
        {"p1_pass": True, "pass_rate": "10/14"}
    ) is False


def test_audit_pass_count_total_count_format() -> None:
    assert extract_audit_gates_passed(
        {"pass_count": 14, "total_count": 14}
    ) is True
    assert extract_audit_gates_passed(
        {"pass_count": 12, "total_count": 14}
    ) is False


def test_audit_none_returns_false_fail_closed() -> None:
    assert extract_audit_gates_passed(None) is False


def test_audit_unrecognised_shape_returns_false_fail_closed() -> None:
    assert extract_audit_gates_passed({"random": "data"}) is False


# ---- extract_journal_surface_passed --------------------------------------


def test_journal_surface_pass_field() -> None:
    assert extract_journal_surface_passed({"pass": True}) is True
    assert extract_journal_surface_passed({"pass": False}) is False


def test_journal_surface_passed_field() -> None:
    assert extract_journal_surface_passed({"passed": True}) is True


def test_journal_surface_verdict_strings() -> None:
    assert extract_journal_surface_passed({"verdict": "pass"}) is True
    assert extract_journal_surface_passed({"verdict": "PASS"}) is True
    assert extract_journal_surface_passed({"verdict": "fail"}) is False


def test_journal_surface_none_returns_false_fail_closed() -> None:
    assert extract_journal_surface_passed(None) is False


# ---- extract_unresolved_reviewer_p1_count --------------------------------


def test_unresolved_p1_direct_count() -> None:
    assert extract_unresolved_reviewer_p1_count(
        {"unresolved_p1_count": 3}
    ) == 3
    assert extract_unresolved_reviewer_p1_count(
        {"unresolved_p1_count": 0}
    ) == 0


def test_unresolved_p1_from_patch_list() -> None:
    patches = {"patches": [
        {"severity": "P1", "status": "unresolved"},
        {"severity": "P1", "status": "applied"},
        {"severity": "P1", "status": "auto_strip"},
        {"severity": "P2", "status": "unresolved"},
        {"severity": "P1", "status": "resolved"},
    ]}
    assert extract_unresolved_reviewer_p1_count(patches) == 1


def test_unresolved_p1_missing_artifact_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing or malformed"):
        extract_unresolved_reviewer_p1_count(None)


def test_unresolved_p1_empty_patches_returns_zero() -> None:
    assert extract_unresolved_reviewer_p1_count({"patches": []}) == 0


# ---- build_gate_inputs (direct path) -------------------------------------


def test_build_gate_inputs_returns_typed_gate_inputs() -> None:
    inputs = build_gate_inputs(
        numeric_coverage=1.0, citation_registry_complete=True,
        audit_gates_passed=True, journal_surface_passed=True,
        unresolved_reviewer_p1_count=0,
        rob_coverage=0.9, grade_coverage=1.0,
        n_tensions=5, n_receipts=34, template_language_blocking=False,
    )
    assert isinstance(inputs, GateInputs)
    assert inputs.audit_gates_passed is True
    assert inputs.rob_coverage == 0.9


def test_build_gate_inputs_passes_through_to_final_gate() -> None:
    inputs = build_gate_inputs(
        numeric_coverage=1.0, citation_registry_complete=True,
        audit_gates_passed=True, journal_surface_passed=True,
        unresolved_reviewer_p1_count=0,
        rob_coverage=1.0, grade_coverage=1.0,
        n_tensions=5, n_receipts=34, template_language_blocking=False,
    )
    result = evaluate_final_gate(inputs)
    assert result.passed
    assert result.failures == ()


def test_build_gate_inputs_coverce_int_floats() -> None:
    """Caller may pass numpy/decimal etc; mapper must coerce."""
    inputs = build_gate_inputs(
        numeric_coverage=1.0, citation_registry_complete=1,  # type: ignore[arg-type]
        audit_gates_passed=1, journal_surface_passed=1,  # type: ignore[arg-type]
        unresolved_reviewer_p1_count=0.0,  # type: ignore[arg-type]
        rob_coverage=1.0, grade_coverage=1.0,
        n_tensions=5.0,  # type: ignore[arg-type]
        n_receipts=34,
        template_language_blocking=0,  # type: ignore[arg-type]
    )
    assert inputs.audit_gates_passed is True
    assert inputs.template_language_blocking is False


def test_build_gate_inputs_invalid_coverage_propagates_value_error() -> None:
    with pytest.raises(ValueError, match="numeric_coverage"):
        build_gate_inputs(
            numeric_coverage=1.5, citation_registry_complete=True,
            audit_gates_passed=True, journal_surface_passed=True,
            unresolved_reviewer_p1_count=0,
            rob_coverage=1.0, grade_coverage=1.0,
            n_tensions=5, n_receipts=34, template_language_blocking=False,
        )


# ---- build_gate_inputs_from_artifacts (artifact path) --------------------


def test_from_artifacts_full_pass() -> None:
    qm = _full_quality_bundle()
    tg = evaluate_template_gate("Clean paper text.")
    inputs = build_gate_inputs_from_artifacts(
        audit={"all_pass": True},
        journal_surface={"pass": True},
        reviewer_patches={"unresolved_p1_count": 0},
        template_gate=tg, quality_methods=qm,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=5, n_receipts=34,
    )
    assert inputs.audit_gates_passed is True
    assert inputs.journal_surface_passed is True
    assert inputs.unresolved_reviewer_p1_count == 0
    assert inputs.rob_coverage == 1.0
    assert inputs.template_language_blocking is False
    result = evaluate_final_gate(inputs)
    assert result.passed


def test_from_artifacts_missing_audit_fails_audit_gate() -> None:
    qm = _full_quality_bundle()
    tg = evaluate_template_gate("Clean text.")
    inputs = build_gate_inputs_from_artifacts(
        audit=None,
        journal_surface={"pass": True},
        reviewer_patches={"patches": []},
        template_gate=tg, quality_methods=qm,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=5, n_receipts=34,
    )
    assert inputs.audit_gates_passed is False
    result = evaluate_final_gate(inputs)
    assert "audit_gates_failed" in result.failures


def test_from_artifacts_dirty_template_gate_blocks_final() -> None:
    qm = _full_quality_bundle()
    tg = evaluate_template_gate("It is clear that.")  # P1 hit
    inputs = build_gate_inputs_from_artifacts(
        audit={"all_pass": True},
        journal_surface={"pass": True},
        reviewer_patches={"patches": []},
        template_gate=tg, quality_methods=qm,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=5, n_receipts=34,
    )
    assert inputs.template_language_blocking is True
    result = evaluate_final_gate(inputs)
    assert "template_language_gate_blocking" in result.failures


def test_from_artifacts_partial_quality_coverage_propagates() -> None:
    """Quality methods bundle's coverage flows into gate inputs verbatim."""
    qm = build_quality_methods_bundle(
        rob_payload=[_rob_json("S1"), _rob_json("S2")],  # 2 of 10
        grade_payload=[{"outcome": "x", "starting_certainty": "high"}],
        receipt_count=10, outcome_count=2,
    )
    tg = evaluate_template_gate("Clean.")
    inputs = build_gate_inputs_from_artifacts(
        audit={"all_pass": True},
        journal_surface={"pass": True},
        reviewer_patches={"patches": []},
        template_gate=tg, quality_methods=qm,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=5, n_receipts=10,
    )
    assert inputs.rob_coverage == pytest.approx(0.2)
    assert inputs.grade_coverage == pytest.approx(0.5)


def test_from_artifacts_unresolved_reviewer_blocks() -> None:
    qm = _full_quality_bundle()
    tg = evaluate_template_gate("Clean.")
    patches = {"patches": [
        {"severity": "P1", "status": "unresolved"},
    ]}
    inputs = build_gate_inputs_from_artifacts(
        audit={"all_pass": True},
        journal_surface={"pass": True},
        reviewer_patches=patches,
        template_gate=tg, quality_methods=qm,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=5, n_receipts=34,
    )
    assert inputs.unresolved_reviewer_p1_count == 1
    result = evaluate_final_gate(inputs)
    assert any("unresolved_reviewer_p1" in f for f in result.failures)


def test_from_artifacts_journal_surface_failure_blocks() -> None:
    qm = _full_quality_bundle()
    tg = evaluate_template_gate("Clean.")
    inputs = build_gate_inputs_from_artifacts(
        audit={"all_pass": True},
        journal_surface={"verdict": "fail"},
        reviewer_patches={"patches": []},
        template_gate=tg, quality_methods=qm,
        numeric_coverage=1.0, citation_registry_complete=True,
        n_tensions=5, n_receipts=34,
    )
    assert inputs.journal_surface_passed is False
    result = evaluate_final_gate(inputs)
    assert "journal_surface_failed" in result.failures
