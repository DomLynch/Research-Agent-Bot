"""Contract tests for agent.types.

Covers:
- Frozen dataclasses are actually immutable.
- Slots prevent typo-attribute bugs.
- assert_invariants enforces the role <-> fact-kind pairing rule.
"""
from __future__ import annotations

import dataclasses

import pytest

from agent.types import (
    Draft,
    EvidenceItem,
    Fact,
    InvariantError,
    Source,
    assert_invariants,
)


def _src(ref: int) -> Source:
    return Source(
        ref=ref,
        title=f"Source {ref}",
        year=2024,
        url=f"https://example.org/{ref}",
        source="pubmed",
        doi=f"10.1000/{ref}",
    )


_ROLE_TO_DESIGN = {
    "published_results": "rct",
    "published_protocol": "protocol",
    "registered_pending": "registry",
    "review": "review",
    "mechanistic": "mechanistic",
    "off_domain": "other",
}


def _item(ref: int, role) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref),
        abstract="Trial of intervention X.",
        design=_ROLE_TO_DESIGN[role],
        role=role,
        tier="A1",
        direct=True,
        strict=True,
    )


# --- Frozen + slots --------------------------------------------------------


def test_source_is_frozen():
    s = _src(1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.title = "mutated"  # type: ignore[misc]


def test_evidence_item_is_frozen():
    e = _item(1, "published_results")
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.tier = "C"  # type: ignore[misc]


def test_fact_is_frozen():
    f = Fact(ref=1, kind="result", claim="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.estimate = "1.0"  # type: ignore[misc]


def test_slots_present_no_dunder_dict():
    """Slots prevents typo-attribute bugs and saves memory."""
    s = _src(1)
    assert hasattr(Source, "__slots__")
    assert "title" in Source.__slots__
    assert not hasattr(s, "__dict__")


# --- Draft is intentionally mutable ----------------------------------------


def test_draft_is_mutable():
    d = Draft(
        topic="t",
        domain="d",
        criteria="c",
        title="T",
        abstract=[],
        sections={},
        bundle=[],
        facts=[],
    )
    d.sections["intro"] = ["sentence one."]
    d.bundle.append(_item(1, "published_results"))
    assert d.sections["intro"] == ["sentence one."]
    assert d.bundle[0].source.ref == 1


# --- Invariants: the spine -------------------------------------------------


def test_invariant_passes_when_pairings_match():
    bundle = [_item(1, "published_results"), _item(2, "published_protocol")]
    facts = [
        Fact(ref=1, kind="result", claim="6MWD improved", outcome="6MWD", estimate="+25m"),
        Fact(ref=2, kind="protocol", claim="primary endpoint is 6MWD"),
    ]
    assert_invariants(bundle, facts)  # does not raise


def test_invariant_blocks_result_fact_on_protocol_role():
    """The rapamycin bug class: protocol typed as published_results in prose."""
    bundle = [_item(1, "published_protocol")]
    facts = [Fact(ref=1, kind="result", claim="trial showed benefit", outcome="6MWD")]
    with pytest.raises(InvariantError, match="kind='result'"):
        assert_invariants(bundle, facts)


def test_invariant_blocks_result_fact_on_review_role():
    bundle = [_item(1, "review")]
    facts = [Fact(ref=1, kind="result", claim="meta showed benefit")]
    with pytest.raises(InvariantError, match="kind='result'"):
        assert_invariants(bundle, facts)


def test_invariant_blocks_protocol_fact_on_results_role():
    bundle = [_item(1, "published_results")]
    facts = [Fact(ref=1, kind="protocol", claim="primary endpoint")]
    with pytest.raises(InvariantError, match="kind='protocol'"):
        assert_invariants(bundle, facts)


def test_invariant_blocks_context_fact_on_wrong_role():
    bundle = [_item(1, "published_results")]
    facts = [Fact(ref=1, kind="context", claim="background mechanism")]
    with pytest.raises(InvariantError, match="kind='context'"):
        assert_invariants(bundle, facts)


def test_invariant_blocks_unknown_ref():
    bundle = [_item(1, "published_results")]
    facts = [Fact(ref=99, kind="result", claim="orphan")]
    with pytest.raises(InvariantError, match="unknown source ref=99"):
        assert_invariants(bundle, facts)


# --- Reverse direction: per-item completeness ------------------------------


def test_invariant_blocks_results_item_with_no_result_fact():
    """An EvidenceItem typed as published_results MUST carry a result fact;
    otherwise the prose silently drops the finding (data-loss bug class)."""
    bundle = [_item(1, "published_results")]
    facts: list[Fact] = []  # nothing extracted
    with pytest.raises(InvariantError, match="role='published_results' has no"):
        assert_invariants(bundle, facts)


def test_invariant_blocks_protocol_item_with_no_protocol_fact():
    bundle = [_item(1, "published_protocol")]
    facts: list[Fact] = []
    with pytest.raises(InvariantError, match="role='published_protocol' has no"):
        assert_invariants(bundle, facts)


def test_invariant_blocks_registered_pending_item_with_no_protocol_fact():
    bundle = [_item(1, "registered_pending")]
    facts: list[Fact] = []
    with pytest.raises(InvariantError, match="role='registered_pending' has no"):
        assert_invariants(bundle, facts)


def test_invariant_allows_review_item_without_facts():
    """Review/mechanistic items don't require facts — context extraction
    is best-effort, not load-bearing."""
    bundle = [_item(1, "review")]
    assert_invariants(bundle, facts=[])  # does not raise
