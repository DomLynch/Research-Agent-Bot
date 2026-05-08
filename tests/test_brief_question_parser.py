"""BRIEFS-V1 Phase 1 question parser tests."""
from __future__ import annotations

import pytest

from agent.briefs import BriefQuery, parse_question


def test_parse_metformin_cognition_t2d_older_adults() -> None:
    q = parse_question(
        "What does the evidence say about metformin for cognitive "
        "prevention in T2D patients 65+?"
    )
    assert q == BriefQuery(
        question=(
            "What does the evidence say about metformin for cognitive "
            "prevention in T2D patients 65+?"
        ),
        interventions=("metformin",),
        outcome_classes=("cognitive",),
        population="T2D",
        age_range=(65, 120),
    )


def test_parse_multi_intervention_mortality_question() -> None:
    q = parse_question(
        "statins and PCSK9 inhibitors for cardiovascular mortality "
        "in older adults"
    )
    assert q.interventions == ("statins", "pcsk9 inhibitors")
    assert q.outcome_classes == ("cardiometabolic", "longevity")
    assert q.population == "older adults"


def test_parse_population_and_comorbidity_separately() -> None:
    q = parse_question(
        "GLP-1 receptor agonists for weight loss and inflammation "
        "in people with obesity and CKD"
    )
    assert q.interventions == ("glp-1 receptor agonists",)
    assert q.outcome_classes == ("cardiometabolic", "immune")
    assert q.population == "obesity"
    assert q.comorbidities == ("CKD",)


def test_parse_age_ranges() -> None:
    assert parse_question("creatine for cognition ages 55-75").age_range == (
        55, 75,
    )
    assert parse_question("omega-3 for dementia under 50").age_range == (
        0, 50,
    )


def test_to_dict_is_json_ready() -> None:
    q = parse_question("metformin for mortality over 65")
    assert q.to_dict()["age_range"] == [65, 120]
    assert q.to_dict()["interventions"] == ["metformin"]


def test_blank_question_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        parse_question("  ")
