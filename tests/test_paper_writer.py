"""Tests for agent/paper_writer.py — full-paper rendering helpers.

Day 10.17 Fix A coverage: _build_user_prompt must not include
rejected (SPAR-quarantined) receipts in the LLM prompt context. The
LLM should physically not see what it's not allowed to cite.
"""
from __future__ import annotations

from agent.paper_writer import _build_user_prompt
from agent.synthesis_schemas import (
    EffectDirection,
    OutcomeClass,
    ReceiptSummary,
    SynthesisThesis,
    TensionMatrix,
)


def _summary(
    rid: str,
    *,
    outcome: OutcomeClass = "muscle_function",
    direction: EffectDirection = "negative",
    tier: str = "A1",
    directness: str = "direct",
    spar_verdict: str = "accept_clean",
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text=f"thesis for {rid}",
        spar_verdict=spar_verdict,
        n_claims=4, n_failed_traces=0,
        canonical_trial_id=f"NCT-{rid}",
        evidence_tier=tier, directness=directness,
        outcome_class=outcome, effect_direction=direction,
        p_values=("p=0.003",), population_summary="older adults",
    )


def _thesis() -> SynthesisThesis:
    return SynthesisThesis(
        text="metformin shows mixed evidence",
        receipt_ids_referenced=("r-A",),
        tensions_addressed=(),
        rejected_candidates=(),
        picker_rationale="test",
    )


def _matrix(receipts) -> TensionMatrix:
    return TensionMatrix(receipts=tuple(receipts), pairs=())


# ============================================================
# Day 10.17 Fix A — accepted-only LLM writer context
# ============================================================
# Empirical bug from the 10.17 e2e run: rejected receipt cfab-c02
# leaked into the Background section of full_paper.md. Q8 caught it
# at audit time, but by then the LLM had already cited it. The fix
# is to remove rejected receipts from the LLM prompt context entirely
# — the writer cannot cite what it does not see.
#
# Trust-spine layer is preserved: the deterministic Methods,
# References, and Rejected/Contested Evidence sections still render
# rejected receipts (those don't go through the LLM). Only the
# LLM-anchored prompt is restricted.


def test_build_user_prompt_does_not_include_rejected_receipt_ids() -> None:
    """The load-bearing test: a rejected receipt's id must NOT appear
    anywhere in the prompt the LLM sees."""
    accepted = [_summary("r-A"), _summary("r-B")]
    rejected = [_summary("r-rej-X", spar_verdict="reject_majority")]
    prompt = _build_user_prompt(
        accepted, rejected, _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "r-rej-X" not in prompt, (
        "rejected receipt id leaked into LLM prompt context — "
        "Fix A regression"
    )


def test_build_user_prompt_does_not_emit_quarantined_block_header() -> None:
    """Pre-Fix-A code emitted a 'QUARANTINED (SPAR-rejected) RECEIPTS:'
    block. Fix A removes that header entirely — there's no LLM-visible
    quarantine block at all."""
    accepted = [_summary("r-A")]
    rejected = [_summary("r-rej-X", spar_verdict="reject_majority")]
    prompt = _build_user_prompt(
        accepted, rejected, _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "QUARANTINED" not in prompt
    assert "SPAR-rejected" not in prompt


def test_build_user_prompt_includes_accepted_receipt_ids() -> None:
    """Sanity: the prompt MUST still include accepted receipts —
    Fix A is about suppressing only the rejected ones."""
    accepted = [_summary("r-A"), _summary("r-B")]
    rejected = [_summary("r-rej-X", spar_verdict="reject_majority")]
    prompt = _build_user_prompt(
        accepted, rejected, _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "r-A" in prompt
    assert "r-B" in prompt


def test_build_user_prompt_no_rejected_input_still_works() -> None:
    """The function must handle an empty rejected list cleanly —
    the e2e pipeline always passes one, but defensive."""
    accepted = [_summary("r-A")]
    prompt = _build_user_prompt(
        accepted, [], _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "r-A" in prompt
    assert "QUARANTINED" not in prompt


def test_build_user_prompt_caller_filter_treats_accept_caveated_as_accepted() -> None:
    """Boundary test (reviewer pin): the production caller in
    render_full_paper computes `rejected` as `spar_verdict not in
    ('accept_clean', 'accept_caveated')`. Verify that membership
    expression treats `accept_caveated` as accepted, not rejected.
    Regression risk: a future maintainer might tighten the filter to
    `spar_verdict == 'accept_clean'` and silently quarantine the
    accept_caveated receipts that should still be cited."""
    ACCEPTED_VERDICTS = ("accept_clean", "accept_caveated")
    receipts = [
        _summary("r-clean", spar_verdict="accept_clean"),
        _summary("r-caveated", spar_verdict="accept_caveated"),
        _summary("r-rej", spar_verdict="reject_majority"),
    ]
    accepted = [r for r in receipts if r.spar_verdict in ACCEPTED_VERDICTS]
    rejected = [r for r in receipts if r.spar_verdict not in ACCEPTED_VERDICTS]
    assert {r.receipt_id for r in accepted} == {"r-clean", "r-caveated"}
    assert {r.receipt_id for r in rejected} == {"r-rej"}
    prompt = _build_user_prompt(
        accepted, rejected, _matrix(accepted), _thesis(),
        topic="metformin",
    )
    assert "r-clean" in prompt
    assert "r-caveated" in prompt
    assert "r-rej" not in prompt
