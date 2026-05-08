from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import novel_framework as nf  # noqa: E402


def _manifest() -> dict:
    return {
        "receipts": [
            {
                "receipt_id": "r1",
                "outcome_class": "cardiometabolic",
                "directness": "direct",
                "effect_direction": "positive",
            },
            {
                "receipt_id": "r2",
                "outcome_class": "cardiometabolic",
                "directness": "mechanistic",
                "effect_direction": "positive",
            },
            {
                "receipt_id": "r3",
                "outcome_class": "frailty",
                "directness": "mechanistic",
                "effect_direction": "positive",
            },
            {
                "receipt_id": "r4",
                "outcome_class": "frailty",
                "directness": "review",
                "effect_direction": "null",
            },
        ],
    }


def test_boundary_condition_matrix_shape_from_manifest_claims_tensions() -> None:
    matrix = nf.build_boundary_condition_matrix(
        _manifest(),
        claims=(
            {
                "outcome_class": "frailty",
                "directness": "indirect",
                "effect_direction": "mixed",
            },
        ),
        tensions=(
            {"outcome_class": "frailty", "severity": 4},
            {"outcome_class": "cardiometabolic", "severity": 1},
        ),
    )

    assert [r.outcome_class for r in matrix] == ["cardiometabolic", "frailty"]
    frailty = next(r for r in matrix if r.outcome_class == "frailty")
    assert frailty.direct_receipts == 0
    assert frailty.indirect_receipts == 1
    assert frailty.mechanistic_receipts == 1
    assert frailty.review_receipts == 1
    assert frailty.max_conflict_severity == 4
    assert frailty.boundary == "conflict-resolution gap"


def test_gap_priority_orders_by_directness_and_conflict() -> None:
    matrix = nf.build_boundary_condition_matrix(
        _manifest(),
        claims=(
            {
                "outcome_class": "frailty",
                "directness": "indirect",
                "effect_direction": "mixed",
            },
        ),
        tensions=({"outcome_class": "frailty", "severity": 4},),
    )

    priorities = nf.rank_gap_priorities(matrix)

    assert priorities[0].outcome_class == "frailty"
    assert priorities[0].score > priorities[-1].score
    assert "conflict severity 4" in priorities[0].rationale


def test_trial_design_recommendation_fails_closed_when_data_thin() -> None:
    matrix = nf.build_boundary_condition_matrix(
        {
            "receipts": [
                {
                    "outcome_class": "immune",
                    "directness": "mechanistic",
                    "effect_direction": "positive",
                }
            ],
        },
    )
    gap = nf.rank_gap_priorities(matrix)[0]

    recommendation = nf.build_trial_design_recommendation(gap, matrix)

    assert recommendation.fail_closed is True
    assert "expand the corpus" in recommendation.recommendation
    assert recommendation.endpoint_class == "immune"


def test_trial_design_recommendation_uses_generic_endpoint_class() -> None:
    matrix = nf.build_boundary_condition_matrix(
        _manifest(),
        claims=(
            {
                "outcome_class": "frailty",
                "directness": "indirect",
                "effect_direction": "mixed",
            },
        ),
        tensions=({"outcome_class": "frailty", "severity": 4},),
    )
    gap = nf.rank_gap_priorities(matrix)[0]

    recommendation = nf.build_trial_design_recommendation(gap, matrix)

    assert recommendation.fail_closed is False
    assert "pre-registered frailty endpoint class" in recommendation.recommendation
    assert "direct-vs-mechanistic endpoint separation" in recommendation.recommendation


def test_novel_framework_proposal_is_validated_scaffold_only() -> None:
    matrix = nf.build_boundary_condition_matrix(
        _manifest(),
        claims=(
            {
                "outcome_class": "frailty",
                "directness": "indirect",
                "effect_direction": "mixed",
            },
        ),
        tensions=({"outcome_class": "frailty", "severity": 4},),
    )
    gaps = nf.rank_gap_priorities(matrix)

    proposal = nf.propose_novel_framework(matrix, gaps)

    assert proposal.validation_status == "validated_scaffold"
    assert proposal.axes == (
        "outcome_class",
        "directness",
        "effect_direction",
        "conflict_severity",
    )
    assert "deterministic map" in proposal.premise


def test_novel_framework_fails_closed_when_structured_evidence_thin() -> None:
    proposal = nf.propose_novel_framework((), ())

    assert proposal.validation_status == "insufficient_structured_evidence"
    assert proposal.axes == ()


def test_research_contribution_layer_has_no_topic_specific_branches() -> None:
    source = inspect.getsource(nf).lower()
    forbidden = (
        "metformin",
        "rapamycin",
        "glp1",
        "statins",
        "omega3",
        "creatine",
        "if topic",
    )

    assert not any(needle in source for needle in forbidden)


def test_helper_lives_outside_agent_runtime_package() -> None:
    path = Path(inspect.getfile(nf)).as_posix()
    assert "/scripts/novel_framework.py" in path
    assert "/agent/" not in path
