"""BRIEFS-V1 Phase 3 receipt filter tests."""
from __future__ import annotations

from agent.briefs import filter_receipts, parse_question


def test_filter_receipts_by_outcome_class() -> None:
    manifest = {"receipts": [
        {"receipt_id": "r1", "outcome_class": "cognitive"},
        {"receipt_id": "r2", "outcome_class": "cardiometabolic"},
    ]}
    q = parse_question("metformin for cognition in T2D patients 65+")
    out = filter_receipts(manifest, q)
    assert [r["receipt_id"] for r in out] == ["r1"]


def test_population_signal_selects_relevant_subset() -> None:
    manifest = {"receipts": [
        {
            "receipt_id": "generic_weight_trial",
            "outcome_class": "cardiometabolic",
        },
        {
            "receipt_id": "semaglutide_obesity_weight_trial",
            "outcome_class": "cardiometabolic",
        },
    ]}
    q = parse_question("GLP-1 receptor agonists for weight loss in obesity")
    out = filter_receipts(manifest, q)
    assert [r["receipt_id"] for r in out] == [
        "semaglutide_obesity_weight_trial",
    ]


def test_sparse_population_metadata_does_not_empty_outcome_matches() -> None:
    manifest = {"receipts": [
        {"receipt_id": "a", "outcome_class": "cardiometabolic"},
        {"receipt_id": "b", "outcome_class": "cardiometabolic"},
    ]}
    q = parse_question("GLP-1 receptor agonists for weight loss in obesity")
    out = filter_receipts(manifest, q)
    assert [r["receipt_id"] for r in out] == ["a", "b"]


def test_comorbidity_and_age_increase_relevance() -> None:
    manifest = {"receipts": [
        {
            "receipt_id": "omega3_ckd_older_adults",
            "outcome_class": "cardiometabolic",
        },
        {
            "receipt_id": "omega3_general_adults",
            "outcome_class": "cardiometabolic",
        },
    ]}
    q = parse_question("omega-3 for cardiovascular outcomes in CKD aged 65+")
    out = filter_receipts(manifest, q)
    assert out[0]["receipt_id"] == "omega3_ckd_older_adults"


def test_empty_or_malformed_manifest_returns_empty_tuple() -> None:
    assert filter_receipts({}, parse_question("metformin for mortality")) == ()
    assert filter_receipts(
        {"receipts": ["bad"]}, parse_question("metformin for mortality"),
    ) == ()
