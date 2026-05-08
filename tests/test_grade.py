from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from grade_assessment import (  # noqa: E402
    GradeAssessment,
    assess_grade,
    assess_grade_batch,
    assess_grade_batch_json,
    to_stable_json,
)


def test_low_risk_direct_rct_is_high_certainty() -> None:
    grade = assess_grade("walk speed", {
        "tier": "A1",
        "directness": "direct",
        "risk_of_bias": "low",
        "inconsistency": "not_serious",
        "imprecision": "not_serious",
    })

    assert grade.certainty == "high"
    assert grade.start_certainty == "high"
    assert grade.downgrades == ()


def test_high_risk_of_bias_downgrades_certainty() -> None:
    grade = assess_grade("walk speed", {
        "tier": "A1",
        "directness": "direct",
        "risk_of_bias": "high",
    })

    assert grade.certainty == "moderate"
    assert grade.downgrades == ("risk_of_bias:serious",)


def test_indirect_evidence_is_capped() -> None:
    grade = assess_grade("mortality", {
        "tier": "B1",
        "directness": "indirect",
        "risk_of_bias": "low",
    })

    assert grade.certainty == "low"
    assert grade.caps == ("indirect_evidence_cap:low",)


def test_review_evidence_is_capped_like_indirect_evidence() -> None:
    grade = assess_grade("mortality", {
        "tier": "B1",
        "directness": "review",
        "risk_of_bias": "low",
    })

    assert grade.certainty == "low"
    assert grade.caps == ("review_evidence_cap:low",)


def test_preclinical_evidence_is_capped() -> None:
    grade = assess_grade("healthspan", {
        "tier": "A1",
        "directness": "preclinical",
        "risk_of_bias": "low",
    })

    assert grade.certainty == "low"
    assert grade.caps == ("preclinical_evidence_cap:low",)


def test_invalid_or_missing_fields_fail_closed() -> None:
    grade = assess_grade("mortality", {"directness": "direct"})

    assert grade.certainty == "very_low"
    assert grade.fail_closed
    assert grade.downgrades == ("missing_or_invalid_required_fields",)


def test_grade_dataclass_is_frozen_and_json_friendly() -> None:
    grade = GradeAssessment(
        outcome="mortality",
        certainty="high",
        start_certainty="high",
        downgrades=(),
        caps=(),
    )

    assert grade.to_dict()["certainty"] == "high"
    with pytest.raises(dataclasses.FrozenInstanceError):
        grade.certainty = "low"  # type: ignore[misc]


def test_batch_summarizes_receipts_grouped_by_outcome_fail_closed() -> None:
    grades = assess_grade_batch({
        "mortality": (
            {"tier": "A1", "directness": "direct", "risk_of_bias": "low"},
            {"tier": "C1", "directness": "mechanistic", "risk_of_bias": "high"},
        ),
        "frailty": ({"tier": "A1"},),
    })

    by_outcome = {grade.outcome: grade for grade in grades}
    assert by_outcome["mortality"].certainty == "very_low"
    assert by_outcome["mortality"].start_certainty == "high"
    assert by_outcome["frailty"].fail_closed


def test_grade_stable_json_serializer_sorts_keys_and_is_compact() -> None:
    grade = assess_grade("mortality", {"tier": "A1", "directness": "direct"})

    assert to_stable_json({"z": grade, "a": 1}).startswith(
        '{"a":1,"z":{"caps":[],"certainty":"high"'
    )


def test_grade_batch_json_is_stable() -> None:
    payload = assess_grade_batch_json({
        "mortality": ({"tier": "A1", "directness": "direct"},)
    })

    assert payload.startswith('[{"caps":[],"certainty":"high"')
