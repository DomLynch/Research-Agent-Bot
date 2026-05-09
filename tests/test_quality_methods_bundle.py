"""Tests for the Phase 4 quality-methods bundle builder."""
from __future__ import annotations

import pytest

from agent.quality_methods_bundle import (
    build_quality_methods_bundle,
    compute_grade_coverage,
    compute_rob_coverage,
)
from agent.risk_of_bias_schema import (
    ROB2_DOMAINS,
    DomainAssessment,
    StudyAssessment,
)
from agent.grade_schema import GradeAssessment


def _rob_json(study_id: str, *, rating: str = "low") -> dict:
    return {
        "study_id": study_id, "design": "rct", "tool": "rob2",
        "overall_rating": rating,
        "domains": [{"domain": d, "rating": rating} for d in ROB2_DOMAINS],
    }


def _grade_json(outcome: str, *, downgrade_levels: int = 0) -> dict:
    payload: dict = {
        "outcome": outcome, "starting_certainty": "high",
        "downgrades": [], "upgrades": [],
    }
    if downgrade_levels > 0:
        payload["downgrades"] = [
            {"reason": "rob", "levels": min(2, downgrade_levels)}
        ]
        if downgrade_levels > 2:
            payload["downgrades"].append(
                {"reason": "imprecision", "levels": downgrade_levels - 2}
            )
    return payload


# ---- compute_rob_coverage / compute_grade_coverage ------------------------


def test_rob_coverage_zero_when_no_assessments() -> None:
    assert compute_rob_coverage([], 5) == 0.0


def test_rob_coverage_one_when_all_assessed() -> None:
    rob = [
        StudyAssessment(
            f"S{i}", "rct", "rob2",
            tuple(DomainAssessment(d, "low") for d in ROB2_DOMAINS),
            "low",
        )
        for i in range(3)
    ]
    assert compute_rob_coverage(rob, 3) == 1.0


def test_rob_coverage_clamps_at_one_when_assessed_exceed_receipts() -> None:
    rob = [
        StudyAssessment(
            f"S{i}", "rct", "rob2",
            tuple(DomainAssessment(d, "low") for d in ROB2_DOMAINS),
            "low",
        )
        for i in range(10)
    ]
    assert compute_rob_coverage(rob, 5) == 1.0


def test_rob_coverage_zero_when_receipt_count_zero() -> None:
    rob = [
        StudyAssessment(
            "S", "rct", "rob2",
            tuple(DomainAssessment(d, "low") for d in ROB2_DOMAINS),
            "low",
        )
    ]
    assert compute_rob_coverage(rob, 0) == 0.0


def test_grade_coverage_zero_when_no_assessments() -> None:
    assert compute_grade_coverage([], 5) == 0.0


def test_grade_coverage_handles_unique_outcomes() -> None:
    grades = [
        GradeAssessment("immune", "high"),
        GradeAssessment("immune", "low"),  # same outcome, dedup
        GradeAssessment("cardiometabolic", "high"),
    ]
    assert compute_grade_coverage(grades, 5) == 0.4  # 2 unique / 5


def test_grade_coverage_zero_when_outcome_count_zero() -> None:
    grades = [GradeAssessment("x", "high")]
    assert compute_grade_coverage(grades, 0) == 0.0


# ---- build_quality_methods_bundle: fully populated ------------------------


def test_full_bundle_renders_both_sections() -> None:
    rob = [_rob_json("Moel 2025"), _rob_json("Stanfield 2026")]
    grade = [_grade_json("Cardiometabolic", downgrade_levels=2)]
    bundle = build_quality_methods_bundle(
        rob_payload=rob, grade_payload=grade,
        receipt_count=3, outcome_count=1,
    )
    assert "Quality Methods Bundle" in bundle.markdown
    assert "Moel 2025" in bundle.markdown
    assert "Stanfield 2026" in bundle.markdown
    assert "Cardiometabolic" in bundle.markdown
    assert bundle.rob_coverage == pytest.approx(2 / 3)
    assert bundle.grade_coverage == 1.0
    assert bundle.receipt_count == 3
    assert bundle.outcome_count == 1


def test_full_bundle_persists_validated_dataclasses() -> None:
    rob = [_rob_json("S")]
    grade = [_grade_json("X")]
    bundle = build_quality_methods_bundle(
        rob_payload=rob, grade_payload=grade,
        receipt_count=1, outcome_count=1,
    )
    assert isinstance(bundle.rob_assessments, tuple)
    assert isinstance(bundle.grade_assessments, tuple)
    assert bundle.rob_assessments[0].study_id == "S"
    assert bundle.grade_assessments[0].outcome == "X"


# ---- build_quality_methods_bundle: missing data ---------------------------


def test_missing_rob_yields_zero_coverage_and_placeholder() -> None:
    bundle = build_quality_methods_bundle(
        rob_payload=None, grade_payload=[_grade_json("X")],
        receipt_count=3, outcome_count=1,
    )
    assert bundle.rob_coverage == 0.0
    assert "_No RoB data provided._" in bundle.markdown
    # GRADE still rendered
    assert "X" in bundle.markdown


def test_missing_grade_yields_zero_coverage_and_placeholder() -> None:
    bundle = build_quality_methods_bundle(
        rob_payload=[_rob_json("S")], grade_payload=None,
        receipt_count=1, outcome_count=2,
    )
    assert bundle.grade_coverage == 0.0
    assert "_No GRADE data provided._" in bundle.markdown


def test_both_missing_renders_both_placeholders_zero_coverage() -> None:
    bundle = build_quality_methods_bundle(
        rob_payload=None, grade_payload=None,
        receipt_count=3, outcome_count=2,
    )
    assert bundle.rob_coverage == 0.0
    assert bundle.grade_coverage == 0.0
    assert "_No RoB data provided._" in bundle.markdown
    assert "_No GRADE data provided._" in bundle.markdown


def test_empty_payloads_treated_as_missing() -> None:
    bundle = build_quality_methods_bundle(
        rob_payload=[], grade_payload=[],
        receipt_count=3, outcome_count=2,
    )
    assert bundle.rob_coverage == 0.0
    assert bundle.grade_coverage == 0.0


# ---- build_quality_methods_bundle: validation -----------------------------


def test_invalid_rob_rating_propagates_value_error() -> None:
    bad = [{
        "study_id": "X", "design": "rct", "tool": "rob2",
        "overall_rating": "low",
        "domains": [{"domain": ROB2_DOMAINS[0], "rating": "BOGUS"}],
    }]
    with pytest.raises(ValueError, match="invalid rating"):
        build_quality_methods_bundle(
            rob_payload=bad, grade_payload=None,
            receipt_count=1, outcome_count=1,
        )


def test_invalid_grade_certainty_propagates_value_error() -> None:
    bad = [{"outcome": "x", "starting_certainty": "BOGUS"}]
    with pytest.raises(ValueError, match="starting_certainty"):
        build_quality_methods_bundle(
            rob_payload=None, grade_payload=bad,
            receipt_count=1, outcome_count=1,
        )


def test_negative_counts_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="must be ≥0"):
        build_quality_methods_bundle(
            rob_payload=None, grade_payload=None,
            receipt_count=-1, outcome_count=0,
        )


def test_invalid_coverage_rejected_in_dataclass_post_init() -> None:
    """Direct dataclass construction with out-of-range coverage must fail."""
    from agent.quality_methods_bundle import QualityMethodsBundle
    with pytest.raises(ValueError, match="rob_coverage"):
        QualityMethodsBundle(
            rob_assessments=(), grade_assessments=(),
            rob_coverage=1.5, grade_coverage=0.5,
            receipt_count=1, outcome_count=1,
            markdown="",
        )


# ---- build_quality_methods_bundle: real-shape input -----------------------


def test_realistic_3_rcts_5_outcomes_partial_coverage() -> None:
    """3 RCTs + 5 outcome classes, but only 2 RoBs + 1 GRADE done — partial coverage."""
    rob = [_rob_json("Moel 2025"), _rob_json("Stanfield 2026")]
    grade = [_grade_json("Cardiometabolic")]
    bundle = build_quality_methods_bundle(
        rob_payload=rob, grade_payload=grade,
        receipt_count=3, outcome_count=5,
    )
    assert bundle.rob_coverage == pytest.approx(2 / 3)
    assert bundle.grade_coverage == 0.2
    # Both sections populated; no placeholders
    assert "_No RoB data provided._" not in bundle.markdown
    assert "_No GRADE data provided._" not in bundle.markdown


def test_duplicate_rob_study_ids_rejected_by_renderer() -> None:
    """Two RoBs with the same study_id is a data error; the renderer's
    assert_studies_unique guard fails closed."""
    rob = [_rob_json("Same Study"), _rob_json("Same Study", rating="some_concerns")]
    with pytest.raises(ValueError, match="duplicate study_id"):
        build_quality_methods_bundle(
            rob_payload=rob, grade_payload=None,
            receipt_count=4, outcome_count=1,
        )
