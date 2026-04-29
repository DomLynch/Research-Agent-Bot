"""Tests for agent/synthesis_thesis.py — Day 10.3 thesis tournament.

Discriminating tests cover:
  - validation contract: each rule fails for the right reason
  - picker ranking: more receipts > more tensions > brevity > alpha
  - fallback stub: produces a valid SynthesisThesis when all candidates
    fail validation
  - LLM-mock proposal flow: build_thesis_user_prompt is deterministic,
    parsing is defensive, end-to-end synthesize_thesis works

The trust-spine analogue for synthesis: same-input-same-output
(deterministic when seed is set), no LLM-fabricated receipt_ids slip
through, no novel numerics enter the synthesis layer.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from agent.llm_client import CallSpec
from agent.synthesis_schemas import (
    EffectDirection,
    OutcomeClass,
    ReceiptSummary,
    SynthesisThesisCandidate,
    Tension,
    TensionMatrix,
)
from agent.synthesis_thesis import (
    SYSTEM_PROMPT,
    THESIS_PROMPT_VERSION,
    build_fallback_thesis,
    build_thesis_user_prompt,
    pick_synthesis_thesis,
    synthesize_thesis,
    validate_thesis_candidate,
)


# --- Fixtures -------------------------------------------------------------


def _summary(
    rid: str,
    *,
    outcome: OutcomeClass = "muscle_function",
    direction: EffectDirection = "negative",
    tier: str = "A1",
    directness: str = "direct",
    p_values: tuple[str, ...] = ("p=0.003",),
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}",
        topic="metformin",
        thesis_text=f"thesis text for {rid}",
        spar_verdict="accept_clean",
        n_claims=4, n_failed_traces=0,
        canonical_trial_id=f"NCT-{rid}",
        evidence_tier=tier, directness=directness,
        outcome_class=outcome,
        effect_direction=direction,
        p_values=p_values,
        population_summary="older adults",
    )


def _receipts_three() -> tuple[ReceiptSummary, ReceiptSummary, ReceiptSummary]:
    return (_summary("r-A"), _summary("r-B", outcome="cardiometabolic"), _summary("r-C", outcome="frailty"))


def _matrix_with_one_tension(receipts) -> TensionMatrix:
    """Synthetic matrix with one non-orthogonal tension between r-A
    and r-B for the validation tests to address."""
    pairs = (
        Tension(
            receipt_a_id="r-A", receipt_b_id="r-B",
            kind="agreement", outcome_class="muscle_function",
            summary="r-A and r-B both report negative effect on muscle_function",
            severity=2,
        ),
        Tension(
            receipt_a_id="r-A", receipt_b_id="r-C",
            kind="orthogonal", outcome_class="muscle_function",
            summary="orthogonal", severity=0,
        ),
        Tension(
            receipt_a_id="r-B", receipt_b_id="r-C",
            kind="orthogonal", outcome_class="cardiometabolic",
            summary="orthogonal", severity=0,
        ),
    )
    return TensionMatrix(receipts=tuple(receipts), pairs=pairs)


def _candidate(
    text: str = "Metformin shows mixed evidence across muscle, cardio, and frailty trials",
    *,
    refs: tuple[str, ...] = ("r-A", "r-B", "r-C"),
    tensions: tuple[str, ...] = (
        "r-A and r-B both report negative effect on muscle_function",
    ),
) -> SynthesisThesisCandidate:
    return SynthesisThesisCandidate(
        text=text,
        receipt_ids_referenced=refs,
        tensions_addressed=tensions,
        word_count=len(text.split()),
    )


# ============================================================
# validate_thesis_candidate — each contract rule fails right
# ============================================================


def test_validate_passes_well_formed_candidate() -> None:
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    rej = validate_thesis_candidate(_candidate(), receipts, matrix)
    assert rej is None


def test_validate_rejects_empty_text() -> None:
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    rej = validate_thesis_candidate(
        _candidate(text="   "), receipts, matrix,
    )
    assert rej is not None
    assert rej.reason == "empty_text"


def test_validate_rejects_too_long_thesis() -> None:
    """≤30 words is the cap. Reference papers are 14-25 words; longer
    means the LLM is overclaiming."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    long_text = " ".join(["word"] * 50)
    cand = SynthesisThesisCandidate(
        text=long_text,
        receipt_ids_referenced=("r-A", "r-B", "r-C"),
        tensions_addressed=(
            "r-A and r-B both report negative effect on muscle_function",
        ),
        word_count=50,
    )
    rej = validate_thesis_candidate(cand, receipts, matrix)
    assert rej is not None
    assert rej.reason.startswith("too_long")


def test_validate_rejects_unknown_receipt_id() -> None:
    """Synthesis-layer analogue of spar.py's flagged-claim-id check.
    LLM-fabricated ids must be caught."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    cand = _candidate(refs=("r-A", "r-B", "r-FAKE"))
    rej = validate_thesis_candidate(cand, receipts, matrix)
    assert rej is not None
    assert "unknown_receipt_ids" in rej.reason
    assert "r-FAKE" in rej.reason


def test_validate_rejects_too_few_receipts() -> None:
    """Single-trial generalization is the most common synthesis failure
    mode. Require ≥3 distinct receipts."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    cand = _candidate(refs=("r-A", "r-B"))  # only 2
    rej = validate_thesis_candidate(cand, receipts, matrix)
    assert rej is not None
    assert "too_few_receipts" in rej.reason


def test_validate_rejects_no_tension_addressed_when_matrix_has_one() -> None:
    """When the matrix has a non-orthogonal tension, the thesis must
    name at least one verbatim in `tensions_addressed`. Day 10.10
    reverted Day 10.9's pair-coverage relaxation: pair-coverage made
    the validator too lenient (a thesis citing both refs but taking no
    position on the tension would pass). Strict verbatim match it is."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    cand = _candidate(refs=("r-A", "r-B", "r-C"), tensions=())
    rej = validate_thesis_candidate(cand, receipts, matrix)
    assert rej is not None
    assert rej.reason == "no_tension_addressed"


def test_validate_rejects_pair_coverage_alone_after_day10_10() -> None:
    """Day 10.10 regression guard: pair-coverage alone (refs include
    both receipt_a_id and receipt_b_id of a non-orth tension) is NOT
    enough to address the tension. The candidate must NAME it via
    verbatim summary in `tensions_addressed`, forcing the thesis to
    actually take a position on the tension rather than just structurally
    spanning the pair."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    # All refs cover the tension pair (r-A, r-B), but tensions=() means
    # no verbatim match. Day 10.10 strict verbatim → reject.
    cand = _candidate(refs=("r-A", "r-B", "r-C"), tensions=())
    rej = validate_thesis_candidate(cand, receipts, matrix)
    assert rej is not None and rej.reason == "no_tension_addressed"


def test_validate_allows_no_tensions_addressed_when_matrix_is_orthogonal() -> None:
    """If every pair is orthogonal, there are no tensions to name —
    requiring `tensions_addressed` to be non-empty would create an
    impossible contract. Allow empty in that case."""
    receipts = _receipts_three()
    # Matrix with ONLY orthogonal pairs
    matrix = TensionMatrix(
        receipts=tuple(receipts),
        pairs=(
            Tension(
                receipt_a_id="r-A", receipt_b_id="r-B",
                kind="orthogonal", outcome_class="muscle_function",
                summary="orthogonal", severity=0,
            ),
        ),
    )
    cand = _candidate(tensions=())
    rej = validate_thesis_candidate(cand, receipts, matrix)
    assert rej is None


def test_validate_rejects_novel_numeric_in_thesis() -> None:
    """No new numerics: every numeric token in the candidate must
    appear in some receipt's p_values or thesis_text."""
    receipts = _receipts_three()  # all have p_values=("p=0.003",)
    matrix = _matrix_with_one_tension(receipts)
    # Candidate cites a p-value NONE of the receipts have
    cand = _candidate(
        text="Across r-A r-B r-C trials, the synthesis (p=0.99) shows agreement on muscle.",
    )
    rej = validate_thesis_candidate(cand, receipts, matrix)
    assert rej is not None
    assert rej.reason.startswith("novel_numeric")
    assert "p=0.99" in rej.reason or "p<0.99" in rej.reason or "0.99" in rej.reason


def test_validate_allows_thesis_referencing_receipt_p_value() -> None:
    """When the candidate cites a p-value that DOES appear in some
    receipt, validation passes."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    cand = _candidate(
        text="Across r-A r-B r-C, p=0.003 effect agrees on muscle outcome",
    )
    rej = validate_thesis_candidate(cand, receipts, matrix)
    assert rej is None


# ============================================================
# pick_synthesis_thesis — ranking is deterministic
# ============================================================


def test_picker_prefers_more_receipts_over_fewer() -> None:
    """Two valid candidates: one references 3 receipts, one references
    4. The 4-reference winner has more breadth → wins."""
    receipts = (
        _summary("r-A"), _summary("r-B"), _summary("r-C"), _summary("r-D"),
    )
    matrix = TensionMatrix(
        receipts=receipts,
        pairs=(
            Tension(
                receipt_a_id="r-A", receipt_b_id="r-B",
                kind="agreement", outcome_class="muscle_function",
                summary="r-A and r-B agree on muscle", severity=2,
            ),
        ),
    )
    cand_3 = SynthesisThesisCandidate(
        text="three-receipt thesis spanning r-A r-B r-C",
        receipt_ids_referenced=("r-A", "r-B", "r-C"),
        tensions_addressed=("r-A and r-B agree on muscle",),
        word_count=7,
    )
    cand_4 = SynthesisThesisCandidate(
        text="four-receipt thesis spanning r-A r-B r-C r-D",
        receipt_ids_referenced=("r-A", "r-B", "r-C", "r-D"),
        tensions_addressed=("r-A and r-B agree on muscle",),
        word_count=8,
    )
    thesis = pick_synthesis_thesis([cand_3, cand_4], receipts, matrix)
    assert len(thesis.receipt_ids_referenced) == 4
    assert thesis.text == cand_4.text


def test_picker_prefers_more_tensions_at_equal_breadth() -> None:
    """Tied on receipts (both 3); winner has more tensions addressed."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    cand_one_t = _candidate(
        text="thesis A 3 receipts 1 tension addressed",
        tensions=("r-A and r-B both report negative effect on muscle_function",),
    )
    # Synthetic — pretend matrix had two tensions for this test
    matrix_two = TensionMatrix(
        receipts=matrix.receipts,
        pairs=matrix.pairs + (
            Tension(
                receipt_a_id="r-A", receipt_b_id="r-C",
                kind="agreement", outcome_class="muscle_function",
                summary="second tension", severity=2,
            ),
        ),
    )
    cand_two_t = SynthesisThesisCandidate(
        text="thesis B 3 receipts 2 tensions addressed",
        receipt_ids_referenced=("r-A", "r-B", "r-C"),
        tensions_addressed=(
            "r-A and r-B both report negative effect on muscle_function",
            "second tension",
        ),
        word_count=7,
    )
    thesis = pick_synthesis_thesis(
        [cand_one_t, cand_two_t], receipts, matrix_two,
    )
    assert thesis.text == cand_two_t.text
    assert len(thesis.tensions_addressed) == 2


def test_picker_prefers_brevity_at_equal_receipts_and_tensions() -> None:
    """Brevity-wins tiebreak: same receipts, same tensions, shorter wins.
    Reference papers (Witham 2025, Mohammed 2021) are tight."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    short = SynthesisThesisCandidate(
        text="short thesis r-A r-B r-C tension",
        receipt_ids_referenced=("r-A", "r-B", "r-C"),
        tensions_addressed=(
            "r-A and r-B both report negative effect on muscle_function",
        ),
        word_count=6,
    )
    long_ = SynthesisThesisCandidate(
        text="much longer thesis r-A r-B r-C tension with extra qualifying clauses",
        receipt_ids_referenced=("r-A", "r-B", "r-C"),
        tensions_addressed=(
            "r-A and r-B both report negative effect on muscle_function",
        ),
        word_count=10,
    )
    thesis = pick_synthesis_thesis([short, long_], receipts, matrix)
    assert thesis.text == short.text


def test_picker_returns_fallback_stub_when_all_candidates_rejected() -> None:
    """When every candidate fails validation, the picker returns a
    deterministic stub thesis instead of raising. This keeps the
    synthesis pipeline shipping even when the LLM is misbehaving."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    bad_1 = _candidate(refs=("r-A",))  # too few receipts
    bad_2 = _candidate(refs=("r-A", "r-B", "r-FAKE"))  # unknown id
    thesis = pick_synthesis_thesis(
        [bad_1, bad_2], receipts, matrix, topic="metformin",
    )
    assert "fallback" in thesis.picker_rationale.lower()
    assert "rejected" in thesis.picker_rationale.lower()
    # Fallback still references all receipts so downstream invariants hold
    assert set(thesis.receipt_ids_referenced) == {"r-A", "r-B", "r-C"}


def test_picker_preserves_rejected_candidates_for_audit() -> None:
    """Losers are kept on the SynthesisThesis for audit traceability."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    winner = _candidate(text="winner thesis r-A r-B r-C tension")
    loser = SynthesisThesisCandidate(
        text="loser overlong thesis " + " ".join(["padding"] * 40),
        receipt_ids_referenced=("r-A", "r-B", "r-C"),
        tensions_addressed=(
            "r-A and r-B both report negative effect on muscle_function",
        ),
        word_count=43,  # > 30 → rejected
    )
    thesis = pick_synthesis_thesis([winner, loser], receipts, matrix)
    assert thesis.text == winner.text
    # Loser preserved
    assert any(c.text.startswith("loser") for c in thesis.rejected_candidates)


# ============================================================
# Fallback stub
# ============================================================


def test_fallback_stub_is_a_valid_synthesis_thesis() -> None:
    """The fallback stub must satisfy the schema invariants — it
    references at least one receipt and produces a non-empty text."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    stub = build_fallback_thesis(receipts, matrix, topic="metformin")
    assert stub.text  # non-empty
    assert len(stub.receipt_ids_referenced) >= 1
    assert "fallback" in stub.picker_rationale.lower()


# ============================================================
# build_thesis_user_prompt — deterministic rendering
# ============================================================


def test_user_prompt_contains_all_receipts() -> None:
    """Same inputs → same prompt. Every receipt's id, thesis_text,
    outcome_class, effect_direction must be in the rendered prompt."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    prompt = build_thesis_user_prompt(receipts, matrix, topic="metformin")
    for r in receipts:
        assert r.receipt_id in prompt
        assert r.thesis_text in prompt
        assert r.outcome_class in prompt


def test_user_prompt_lists_non_orthogonal_tensions_only() -> None:
    """Orthogonal pairs should not clutter the LLM input; only
    actionable tensions go in."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)
    prompt = build_thesis_user_prompt(receipts, matrix, topic="metformin")
    # The agreement tension must appear
    assert "r-A and r-B both report negative" in prompt
    # The orthogonal pairs (summary == "orthogonal") must NOT — they're
    # not actionable for the thesis.
    assert "summary: orthogonal" not in prompt


# ============================================================
# synthesize_thesis — end-to-end with mocked LLM
# ============================================================


def _spec() -> CallSpec:
    return CallSpec(
        base_url="https://api.example.com/v1",
        api_key="k", model="test/model", timeout_sec=5.0,
    )


def test_synthesize_thesis_picks_winner_from_llm_proposal() -> None:
    """End-to-end: mock LLM returns 3 candidates, picker chooses the
    one with most receipts referenced."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)

    candidates_payload = {
        "candidates": [
            {
                "text": "two-receipt candidate r-A r-B agreement",
                "receipt_ids_referenced": ["r-A", "r-B"],  # too few
                "tensions_addressed": [
                    "r-A and r-B both report negative effect on muscle_function",
                ],
            },
            {
                "text": "three-receipt candidate r-A r-B r-C tension",
                "receipt_ids_referenced": ["r-A", "r-B", "r-C"],
                "tensions_addressed": [
                    "r-A and r-B both report negative effect on muscle_function",
                ],
            },
            {
                "text": "another three-receipt longer overall version r-A r-B r-C tension",
                "receipt_ids_referenced": ["r-A", "r-B", "r-C"],
                "tensions_addressed": [
                    "r-A and r-B both report negative effect on muscle_function",
                ],
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": json.dumps(candidates_payload),
            }}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 80},
        })

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await synthesize_thesis(
                receipts, matrix,
                chain=(_spec(),), topic="metformin",
                client=client,
            )
        finally:
            await client.aclose()

    thesis = asyncio.run(go())
    # First candidate (2 refs) is rejected; brevity tiebreak picks
    # the shorter of the two valid 3-refs candidates.
    assert thesis.text.startswith("three-receipt candidate")
    # The 2-receipt candidate is among rejected
    assert any(
        c.text.startswith("two-receipt") for c in thesis.rejected_candidates
    )


def test_synthesize_thesis_falls_back_when_llm_returns_garbage() -> None:
    """Defensive: malformed LLM JSON → no candidates → fallback stub."""
    receipts = _receipts_three()
    matrix = _matrix_with_one_tension(receipts)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": '{"candidates": "this is not a list"}',
            }}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5},
        })

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await synthesize_thesis(
                receipts, matrix,
                chain=(_spec(),), topic="metformin",
                client=client,
            )
        finally:
            await client.aclose()

    thesis = asyncio.run(go())
    assert "fallback" in thesis.picker_rationale.lower()


# ============================================================
# Anchored constants
# ============================================================


def test_thesis_prompt_version_is_anchored() -> None:
    """cost_log records prompt versions for reproducibility — must
    be a stable string."""
    assert THESIS_PROMPT_VERSION == "synthesis-thesis/2026-04-29"


def test_system_prompt_states_required_contracts() -> None:
    """The system prompt must instruct the LLM about the validation
    rules — otherwise it produces non-validating candidates and the
    fallback stub fires every time."""
    assert "≤30 words" in SYSTEM_PROMPT or "30 words" in SYSTEM_PROMPT
    assert "at least 3" in SYSTEM_PROMPT.lower()
    assert "tension" in SYSTEM_PROMPT.lower()
    assert "JSON" in SYSTEM_PROMPT
