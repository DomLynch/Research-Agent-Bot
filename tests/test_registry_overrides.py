"""Tests for agent/registry_overrides.py and the evidence_cards.py integration.

Two layers under test:
  1. lookup_override unit tests (NCT match, ISRCTN-in-URL match, miss paths)
  2. bundle() integration tests, including the planted-case-1 second-layer catch
     (TAME with a lying abstract — override pins role=registered_pending)

The registry-override layer is the moat. If a future change reorders bundle()
to run classify_role BEFORE lookup_override, or if a topic_pack mutation
slips an override out of the table, these tests fire immediately.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.evidence_cards import bundle
from agent.registry_overrides import _extract_isrctn, lookup_override
from agent.topic_pack import TopicPack, load_topic_pack
from agent.types import Source

METFORMIN_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"


@pytest.fixture(scope="module")
def metformin_pack() -> TopicPack:
    return load_topic_pack(METFORMIN_PATH)


def _src(
    *,
    ref: int = 1,
    title: str = "Some study",
    nct: str | None = None,
    url: str = "",
    source: str = "pubmed",
    year: int = 2024,
) -> Source:
    return Source(ref=ref, title=title, year=year, url=url, source=source, nct=nct)


# --- lookup_override unit tests -------------------------------------------


def test_lookup_override_returns_none_when_pack_is_none() -> None:
    src = _src(nct="NCT04264897")
    assert lookup_override(src, None) is None


def test_lookup_override_hits_on_known_nct(metformin_pack: TopicPack) -> None:
    """TAME (NCT04264897) is pinned to registered_pending."""
    src = _src(nct="NCT04264897")
    rec = lookup_override(src, metformin_pack)
    assert rec is not None
    assert rec.role == "registered_pending"
    assert rec.design == "rct"
    assert rec.tier == "A1"


def test_lookup_override_hits_on_canonical_results_nct(
    metformin_pack: TopicPack,
) -> None:
    """MASTERS, MET-PREVENT, MILES are pinned to published_results."""
    for nct in ("NCT02308228", "NCT01765946"):
        src = _src(nct=nct)
        rec = lookup_override(src, metformin_pack)
        assert rec is not None and rec.role == "published_results"


def test_lookup_override_hits_on_isrctn_in_url(metformin_pack: TopicPack) -> None:
    """MET-PREVENT uses ISRCTN29932357 — encoded in URL because Source has
    no dedicated ISRCTN field. Override lookup must extract from URL."""
    src = _src(
        nct=None,
        url="https://www.isrctn.com/ISRCTN29932357",
    )
    rec = lookup_override(src, metformin_pack)
    assert rec is not None
    assert rec.role == "published_results"
    assert rec.tier == "A1"


def test_lookup_override_misses_on_unknown_nct(metformin_pack: TopicPack) -> None:
    """Unknown NCTs return None — caller falls through to deterministic
    classifier. This is the contract that preserves backward compat
    when registry isn't comprehensive."""
    src = _src(nct="NCT99999999")
    assert lookup_override(src, metformin_pack) is None


def test_lookup_override_misses_when_source_has_no_registry_id(
    metformin_pack: TopicPack,
) -> None:
    """A PubMed-only source without NCT/ISRCTN can never hit the override."""
    src = _src(nct=None, url="")
    assert lookup_override(src, metformin_pack) is None


def test_lookup_override_strips_whitespace_via_topic_pack(
    metformin_pack: TopicPack,
) -> None:
    """The TopicPack.lookup_role_override strips whitespace; lookup_override
    inherits that behavior."""
    src = _src(nct="  NCT04264897  ")
    rec = lookup_override(src, metformin_pack)
    assert rec is not None
    assert rec.role == "registered_pending"


# --- _extract_isrctn unit tests -------------------------------------------


def test_extract_isrctn_canonical_url() -> None:
    assert _extract_isrctn("https://www.isrctn.com/ISRCTN29932357") == "ISRCTN29932357"


def test_extract_isrctn_case_insensitive() -> None:
    assert _extract_isrctn("https://example.com/isrctn29932357") == "ISRCTN29932357"


def test_extract_isrctn_no_digits_returns_none() -> None:
    """`ISRCTN` without trailing digits is malformed."""
    assert _extract_isrctn("https://example.com/isrctn") is None


def test_extract_isrctn_no_marker_returns_none() -> None:
    assert _extract_isrctn("https://clinicaltrials.gov/study/NCT04264897") is None


def test_extract_isrctn_stops_at_non_digit() -> None:
    assert _extract_isrctn("https://example.com/ISRCTN29932357?ref=1") == "ISRCTN29932357"


# --- bundle() integration: PLANTED CASE 1 SECOND-LAYER CATCH --------------


def test_planted_case_1_second_layer_catch(metformin_pack: TopicPack) -> None:
    """The moat in action.

    Construct a synthetic TAME submission with a LYING abstract that mimics
    results prose ('demonstrated cardiovascular benefit', 'p<0.001'). Without
    the topic pack, the deterministic classifier would believe the abstract
    and assign role=published_results — the exact bug case 1 represents.

    With the topic pack, registry_overrides.lookup_override hits the
    NCT04264897 entry and pins role=registered_pending IRREVOCABLY. The
    abstract is ignored for the categorical decision.
    """
    tame = _src(
        ref=1,
        title="TAME results",
        nct="NCT04264897",
        url="https://clinicaltrials.gov/study/NCT04264897",
    )
    lying_abstract = (
        "TAME demonstrated cardiovascular benefit in older adults treated "
        "with metformin (HR 0.78, 95% CI 0.65-0.92, p<0.001) over 6 years."
    )

    # Baseline (no pack): the lying abstract fools the classifier.
    items_no_pack = bundle(
        [tame], {1: lying_abstract},
        topic="metformin", domain="longevity older adults",
    )
    assert items_no_pack[0].role == "published_results", (
        "BASELINE: lying abstract should fool classifier without pack — "
        "this is the bug we're protecting against"
    )

    # With pack: registry override pins role=registered_pending.
    items_with_pack = bundle(
        [tame], {1: lying_abstract},
        topic="metformin", domain="longevity older adults",
        topic_pack=metformin_pack,
    )
    assert items_with_pack[0].role == "registered_pending", (
        f"PLANTED CASE 1 NOT CAUGHT at evidence_cards layer. "
        f"Got role={items_with_pack[0].role!r}; expected 'registered_pending'."
    )
    assert items_with_pack[0].design == "rct"
    assert items_with_pack[0].tier == "A1"


def test_masters_classification_unchanged_with_pack(
    metformin_pack: TopicPack,
) -> None:
    """When the override AGREES with what the abstract would imply, the
    categorical decision is identical. No double-counting, no surprise."""
    masters = _src(
        ref=2,
        title="MASTERS — metformin blunts hypertrophy",
        nct="NCT02308228",
        year=2019,
    )
    abstract = (
        "In a randomized, double-blind, placebo-controlled trial of older "
        "adults, metformin reduced lean mass gain compared to placebo "
        "(p=0.003)."
    )
    items = bundle(
        [masters], {2: abstract},
        topic="metformin", domain="longevity older adults",
        topic_pack=metformin_pack,
    )
    assert items[0].role == "published_results"
    assert items[0].design == "rct"
    assert items[0].tier == "A1"


def test_unknown_nct_falls_through_to_classifier(metformin_pack: TopicPack) -> None:
    """When the override misses, the deterministic classifier runs as before.
    Critical for backward compatibility — most of the metformin retrieval
    won't be canonical NCTs."""
    unknown = _src(
        ref=3,
        title="Some metformin observational cohort",
        nct="NCT99999999",
        year=2023,
    )
    abstract = (
        "In a randomized trial of older adults, metformin was associated "
        "with reduced mortality (HR 0.85, 95% CI 0.74-0.97, p=0.02)."
    )
    items = bundle(
        [unknown], {3: abstract},
        topic="metformin", domain="longevity older adults",
        topic_pack=metformin_pack,
    )
    # Classifier path: published_results, rct (RANDOMIZED_RE match),
    # A2 (no high-impact venue).
    assert items[0].role == "published_results"
    assert items[0].design == "rct"


def test_pack_optional_preserves_v11_behavior(metformin_pack: TopicPack) -> None:
    """When topic_pack is omitted, bundle() behaves exactly as V1.1 did.
    No surprise activation, no implicit default. Opt-in by parameter."""
    src = _src(nct="NCT04264897")  # TAME id present
    abstract = "Lying TAME abstract: TAME demonstrated benefit (p<0.001)."
    items = bundle([src], {1: abstract}, topic="metformin", domain="longevity")
    # Without pack, classifier reads abstract literally
    assert items[0].role == "published_results"
