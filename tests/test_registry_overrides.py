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
from agent.registry_overrides import _extract_isrctn, lookup_override, resolve_override
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


# --- Day 3.0: NCT-in-abstract scan (live-smoke regression) -----------------


def test_lookup_override_hits_on_nct_in_abstract(metformin_pack: TopicPack) -> None:
    """The live-smoke regression. Live OpenAlex/PubMed return MASTERS
    (NCT02308228) with the NCT only in the abstract — source.nct is None
    because the dedup-merge with CT.gov didn't fire. Without the
    abstract scan, the override missed and MASTERS classified as
    mechanistic/C in the live run (2026-04-27 baseline).

    With the Day 3.0 abstract scan, the override fires and pins MASTERS
    to published_results / rct / A1.
    """
    src = _src(nct=None)  # Source has no NCT (the live OpenAlex shape)
    abstract = (
        "Progressive resistance exercise training (PRT) is the most "
        "effective intervention for combating aging skeletal muscle "
        "atrophy. ClinicalTrials.gov Identifier: NCT02308228."
    )
    rec = lookup_override(src, metformin_pack, abstract=abstract)
    assert rec is not None, "abstract NCT scan should pin MASTERS"
    assert rec.role == "published_results"
    assert rec.tier == "A1"


def test_lookup_override_accepts_id_before_registration_and_deduplicates(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct=None)
    abstract = (
        "NCT04264897 was registered as the trial identifier. "
        "The trial was registered as NCT04264897 before enrollment."
    )

    rec = lookup_override(src, metformin_pack, abstract=abstract)

    assert rec is not None
    assert rec.role == "registered_pending"


@pytest.mark.parametrize(
    "other_id",
    ["NCT99999999", "NCT02308228"],
)
def test_lookup_override_rejects_ambiguous_declared_registry_ids(
    metformin_pack: TopicPack, other_id: str,
) -> None:
    src = _src(nct=None)
    abstract = f"The trial was registered as NCT04264897 and {other_id}."

    assert lookup_override(src, metformin_pack, abstract=abstract) is None


def test_lookup_override_hits_on_first_known_nct_in_abstract(
    metformin_pack: TopicPack,
) -> None:
    """Incidental registry mentions do not pin a source role."""
    src = _src(nct=None)
    # NCT99999999 is unknown; NCT02308228 is MASTERS; NCT04264897 is TAME.
    abstract = "compared NCT99999999 baseline against NCT02308228 results."
    rec = lookup_override(src, metformin_pack, abstract=abstract)
    assert rec is None


def test_lookup_override_hits_on_isrctn_in_abstract(
    metformin_pack: TopicPack,
) -> None:
    """ISRCTN in abstract (the MET-PREVENT pattern) also fires the override."""
    src = _src(nct=None)
    abstract = (
        "MET-PREVENT was registered as ISRCTN29932357 and enrolled "
        "older adults with sarcopenia."
    )
    rec = lookup_override(src, metformin_pack, abstract=abstract)
    assert rec is not None
    assert rec.role == "published_results"


def test_lookup_override_abstract_scan_is_word_bounded(
    metformin_pack: TopicPack,
) -> None:
    """A 9-digit number should NOT match the 8-digit NCT pattern. Catches
    a class of false positives where digits run together with surrounding
    text."""
    src = _src(nct=None)
    abstract = "the trial enrolled NCT023082289 patients (typo or different id)"
    rec = lookup_override(src, metformin_pack, abstract=abstract)
    # NCT023082289 is 9 digits — does NOT match \bNCT\d{8}\b.
    assert rec is None


def test_lookup_override_source_nct_takes_precedence_over_abstract(
    metformin_pack: TopicPack,
) -> None:
    """When source.nct hits, abstract scan is short-circuited — the
    contract is documented in the docstring."""
    src = _src(nct="NCT02308228")  # MASTERS — known
    abstract = "discusses NCT04264897 (TAME) for context"  # Different known NCT
    rec = lookup_override(src, metformin_pack, abstract=abstract)
    # source.nct=NCT02308228 should win → published_results (MASTERS)
    # NOT registered_pending (TAME) which is what the abstract NCT would give.
    assert rec is not None
    assert rec.role == "published_results"


def test_lookup_override_rejects_conflicting_structured_and_declared_ids(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct="NCT02308228")
    abstract = "The trial was registered as NCT04264897."

    assert lookup_override(src, metformin_pack, abstract=abstract) is None


def test_lookup_override_detects_clinicaltrials_number_conflict(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct="NCT02308228")
    abstract = "Funded study; ClinicalTrials.gov number NCT04264897."

    record, conflict = resolve_override(src, metformin_pack, abstract=abstract)

    assert record is None
    assert conflict is True


def test_lookup_override_detects_colon_registration_conflict(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct="NCT02308228")
    abstract = "Trial registration: ClinicalTrials.gov NCT04264897."

    record, conflict = resolve_override(src, metformin_pack, abstract=abstract)

    assert record is None
    assert conflict is True


def test_lookup_override_detects_clinicaltrials_colon_conflict(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct="NCT02308228")
    abstract = "Trial registration: ClinicalTrials.gov: NCT04264897."

    record, conflict = resolve_override(src, metformin_pack, abstract=abstract)

    assert record is None
    assert conflict is True


def test_lookup_override_rejects_unknown_structured_id_beside_known_declaration(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct="NCT99999999")
    abstract = "The trial was registered as NCT02308228."

    assert lookup_override(src, metformin_pack, abstract=abstract) is None


def test_lookup_override_accepts_matching_structured_and_declared_ids(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct="NCT02308228")
    abstract = "ClinicalTrials.gov Identifier: NCT02308228."

    rec = lookup_override(src, metformin_pack, abstract=abstract)
    assert rec is not None and rec.role == "published_results"


def test_lookup_override_empty_abstract_arg_does_no_extra_work(
    metformin_pack: TopicPack,
) -> None:
    """Backward compat: callers that don't pass abstract get the same
    behavior as before Day 3.0."""
    src = _src(nct="NCT02308228")
    rec_explicit = lookup_override(src, metformin_pack, abstract="")
    rec_default = lookup_override(src, metformin_pack)
    assert rec_explicit == rec_default
    assert rec_explicit is not None and rec_explicit.role == "published_results"


def test_lookup_override_abstract_scan_returns_none_for_no_known_ids(
    metformin_pack: TopicPack,
) -> None:
    """Abstract has NCTs but none are in the topic_pack — falls through
    to None (caller will use deterministic classifier on the abstract)."""
    src = _src(nct=None)
    abstract = "compared NCT99999999 to NCT00000001 in a meta-analysis."
    rec = lookup_override(src, metformin_pack, abstract=abstract)
    assert rec is None


def test_bundle_rejects_conflicting_known_registry_identities(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct="NCT02308228", title="Conflicting trial identity")
    abstract = "Trial registered as NCT04264897 in ClinicalTrials.gov registration."

    assert lookup_override(src, metformin_pack, abstract=abstract) is None
    assert bundle(
        [src], {src.ref: abstract}, topic="metformin", domain="longevity",
        topic_pack=metformin_pack,
    ) == []


def test_bundle_rejects_distinct_known_ids_with_equal_overrides(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct="NCT02308228", title="Conflicting published-trial identities")
    abstract = "Trial registered as NCT01765946 in ClinicalTrials.gov registration."

    assert lookup_override(src, metformin_pack, abstract=abstract) is None
    assert bundle(
        [src], {src.ref: abstract}, topic="metformin", domain="longevity",
        topic_pack=metformin_pack,
    ) == []


# --- Day 3.0 follow-up: case-insensitivity of registry IDs (P2 fix) -------


def test_lookup_override_lowercase_source_nct_hits(metformin_pack: TopicPack) -> None:
    """Adapters might one day emit lowercase `nct…`. The override must
    pin regardless. Both the regex and the dict lookup canonicalize."""
    src = _src(nct="nct02308228")
    rec = lookup_override(src, metformin_pack)
    assert rec is not None and rec.role == "published_results"


def test_lookup_override_mixed_case_source_nct_hits(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct="NcT02308228")
    rec = lookup_override(src, metformin_pack)
    assert rec is not None


def test_lookup_override_lowercase_nct_in_abstract_hits(
    metformin_pack: TopicPack,
) -> None:
    """The Day 3.0 abstract scan now uses re.IGNORECASE."""
    src = _src(nct=None)
    abstract = "Trial registered as nct02308228 in clinicaltrials.gov."
    rec = lookup_override(src, metformin_pack, abstract=abstract)
    assert rec is not None and rec.role == "published_results"


def test_lookup_override_lowercase_isrctn_in_abstract_hits(
    metformin_pack: TopicPack,
) -> None:
    src = _src(nct=None)
    abstract = "Trial registered as isrctn29932357 in the registry."
    rec = lookup_override(src, metformin_pack, abstract=abstract)
    assert rec is not None and rec.role == "published_results"


def test_lookup_role_override_input_normalization() -> None:
    """Direct test of the canonical-helper normalization. Hits the dict
    lookup itself rather than going through registry_overrides."""
    pack = load_topic_pack(METFORMIN_PATH)
    for variant in (
        "NCT02308228", "nct02308228", "NCT02308228 ", " NCT02308228",
        "  nct02308228  ", "NcT02308228",
    ):
        rec = pack.lookup_role_override(variant)
        assert rec is not None, f"variant {variant!r} should hit"
        assert rec.role == "published_results"


def test_topic_pack_load_canonicalizes_keys_to_uppercase() -> None:
    """Keys in known_role_overrides are uppercased at load time so the
    canonical form is invariant under TOML formatting choices. Storing
    'nct04264897' in TOML still produces 'NCT04264897' as the key."""
    pack = load_topic_pack(METFORMIN_PATH)
    keys = set(pack.known_role_overrides.keys())
    # Every key must be uppercase form
    for k in keys:
        assert k == k.upper(), f"key {k!r} not uppercase after load"


def test_topic_pack_load_rejects_case_only_duplicate_overrides(
    tmp_path: "Path",
) -> None:
    """If a TOML lists both 'NCT04264897' and 'nct04264897', after
    canonicalization they collide. Must raise instead of silently picking
    one — that's a content bug worth surfacing."""
    from pathlib import Path as _P
    p = _P(tmp_path) / "dup.toml"
    p.write_text(
        'topic = "x"\n'
        'class_ = "x"\n'
        'aliases = ["x"]\n'
        'expected_evidence_slots = []\n'
        'special_rules = []\n'
        'forbidden_verbs_for_protocol_role = []\n'
        'forbidden_verbs_for_results_role_with_protocol_keywords = []\n'
        'canonical_trials = []\n'
        '[known_role_overrides.NCT04264897]\n'
        'role = "registered_pending"\ndesign = "rct"\ntier = "A1"\n'
        '[known_role_overrides.nct04264897]\n'
        'role = "published_results"\ndesign = "rct"\ntier = "A1"\n'
    )
    from agent.topic_pack import TopicPackError
    with pytest.raises(TopicPackError, match="duplicate override id"):
        load_topic_pack(p)


def test_lookup_override_master_pinned_via_nct_in_abstract_e2e(
    metformin_pack: TopicPack,
) -> None:
    """E2E shape: when bundle() runs against a Source whose abstract
    contains NCT02308228 but source.nct is None, the resulting
    EvidenceItem must carry MASTERS' override roles. This is the test
    that would have failed before Day 3.0."""
    from agent.evidence_cards import bundle as run_bundle

    src = Source(
        ref=1,
        title="Metformin blunts muscle hypertrophy in response to PRT",
        year=2019,
        url="https://onlinelibrary.wiley.com/doi/10.1111/acel.13039",
        source="openalex",
        nct=None,  # the bug shape — live data has nct=None for this paper
    )
    abstract = (
        "In a randomized, double-blind trial, 1700 mg/day metformin "
        "was compared to placebo. Placebo gained more thigh muscle "
        "mass (p<.001). ClinicalTrials.gov Identifier: NCT02308228."
    )
    items = run_bundle(
        [src], {1: abstract},
        topic="metformin", domain="longevity older adults",
        topic_pack=metformin_pack,
    )
    assert len(items) == 1
    masters = items[0]
    assert masters.role == "published_results", (
        f"E2E regression: MASTERS via NCT-in-abstract should be "
        f"published_results, got {masters.role!r}"
    )
    assert masters.design == "rct"
    assert masters.tier == "A1"


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
