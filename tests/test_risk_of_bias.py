from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from risk_of_bias import (  # noqa: E402
    SCREENING_LABEL,
    RiskOfBiasAssessment,
    assess_risk_of_bias,
)


def test_low_risk_rct_screening_is_json_friendly() -> None:
    assessment = assess_risk_of_bias({
        "tier": "A1",
        "directness": "direct",
        "study_design": "randomized controlled trial",
    })

    assert assessment.overall == "low"
    assert assessment.label == SCREENING_LABEL
    assert assessment.to_dict()["domains"]["randomization_or_selection"] == "low"


def test_explicit_high_rob_metadata_hint_overrides_defaults() -> None:
    assessment = assess_risk_of_bias({
        "tier": "A1",
        "directness": "direct",
        "metadata": {"risk_of_bias": "high"},
    })

    assert assessment.overall == "high"
    assert assessment.basis == ("explicit_metadata_hint:high",)


def test_indirect_mechanistic_rct_cannot_screen_as_low_risk() -> None:
    assessment = assess_risk_of_bias({
        "tier": "A1",
        "directness": "mechanistic",
        "design_tier": "RCT",
    })

    assert assessment.overall == "some_concerns"
    assert "mechanistic_preclinical_bias_floor" in assessment.basis


def test_invalid_or_missing_fields_fail_closed() -> None:
    assessment = assess_risk_of_bias({"tier": "A1"})

    assert assessment.overall == "high"
    assert assessment.fail_closed
    assert assessment.basis == ("missing_or_invalid_tier_or_directness",)


def test_review_receipts_are_valid_some_concerns() -> None:
    assessment = assess_risk_of_bias({
        "tier": "B1",
        "directness": "review",
    })

    assert assessment.overall == "some_concerns"
    assert not assessment.fail_closed


def test_assessment_dataclass_is_frozen() -> None:
    assessment = RiskOfBiasAssessment(
        label=SCREENING_LABEL,
        overall="low",
        domains={},
        basis=(),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        assessment.overall = "high"  # type: ignore[misc]
