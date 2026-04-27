"""Tests for agent/schemas.py — the 6 frozen-dataclasses + invariants + tie-break.

Discriminating tests focused on the seams (v4 Rule 57):
- Frozen-ness (mutation must raise)
- ClaimGraph structural invariants (thesis_claim_id present, edges valid)
- SPAR invariants (3-agent cast, dissent rule, non-empty resolution)
- compute_spar_verdict — all 4 outcomes from DESIGN-001 §8 table
"""
from __future__ import annotations

import dataclasses

import pytest

from agent.schemas import (
    Claim,
    ClaimEdge,
    ClaimGraph,
    ClaimGraphInvariantError,
    JudgeReview,
    SPARInvariantError,
    SPARReview,
    assert_claim_graph_invariants,
    assert_spar_invariants,
    compute_spar_verdict,
)


def _claim(cid: str = "C01") -> Claim:
    return Claim(
        claim_id=cid,
        text="metformin blunts hypertrophy",
        claim_type="efficacy",
        supporting_refs=(1,),
        opposing_refs=(),
        directness="direct",
        evidence_tier="A1",
        confidence="high",
        attack_surface=("single trial",),
    )


def _judge(role, verdict="accept", score=8) -> JudgeReview:
    return JudgeReview(
        judge_role=role, model="m", verdict=verdict, score=score,
        rationale="ok", flagged_claims=(),
    )


# --- Frozen guarantees ----------------------------------------------------


def test_claim_is_frozen() -> None:
    c = _claim()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.text = "mutated"  # type: ignore[misc]


def test_claim_default_falsifiability_is_empty_tuple() -> None:
    c = _claim()
    assert c.falsifiability == ()


def test_claim_falsifiability_supports_thesis() -> None:
    c = Claim(
        claim_id="C06_THESIS", text="thesis", claim_type="efficacy",
        supporting_refs=(1, 2, 3), opposing_refs=(),
        directness="direct", evidence_tier="A1", confidence="high",
        attack_surface=("inferential",),
        falsifiability=("RCT showing additive effect would falsify",),
    )
    assert c.falsifiability == ("RCT showing additive effect would falsify",)


def test_spar_review_is_frozen() -> None:
    r = SPARReview(
        submission_id="m1",
        reviews=(_judge("evidence_auditor"), _judge("domain_skeptic"), _judge("final_judge")),
        verdict="accept_clean", dissent=None, final_judge_resolution="clean",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.verdict = "reject_critical"  # type: ignore[misc]


# --- ClaimGraph invariants ------------------------------------------------


def test_claim_graph_thesis_must_exist() -> None:
    g = ClaimGraph(claims=(_claim("C01"),), edges=(), thesis_claim_id="C99")
    with pytest.raises(ClaimGraphInvariantError, match="thesis_claim_id"):
        assert_claim_graph_invariants(g)


def test_claim_graph_rejects_duplicate_ids() -> None:
    g = ClaimGraph(claims=(_claim("C01"), _claim("C01")), edges=(), thesis_claim_id="C01")
    with pytest.raises(ClaimGraphInvariantError, match="duplicate"):
        assert_claim_graph_invariants(g)


def test_claim_graph_edges_must_reference_real_claims() -> None:
    g = ClaimGraph(
        claims=(_claim("C01"),),
        edges=(ClaimEdge(from_claim="C01", to_claim="C99", kind="supports"),),
        thesis_claim_id="C01",
    )
    with pytest.raises(ClaimGraphInvariantError, match="C99"):
        assert_claim_graph_invariants(g)


def test_claim_graph_valid_passes() -> None:
    g = ClaimGraph(
        claims=(_claim("C01"), _claim("C02")),
        edges=(ClaimEdge(from_claim="C01", to_claim="C02", kind="supports"),),
        thesis_claim_id="C02",
    )
    assert_claim_graph_invariants(g)  # no raise


# --- SPAR invariants ------------------------------------------------------


def test_spar_must_have_three_reviews() -> None:
    r = SPARReview(
        submission_id="m1",
        reviews=(_judge("evidence_auditor"), _judge("domain_skeptic")),  # only 2
        verdict="accept_clean", dissent=None, final_judge_resolution="clean",
    )
    with pytest.raises(SPARInvariantError, match="exactly 3"):
        assert_spar_invariants(r)


def test_spar_must_cover_all_three_roles() -> None:
    r = SPARReview(
        submission_id="m1",
        # 3 reviews but two have the same role
        reviews=(_judge("evidence_auditor"), _judge("evidence_auditor"), _judge("final_judge")),
        verdict="accept_clean", dissent=None, final_judge_resolution="clean",
    )
    with pytest.raises(SPARInvariantError, match="roles"):
        assert_spar_invariants(r)


def test_spar_split_verdict_requires_dissent() -> None:
    """The auditability discipline: 2-1 verdict MUST publish dissent."""
    reviews = (_judge("evidence_auditor", "accept"), _judge("domain_skeptic", "reject"),
               _judge("final_judge", "accept"))
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="accept_caveated", dissent=None,  # dissent missing — FAIL
        final_judge_resolution="resolved",
    )
    with pytest.raises(SPARInvariantError, match="split"):
        assert_spar_invariants(r)


def test_spar_unanimous_must_have_no_dissent() -> None:
    reviews = (_judge("evidence_auditor"), _judge("domain_skeptic"), _judge("final_judge"))
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="accept_clean", dissent=reviews[1],  # dissent present — FAIL
        final_judge_resolution="clean",
    )
    with pytest.raises(SPARInvariantError, match="unanimous"):
        assert_spar_invariants(r)


def test_spar_resolution_must_be_non_empty() -> None:
    reviews = (_judge("evidence_auditor"), _judge("domain_skeptic"), _judge("final_judge"))
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="accept_clean", dissent=None,
        final_judge_resolution="   ",  # whitespace only — FAIL
    )
    with pytest.raises(SPARInvariantError, match="resolution"):
        assert_spar_invariants(r)


def test_spar_valid_unanimous_accept_passes() -> None:
    reviews = (_judge("evidence_auditor"), _judge("domain_skeptic"), _judge("final_judge"))
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="accept_clean", dissent=None,
        final_judge_resolution="all three accepted",
    )
    assert_spar_invariants(r)


def test_spar_valid_split_accept_passes() -> None:
    reviews = (_judge("evidence_auditor", "accept"), _judge("domain_skeptic", "reject"),
               _judge("final_judge", "accept"))
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="accept_caveated", dissent=reviews[1],
        final_judge_resolution="2-1 accept; skeptic dissented on power",
    )
    assert_spar_invariants(r)


# --- Tie-break table (DESIGN-001 §8) --------------------------------------


def test_compute_spar_verdict_3_0_accept() -> None:
    reviews = (_judge("evidence_auditor", "accept"), _judge("domain_skeptic", "accept"),
               _judge("final_judge", "accept"))
    assert compute_spar_verdict(reviews) == "accept_clean"


def test_compute_spar_verdict_2_1_accept() -> None:
    reviews = (_judge("evidence_auditor", "accept"), _judge("domain_skeptic", "reject"),
               _judge("final_judge", "accept"))
    assert compute_spar_verdict(reviews) == "accept_caveated"


def test_compute_spar_verdict_1_2_reject() -> None:
    reviews = (_judge("evidence_auditor", "accept"), _judge("domain_skeptic", "reject"),
               _judge("final_judge", "reject"))
    assert compute_spar_verdict(reviews) == "reject_majority"


def test_compute_spar_verdict_0_3_reject() -> None:
    reviews = (_judge("evidence_auditor", "reject"), _judge("domain_skeptic", "reject"),
               _judge("final_judge", "reject"))
    assert compute_spar_verdict(reviews) == "reject_critical"


def test_compute_spar_verdict_requires_three() -> None:
    with pytest.raises(SPARInvariantError, match="exactly 3"):
        compute_spar_verdict((_judge("evidence_auditor"), _judge("final_judge")))


# --- Verdict-vs-vote consistency (P1 reviewer fix) -------------------------


def test_spar_invariant_rejects_verdict_contradicting_three_accepts() -> None:
    """3 accept votes with verdict='reject_critical' is the canonical
    stale/hand-edited case. The invariant must catch it."""
    reviews = (_judge("evidence_auditor", "accept"),
               _judge("domain_skeptic", "accept"),
               _judge("final_judge", "accept"))
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="reject_critical",  # WRONG — three accepts mean accept_clean
        dissent=None, final_judge_resolution="r",
    )
    with pytest.raises(SPARInvariantError, match="contradicts the votes"):
        assert_spar_invariants(r)


def test_spar_invariant_rejects_verdict_contradicting_three_rejects() -> None:
    reviews = (_judge("evidence_auditor", "reject"),
               _judge("domain_skeptic", "reject"),
               _judge("final_judge", "reject"))
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="accept_clean",  # WRONG
        dissent=None, final_judge_resolution="r",
    )
    with pytest.raises(SPARInvariantError, match="contradicts the votes"):
        assert_spar_invariants(r)


def test_spar_invariant_rejects_split_with_wrong_direction() -> None:
    """2 accepts should be 'accept_caveated', not 'reject_majority'."""
    reviews = (_judge("evidence_auditor", "accept"),
               _judge("domain_skeptic", "reject"),
               _judge("final_judge", "accept"))
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="reject_majority",  # WRONG — 2 accepts means accept_caveated
        dissent=reviews[1], final_judge_resolution="r",
    )
    with pytest.raises(SPARInvariantError, match="contradicts the votes"):
        assert_spar_invariants(r)


def test_spar_invariant_passes_when_verdict_matches() -> None:
    """All 4 valid (vote, verdict) pairs from the tie-break table pass."""
    pairs = [
        (("accept", "accept", "accept"), "accept_clean", None),
        (("accept", "reject", "accept"), "accept_caveated", "domain_skeptic"),
        (("accept", "reject", "reject"), "reject_majority", "evidence_auditor"),
        (("reject", "reject", "reject"), "reject_critical", None),
    ]
    for votes, verdict, dissent_role in pairs:
        reviews = (_judge("evidence_auditor", votes[0]),
                   _judge("domain_skeptic", votes[1]),
                   _judge("final_judge", votes[2]))
        dissent = next((r for r in reviews if r.judge_role == dissent_role), None)
        r = SPARReview(
            submission_id="m1", reviews=reviews,
            verdict=verdict, dissent=dissent,
            final_judge_resolution="r",
        )
        assert_spar_invariants(r)  # no raise


# --- Dissent membership + minority-verdict checks (P1 reviewer fix) -------


def test_spar_dissent_must_be_one_of_the_three_reviews() -> None:
    """A fabricated dissent (not equal to any of the 3 reviews) must be rejected."""
    reviews = (_judge("evidence_auditor", "accept"),
               _judge("domain_skeptic", "reject"),
               _judge("final_judge", "accept"))
    fabricated = JudgeReview(
        judge_role="domain_skeptic", model="m", verdict="reject",
        score=2,
        # Distinguishing rationale ensures __eq__ rejects it as not-in-reviews
        # (the real domain_skeptic has rationale='ok').
        rationale="totally fabricated rationale that doesn't match any real review",
        flagged_claims=("C99",),
    )
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="accept_caveated", dissent=fabricated,
        final_judge_resolution="r",
    )
    with pytest.raises(SPARInvariantError, match="not present in reviews"):
        assert_spar_invariants(r)


def test_spar_dissent_with_majority_verdict_is_rejected() -> None:
    """Dissent must be the MINORITY voice. A majority review labelled as dissent
    corrupts the audit trail."""
    reviews = (_judge("evidence_auditor", "accept"),
               _judge("domain_skeptic", "reject"),
               _judge("final_judge", "accept"))
    # majority = accept; dissent should be a 'reject' review. Pass an 'accept'
    # review (the auditor) and assert the invariant catches it.
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="accept_caveated", dissent=reviews[0],  # auditor accepted (majority)
        final_judge_resolution="r",
    )
    with pytest.raises(SPARInvariantError, match="matches the majority"):
        assert_spar_invariants(r)


def test_spar_dissent_with_majority_verdict_in_reject_split() -> None:
    """Same check on the reject side: a 'reject' review labelled as dissent in
    a 1-2 reject split is invalid."""
    reviews = (_judge("evidence_auditor", "accept"),
               _judge("domain_skeptic", "reject"),
               _judge("final_judge", "reject"))
    # majority = reject; dissent should be the auditor (accept). Pass the
    # skeptic (reject — majority) instead.
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="reject_majority", dissent=reviews[1],  # skeptic rejected (majority)
        final_judge_resolution="r",
    )
    with pytest.raises(SPARInvariantError, match="matches the majority"):
        assert_spar_invariants(r)


def test_spar_dissent_correctly_identified_as_minority_passes() -> None:
    """Happy path: minority voice correctly placed as dissent."""
    # 2-1 accept: skeptic dissents (reject vote)
    reviews = (_judge("evidence_auditor", "accept"),
               _judge("domain_skeptic", "reject"),
               _judge("final_judge", "accept"))
    r = SPARReview(
        submission_id="m1", reviews=reviews,
        verdict="accept_caveated", dissent=reviews[1],  # skeptic = minority
        final_judge_resolution="resolved",
    )
    assert_spar_invariants(r)

    # 1-2 reject: auditor dissents (accept vote)
    reviews2 = (_judge("evidence_auditor", "accept"),
                _judge("domain_skeptic", "reject"),
                _judge("final_judge", "reject"))
    r2 = SPARReview(
        submission_id="m2", reviews=reviews2,
        verdict="reject_majority", dissent=reviews2[0],  # auditor = minority
        final_judge_resolution="resolved",
    )
    assert_spar_invariants(r2)
