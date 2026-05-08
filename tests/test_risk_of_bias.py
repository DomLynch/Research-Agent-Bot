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
    assess_risk_of_bias_batch,
    assess_risk_of_bias_batch_json,
    assess_risk_of_bias,
    to_stable_json,
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


def test_batch_assesses_receipts_grouped_by_outcome() -> None:
    grouped = {
        "mortality": ({"tier": "A1", "directness": "direct"},),
        "frailty": ({"tier": "C1", "directness": "mechanistic"},),
    }

    assessed = assess_risk_of_bias_batch(grouped)

    assert tuple(assessed) == ("frailty", "mortality")
    assert assessed["mortality"][0].overall == "low"
    assert assessed["frailty"][0].overall == "high"


def test_stable_json_serializer_sorts_keys_and_is_compact() -> None:
    assessment = assess_risk_of_bias({"directness": "direct", "tier": "A1"})

    assert to_stable_json({"z": assessment, "a": 1}).startswith(
        '{"a":1,"z":{"basis":["randomized_or_top_tier_default"]'
    )


def test_batch_json_is_stable() -> None:
    payload = assess_risk_of_bias_batch_json({
        "mortality": ({"tier": "A1", "directness": "direct"},)
    })

    assert payload.startswith('{"mortality":[{"basis":["randomized_or_top_tier_default"]')
