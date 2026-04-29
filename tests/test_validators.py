"""Tests for agent/validators.py — pure-function validation gates.

Each validator has a positive-result test (catches its target failure mode)
and at least one negative test (does NOT fire when input is honest).

Tied to planted-failure corpus: cases 1, 3, 4 each get a layered test here
that complements the topic_pack / evidence_cards layers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.schemas import Claim
from agent.topic_pack import TopicPack, load_topic_pack
from agent.types import EvidenceItem, Source
from agent.validators import (
    OBJECTIVE_PATTERN_RE,
    check_alias_drift,
    check_objective_as_claim,
    check_p_value_in_source,
    check_role_claim_match,
    check_verb_ban,
)

METFORMIN_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"
PLANTED_DIR = Path(__file__).parent / "planted_failures" / "metformin"


@pytest.fixture(scope="module")
def metformin_pack() -> TopicPack:
    return load_topic_pack(METFORMIN_PATH)


def _src(*, ref: int = 1, source: str = "pubmed", nct: str | None = None) -> Source:
    return Source(ref=ref, title="Some study", year=2024, url="", source=source, nct=nct)


def _ev(role, *, ref: int = 1, design: str = "rct", direct: bool = True) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref=ref),
        abstract="", design=design, role=role, tier="A1",
        direct=direct, strict=True,
    )


# --- check_verb_ban — planted case 1's third defense layer ----------------


def test_verb_ban_catches_demonstrated_for_protocol(
    metformin_pack: TopicPack,
) -> None:
    """Case 1 prose layer: 'TAME demonstrated CV benefit' citing registered_pending."""
    ev = _ev("registered_pending")
    fail = check_verb_ban(
        "TAME demonstrated cardiovascular benefit in older adults.",
        ev, metformin_pack,
    )
    assert fail is not None
    assert fail.code == "VERB_BAN_PROTOCOL"
    assert "demonstrated" in fail.message
    assert fail.severity == "block"


def test_verb_ban_catches_each_forbidden_protocol_verb(
    metformin_pack: TopicPack,
) -> None:
    """All 7 forbidden verbs must trip the gate."""
    ev = _ev("registered_pending")
    for verb in ("found", "showed", "improved", "reduced", "demonstrated",
                 "established", "proved"):
        text = f"The trial {verb} significant benefit."
        fail = check_verb_ban(text, ev, metformin_pack)
        assert fail is not None and fail.code == "VERB_BAN_PROTOCOL", (
            f"verb {verb!r} should be banned for protocol-role"
        )


def test_verb_ban_is_word_boundary_aware(metformin_pack: TopicPack) -> None:
    """'demonstrative' must NOT trip the ban on 'demonstrated'."""
    ev = _ev("registered_pending")
    fail = check_verb_ban(
        "The protocol provides demonstrative analysis of the design.",
        ev, metformin_pack,
    )
    assert fail is None  # 'demonstrative' is not a banned verb


def test_verb_ban_allows_demonstrated_for_published_results(
    metformin_pack: TopicPack,
) -> None:
    """The same verb on a results-role evidence is fine."""
    ev = _ev("published_results")
    fail = check_verb_ban(
        "MASTERS demonstrated muscle hypertrophy blunting (p=0.003).",
        ev, metformin_pack,
    )
    assert fail is None


def test_verb_ban_inverse_catches_pending_for_results(
    metformin_pack: TopicPack,
) -> None:
    """The inverse: a published trial described as 'pending' or 'planned'."""
    ev = _ev("published_results")
    fail = check_verb_ban(
        "MASTERS data are pending; results awaiting publication.",
        ev, metformin_pack,
    )
    assert fail is not None
    assert fail.code == "VERB_BAN_RESULTS_PROTOCOL_KEYWORD"


def test_verb_ban_skips_review_role(metformin_pack: TopicPack) -> None:
    """Reviews are neither protocol nor results — verb-ban doesn't apply."""
    ev = _ev("review", design="review")
    fail = check_verb_ban(
        "This review demonstrated the field's uncertainty about metformin.",
        ev, metformin_pack,
    )
    assert fail is None


# --- check_alias_drift — planted case 4's local layer --------------------


def test_alias_drift_catches_glufomin_pattern(metformin_pack: TopicPack) -> None:
    """Planted case 4 fixture: 'Glufomin, a metformin equivalent...'"""
    fail = check_alias_drift(
        "Glufomin, a metformin equivalent, reduced incident frailty by 20%.",
        metformin_pack,
    )
    assert fail is not None
    assert fail.code == "ALIAS_DRIFT"
    assert "Glufomin" in fail.message


def test_alias_drift_catches_alternative_phrasing(metformin_pack: TopicPack) -> None:
    """Variants of the apposition pattern should also fire."""
    cases = [
        "AcmeMet, an analog of metformin, reduced mortality.",
        "Glucophagex (a metformin alternative) attenuates frailty.",
        "MetX, an analogue of metformin, was studied in a trial.",
    ]
    for claim_text in cases:
        fail = check_alias_drift(claim_text, metformin_pack)
        assert fail is not None and fail.code == "ALIAS_DRIFT", (
            f"failed to catch drift in: {claim_text!r}"
        )


def test_alias_drift_allows_real_aliases(metformin_pack: TopicPack) -> None:
    """A canonical alias like 'Glucophage' must NOT trip the gate when
    presented as a metformin equivalent."""
    fail = check_alias_drift(
        "Glucophage, a metformin formulation, has been used since the 1950s.",
        metformin_pack,
    )
    assert fail is None


def test_alias_drift_skips_when_no_apposition_pattern(
    metformin_pack: TopicPack,
) -> None:
    """A claim that mentions an unrecognized capitalized token but does NOT
    present it as a topic-alias should pass — false-positive avoidance."""
    fail = check_alias_drift(
        "Stanford researchers studied metformin in older adults.",
        metformin_pack,
    )
    assert fail is None  # 'Stanford' is not presented as a metformin alias


# --- check_p_value_in_source — planted case 3's local layer --------------


def test_p_value_in_source_catches_inflated_pvalue() -> None:
    """Case 3 fixture: claim says 'p<0.001' but source says 'p=0.08'."""
    claim = "Konopka 2019 reported significant attenuation of VO2max (p<0.001)."
    source = (
        "Metformin attenuated VO2max by 50% (p = 0.08). "
        "Insulin sensitivity inhibited (p = 0.02)."
    )
    fail = check_p_value_in_source(claim, source)
    assert fail is not None
    assert fail.code == "P_VALUE_NOT_IN_SOURCE"
    assert "p<0.001" in fail.message
    assert "0.08" in fail.message  # source p-values rendered


def test_p_value_in_source_allows_honest_citation() -> None:
    """When the claim's p-value matches the source, no failure."""
    claim = "Metformin attenuated VO2max gains (p=0.08)."
    source = "Metformin attenuated VO2max by 50% (p = 0.08)."
    fail = check_p_value_in_source(claim, source)
    assert fail is None


def test_p_value_in_source_allows_multiple_cited_pvalues() -> None:
    """Citing multiple p-values, all present in source."""
    claim = "Metformin attenuated VO2max (p=0.08) and insulin sensitivity (p=0.02)."
    source = "VO2max p = 0.08; insulin sensitivity p = 0.02; HbA1c p = 0.74."
    fail = check_p_value_in_source(claim, source)
    assert fail is None


def test_p_value_in_source_rejects_partial_drift() -> None:
    """Two p-values cited, one matches the source and one doesn't — still rejects."""
    claim = "Metformin attenuated VO2max (p=0.08) and lifespan (p=0.001)."
    source = "VO2max p = 0.08; insulin sensitivity p = 0.02."
    fail = check_p_value_in_source(claim, source)
    assert fail is not None
    assert "p=0.001" in fail.message  # the missing one is named


def test_p_value_in_source_no_pvalues_passes() -> None:
    """Claims with no p-values have nothing to verify."""
    claim = "Metformin attenuated VO2max gains in older adults."
    source = "Metformin attenuated VO2max (p = 0.08)."
    fail = check_p_value_in_source(claim, source)
    assert fail is None


def test_p_value_in_source_normalizes_whitespace_and_zero() -> None:
    """`p<0.001`, `p < 0.001`, and `p<.001` all canonicalize the same way."""
    claim = "Significant reduction (p<.001)."
    source = "Significant reduction (p < 0.001)."
    fail = check_p_value_in_source(claim, source)
    assert fail is None  # whitespace + leading zero normalized


# --- check_role_claim_match — directness contract -----------------------


def test_role_claim_match_rejects_direct_with_no_direct_evidence() -> None:
    """A direct claim must have at least one direct evidence item."""
    claim = Claim(
        claim_id="C01", text="metformin blunts hypertrophy",
        claim_type="efficacy", supporting_refs=(1, 2), opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )
    items_indirect_only = {
        1: _ev("mechanistic", ref=1, direct=False),
        2: _ev("review", ref=2, direct=False, design="review"),
    }
    fail = check_role_claim_match(claim, items_indirect_only)
    assert fail is not None
    assert fail.code == "CLAIM_DIRECTNESS_MISMATCH"


def test_role_claim_match_passes_when_at_least_one_direct() -> None:
    claim = Claim(
        claim_id="C01", text="metformin blunts hypertrophy",
        claim_type="efficacy", supporting_refs=(1, 2), opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )
    items_with_one_direct = {
        1: _ev("mechanistic", ref=1, direct=False),
        2: _ev("published_results", ref=2, direct=True),
    }
    fail = check_role_claim_match(claim, items_with_one_direct)
    assert fail is None


def test_role_claim_match_skips_indirect_claims() -> None:
    """Indirect claims have no analogous constraint — pass through."""
    claim = Claim(
        claim_id="C05", text="observational signal collapses",
        claim_type="indirect", supporting_refs=(1,), opposing_refs=(),
        directness="indirect", evidence_tier="B", confidence="moderate",
        attack_surface=(),
    )
    items = {1: _ev("review", ref=1, direct=False, design="review")}
    fail = check_role_claim_match(claim, items)
    assert fail is None


def test_role_claim_match_rejects_no_supporting_refs() -> None:
    claim = Claim(
        claim_id="C99", text="anything",
        claim_type="efficacy", supporting_refs=(), opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )
    fail = check_role_claim_match(claim, {})
    assert fail is not None
    assert fail.code == "CLAIM_NO_SUPPORT"


def test_role_claim_match_rejects_unresolved_refs() -> None:
    """Claim references refs not present in the evidence map."""
    claim = Claim(
        claim_id="C01", text="x",
        claim_type="efficacy", supporting_refs=(1, 2, 3), opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=(),
    )
    fail = check_role_claim_match(claim, {})  # no evidence at all
    assert fail is not None
    assert fail.code == "CLAIM_REFS_NOT_FOUND"


# --- Cross-validator integration — planted case 1 fixture, all 3 layers --


def test_planted_case_1_caught_at_validators_layer(
    metformin_pack: TopicPack,
) -> None:
    """The third defense layer for case 1.

    Layer 1 (topic_pack): TAME (NCT04264897) is in known_role_overrides.
    Layer 2 (evidence_cards): bundle() consults override → role=registered_pending.
    Layer 3 (validators): even if a claim made it past layers 1 and 2,
                          check_verb_ban catches 'demonstrated' for protocol role.

    This test simulates layer 3 in isolation — given an EvidenceItem that
    correctly has role=registered_pending (because layers 1 + 2 worked),
    a prose claim using 'demonstrated' must still be rejected.
    """
    case1 = json.loads((PLANTED_DIR / "case_1_protocol_as_results.json").read_text())
    claim_text = case1["synthetic_claim_text"]
    src = Source(
        ref=1,
        title=case1["synthetic_source"]["title"],
        year=case1["synthetic_source"]["year"],
        url=case1["synthetic_source"]["url"],
        source=case1["synthetic_source"]["source"],
        nct=case1["synthetic_source"]["nct"],
    )
    # Simulate the post-evidence_cards state: TAME has role=registered_pending
    # (which is what layers 1+2 produce given the registry override).
    ev = EvidenceItem(
        source=src,
        abstract=case1["synthetic_source"]["abstract"],
        design="rct", role="registered_pending", tier="A1",
        direct=True, strict=True,
    )
    fail = check_verb_ban(claim_text, ev, metformin_pack)
    assert fail is not None
    assert fail.code == "VERB_BAN_PROTOCOL"
    assert case1["synthetic_claim_verb"] in fail.message


# --- Day 10.11 — check_objective_as_claim --------------------------------
#
# Failure mode: fact extractor pulls "To determine whether metformin..."
# spans from published_results abstracts and presents them as findings.
# SPAR rejects them as protocol-as-claim. The validator catches this
# upstream so the receipt pipeline doesn't waste SPAR cost on
# unverifiable purpose statements.


def test_objective_catches_to_determine_whether_for_results() -> None:
    """The exact pattern from cluster_07/cluster_09 in Day 10.10 run."""
    ev = _ev("published_results")
    fail = check_objective_as_claim(
        "To determine whether metformin can improve the immune response "
        "to influenza vaccine in older adults.",
        ev,
    )
    assert fail is not None
    assert fail.code == "OBJECTIVE_AS_CLAIM_RESULTS"
    assert "OBJECTIVE / DESIGN / REGISTRATION" in fail.message


def test_objective_catches_objective_of_this_research_is_to() -> None:
    """The exact pattern from cluster_11."""
    ev = _ev("published_results")
    fail = check_objective_as_claim(
        "The objective of this research is to assess the efficacy of oral "
        "metformin in mitigating the aging process.",
        ev,
    )
    assert fail is not None
    assert fail.code == "OBJECTIVE_AS_CLAIM_RESULTS"


def test_objective_catches_this_study_aims_to() -> None:
    """The exact pattern from cluster_12."""
    ev = _ev("published_results")
    fail = check_objective_as_claim(
        "This study aims to assess the safety and efficacy of study drugs "
        "and supplements on clinical signs of aging.",
        ev,
    )
    assert fail is not None
    assert fail.code == "OBJECTIVE_AS_CLAIM_RESULTS"


def test_objective_catches_this_research_is_being_done_to() -> None:
    """The exact pattern from cluster_09."""
    ev = _ev("published_results")
    fail = check_objective_as_claim(
        "This research is being done to determine if Metformin, an "
        "FDA-approved diabetes medication, is effective at enhancing "
        "immune responses to flu vaccine in older men and women.",
        ev,
    )
    assert fail is not None
    assert fail.code == "OBJECTIVE_AS_CLAIM_RESULTS"


def test_objective_catches_we_aimed_to() -> None:
    ev = _ev("published_results")
    fail = check_objective_as_claim(
        "We aimed to evaluate whether metformin reduces frailty in older "
        "adults with diabetes.",
        ev,
    )
    assert fail is not None
    assert fail.code == "OBJECTIVE_AS_CLAIM_RESULTS"


def test_objective_catches_trial_registration() -> None:
    """Trial registration spans are classic boilerplate, not findings."""
    ev = _ev("published_results")
    fail = check_objective_as_claim(
        "Trial registration: ClinicalTrials.gov NCT02308228.", ev,
    )
    assert fail is not None
    assert fail.code == "OBJECTIVE_AS_CLAIM_RESULTS"


def test_objective_allows_real_finding_clauses() -> None:
    """Past-tense reporting clauses are the SAFE pattern for results.
    The validator must not catch legitimate findings."""
    ev = _ev("published_results")
    for finding in (
        "Metformin reduced HbA1c by 0.5% (p=0.003) over 12 months.",
        "The treatment group showed greater muscle hypertrophy than placebo.",
        "After 12 weeks, participants in arm A had higher walking speed.",
        "Increases in thigh muscle area were greater in placebo "
        "(p=0.005) than in metformin.",
        "48 adverse events occurred in 16 of 19 metformin participants.",
    ):
        assert check_objective_as_claim(finding, ev) is None, (
            f"validator falsely flagged real finding: {finding}"
        )


def test_objective_skips_protocol_role() -> None:
    """The validator only fires on `published_results`. Protocol/registered
    items are SUPPOSED to quote objective spans."""
    ev = _ev("published_protocol")
    fail = check_objective_as_claim(
        "To determine whether metformin can improve immune response.",
        ev,
    )
    assert fail is None


def test_objective_skips_review_role() -> None:
    """Reviews and mechanistic abstracts often legitimately frame their
    work with objective sentences ('We investigated...'). The validator
    is reserved for the published_results role where the failure mode
    is empirically dominant."""
    ev = _ev("review")
    fail = check_objective_as_claim(
        "We sought to evaluate metformin trials across populations.", ev,
    )
    assert fail is None


def test_objective_pattern_anchors_to_clause_starts() -> None:
    """The pattern triggers at sentence/clause starts, not arbitrarily.
    'The trial showed metformin's objective improved...' is a finding,
    not an objective statement, despite containing the word 'objective'."""
    # 'objective' appears mid-sentence as a noun, not as a clause-leading
    # verb. The regex requires "objective ... of this study is to" —
    # reduce false positives by anchoring.
    ev = _ev("published_results")
    fail = check_objective_as_claim(
        "The trial reported that metformin's objective improvement was "
        "0.5% reduction in HbA1c.",
        ev,
    )
    # Word 'objective' alone is not enough — the pattern needs the full
    # objective-of-this-study form.
    assert fail is None


def test_objective_pattern_re_matches_all_targeted_forms() -> None:
    """Smoke test on the regex itself for each documented form."""
    targets = [
        "To determine whether X works.",
        "To assess the efficacy of Y.",
        "The objective of this study is to evaluate Z.",
        "The aim of this research is to test W.",
        "This study aims to assess A.",
        "This trial seeks to determine B.",
        "We aimed to investigate C.",
        "We sought to characterize D.",
        "Trial registration: NCT12345678.",
    ]
    for t in targets:
        norm = " ".join(t.split())
        assert OBJECTIVE_PATTERN_RE.search(norm) is not None, (
            f"regex missed: {t}"
        )
