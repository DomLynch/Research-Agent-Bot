"""Tests for the Phase 3 deterministic field-framework engagement primitive."""
from __future__ import annotations

import pytest

from agent.field_engagement import (
    FIELD_FRAMEWORK_REGISTRY,
    Framework,
    FrameworkEngagement,
    evaluate_engagement,
)


def _by_name(results, name: str) -> FrameworkEngagement:
    for e in results:
        if e.framework_name == name:
            return e
    raise AssertionError(f"framework {name!r} not in results")


def test_empty_corpus_marks_all_frameworks_insufficient() -> None:
    results = evaluate_engagement(receipts=[], background_refs=[])
    assert {e.framework_name for e in results} == {f.name for f in FIELD_FRAMEWORK_REGISTRY}
    for e in results:
        assert e.status == "insufficient"
        assert e.matched_receipts == ()
        assert e.matched_background_refs == ()


def test_registry_names_expected_five_frameworks() -> None:
    names = {f.name for f in FIELD_FRAMEWORK_REGISTRY}
    assert names == {"Mannick", "Lamming", "Kennedy", "Kaeberlein", "Lopez-Otin"}


def test_positive_primary_match_yields_support() -> None:
    receipts = [
        {"receipt_id": "Mannick 2018 PIE", "authors": ["Mannick"],
         "outcome_class": "immune", "effect_direction": "positive"},
    ]
    e = _by_name(evaluate_engagement(receipts=receipts), "Mannick")
    assert e.status == "support"
    assert e.matched_receipts == ("Mannick 2018 PIE",)


def test_negative_primary_match_yields_challenge() -> None:
    receipts = [
        {"receipt_id": "Lamming RCT", "citation_token": "Lamming 2012",
         "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ]
    e = _by_name(evaluate_engagement(receipts=receipts), "Lamming")
    assert e.status == "challenge"


def test_positive_primary_plus_adjacent_yields_extends() -> None:
    receipts = [
        {"receipt_id": "Mannick 2018", "authors": ["Mannick"],
         "outcome_class": "immune", "effect_direction": "positive"},
        {"receipt_id": "Mannick 2014", "authors": ["Mannick"],
         "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ]
    e = _by_name(evaluate_engagement(receipts=receipts), "Mannick")
    assert e.status == "extends"
    assert "Mannick 2018" in e.matched_receipts
    assert "Mannick 2014" in e.matched_receipts


def test_background_ref_only_falls_closed_to_insufficient() -> None:
    """A background-ref-only match has no effect_direction signal so cannot
    establish support; the function fails closed to insufficient."""
    e = _by_name(
        evaluate_engagement(
            receipts=[],
            background_refs=[{"citation_token": "Mannick 2014"}],
        ),
        "Mannick",
    )
    assert e.status == "insufficient"
    assert e.matched_background_refs == ("Mannick 2014",)


def test_accent_normalization_for_lopez_otin() -> None:
    receipts = [
        {"receipt_id": "X", "citation_token": "López-Otín 2023",
         "outcome_class": "hallmarks", "effect_direction": "supports"},
    ]
    e = _by_name(evaluate_engagement(receipts=receipts), "Lopez-Otin")
    assert e.status == "support"


def test_kaeberlein_recognises_dap_anchor_authors() -> None:
    receipts = [
        {"receipt_id": "Urfer 2017", "authors": ["Urfer"],
         "outcome_class": "companion_animal", "effect_direction": "positive"},
    ]
    e = _by_name(evaluate_engagement(receipts=receipts), "Kaeberlein")
    assert e.status == "support"


def test_unrelated_receipt_does_not_match_any_framework() -> None:
    receipts = [
        {"receipt_id": "Random 2020", "authors": ["Random"],
         "outcome_class": "lifespan", "effect_direction": "positive"},
    ]
    results = evaluate_engagement(receipts=receipts)
    for e in results:
        assert e.matched_receipts == ()
        assert e.status == "insufficient"


def test_caller_can_pass_custom_framework_subset() -> None:
    custom = (
        Framework(
            name="TestOnly",
            primary_claim="Test claim",
            primary_domains=("immune",),
            adjacent_domains=(),
            anchor_authors=("smith",),
        ),
    )
    receipts = [{"receipt_id": "Smith 2024", "authors": ["Smith"],
                 "outcome_class": "immune", "effect_direction": "positive"}]
    results = evaluate_engagement(receipts=receipts, frameworks=custom)
    assert len(results) == 1
    assert results[0].framework_name == "TestOnly"
    assert results[0].status == "support"


def test_invalid_status_raises_at_construction() -> None:
    with pytest.raises(ValueError, match="invalid status"):
        FrameworkEngagement("X", "bogus")  # type: ignore[arg-type]


def test_empty_framework_name_raises() -> None:
    with pytest.raises(ValueError, match="framework_name"):
        FrameworkEngagement("", "support")


def test_rationale_includes_framework_name_and_counts() -> None:
    receipts = [
        {"receipt_id": "M1", "authors": ["Mannick"],
         "outcome_class": "immune", "effect_direction": "positive"},
    ]
    e = _by_name(evaluate_engagement(receipts=receipts), "Mannick")
    assert "Mannick" in e.rationale
    assert "1 receipt" in e.rationale
    assert "support" in e.rationale


def test_authors_field_accepts_string_or_list() -> None:
    """authors can be a single string or a list — both should match."""
    string_form = [{"receipt_id": "X", "authors": "Mannick et al",
                    "outcome_class": "immune", "effect_direction": "positive"}]
    list_form = [{"receipt_id": "Y", "authors": ["Mannick", "Wong"],
                  "outcome_class": "immune", "effect_direction": "positive"}]
    e1 = _by_name(evaluate_engagement(receipts=string_form), "Mannick")
    e2 = _by_name(evaluate_engagement(receipts=list_form), "Mannick")
    assert e1.status == "support"
    assert e2.status == "support"
