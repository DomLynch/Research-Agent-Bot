"""Unit tests for agent.synthesis_writer_q3 (Day 10.16e).

The Q3 invariant says: when the corpus has both direct and
mechanistic/indirect receipts, the synthesis section MUST contain at
least one anchor whose receipt_ids cite both directnesses AND whose
sentence starts with a transition phrase. These tests verify the
predicate, not the LLM retry path (which is exercised in the
integration test).
"""
from __future__ import annotations

from agent.synthesis_schemas import (
    ReceiptSummary,
    SynthesisClaimAnchor,
    SynthesisSection,
)
from agent.synthesis_writer_q3 import (
    Q3_TRANSITION_PHRASES,
    SYNTHESIS_Q3_RETRY_BUDGET,
    q3_retry_user_prompt,
    synthesis_has_mixed_directness_anchor,
)


def _summary(rid: str, *, directness: str = "direct") -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text=f"thesis for {rid}", spar_verdict="accept_clean",
        n_claims=1, n_failed_traces=0, canonical_trial_id=None,
        evidence_tier="A1", directness=directness,
        outcome_class="muscle_function", effect_direction="negative",
        p_values=(), population_summary="older adults",
    )


def _section(*anchors: SynthesisClaimAnchor) -> SynthesisSection:
    return SynthesisSection(
        name="synthesis", body_md="## Synthesis\n\n_stub_\n",
        anchors=tuple(anchors),
    )


# --- predicate: returns True when corpus is uniform-directness ----------


def test_uniform_corpus_passes_invariant_vacuously() -> None:
    receipts = [_summary("r-A"), _summary("r-B")]  # both direct
    section = _section()
    assert synthesis_has_mixed_directness_anchor(section, receipts) is True


def test_all_mechanistic_corpus_passes_invariant_vacuously() -> None:
    receipts = [
        _summary("r-A", directness="mechanistic"),
        _summary("r-B", directness="mechanistic"),
    ]
    section = _section()
    assert synthesis_has_mixed_directness_anchor(section, receipts) is True


# --- predicate: false when mixed corpus + no integrating anchor ---------


def test_mixed_corpus_no_integrating_anchor_fails() -> None:
    receipts = [
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
    ]
    section = _section(
        SynthesisClaimAnchor(
            sentence="Metformin shows benefit (r-A).",
            receipt_ids=("r-A",), numerics=(),
        ),
        SynthesisClaimAnchor(
            sentence="Mechanistically, AMPK activation occurs (r-B).",
            receipt_ids=("r-B",), numerics=(),
        ),
    )
    assert synthesis_has_mixed_directness_anchor(section, receipts) is False


def test_mixed_corpus_integrating_anchor_without_transition_fails() -> None:
    receipts = [
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
    ]
    section = _section(
        SynthesisClaimAnchor(
            sentence="Metformin reduces muscle gain and modulates AMPK.",
            receipt_ids=("r-A", "r-B"), numerics=(),
        ),
    )
    assert synthesis_has_mixed_directness_anchor(section, receipts) is False


def test_mixed_corpus_integrating_anchor_with_transition_passes() -> None:
    receipts = [
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
    ]
    section = _section(
        SynthesisClaimAnchor(
            sentence="Mechanistically, metformin modulates AMPK signaling, but clinically the muscle outcome is mixed.",
            receipt_ids=("r-A", "r-B"), numerics=(),
        ),
    )
    assert synthesis_has_mixed_directness_anchor(section, receipts) is True


def test_indirect_directness_also_satisfies_mix() -> None:
    receipts = [
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="indirect"),
    ]
    section = _section(
        SynthesisClaimAnchor(
            sentence="In contrast, the indirect evidence suggests a different population.",
            receipt_ids=("r-A", "r-B"), numerics=(),
        ),
    )
    assert synthesis_has_mixed_directness_anchor(section, receipts) is True


def test_consequently_satisfies_q3_after_day_10_16f_widening() -> None:
    """Day 10.16e empirical run produced a Q3-compliant integrating
    sentence ('Consequently, while metformin may...') that the audit
    rejected because 'consequently,' was not in the original 6-phrase
    whitelist. Day 10.16f admits the natural causal-bridge transitions
    'consequently,' and 'therefore,' so this kind of evidence-
    integration sentence passes Q3."""
    receipts = [
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
    ]
    section = _section(
        SynthesisClaimAnchor(
            sentence="Consequently, while metformin may optimize insulin sensitivity, it may simultaneously hinder muscle accrual.",
            receipt_ids=("r-A", "r-B"), numerics=(),
        ),
    )
    assert synthesis_has_mixed_directness_anchor(section, receipts) is True


def test_therefore_satisfies_q3_after_day_10_16f_widening() -> None:
    receipts = [
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
    ]
    section = _section(
        SynthesisClaimAnchor(
            sentence="Therefore, the mechanistic correlate of insulin sensitivity translates to a measurable clinical effect.",
            receipt_ids=("r-A", "r-B"), numerics=(),
        ),
    )
    assert synthesis_has_mixed_directness_anchor(section, receipts) is True


def test_day_10_16g_canonical_markers_satisfy_q3() -> None:
    """Day 10.16f run produced an integrating sentence beginning
    'Ultimately,' — Day 10.16g admits the rest of the canonical
    discourse markers ('ultimately,', 'thus,', 'conversely,',
    'nevertheless,', 'nonetheless,'). All five must satisfy Q3."""
    receipts = [
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
    ]
    for marker in ("Ultimately,", "Thus,", "Conversely,",
                   "Nevertheless,", "Nonetheless,"):
        section = _section(
            SynthesisClaimAnchor(
                sentence=f"{marker} the integration of evidence supports a mixed picture.",
                receipt_ids=("r-A", "r-B"), numerics=(),
            ),
        )
        assert synthesis_has_mixed_directness_anchor(section, receipts), (
            f"marker '{marker}' should satisfy Q3 after 10.16g"
        )


# --- retry prompt: names actual receipt IDs by directness ---------------


def test_retry_prompt_names_direct_and_mechanistic_receipts() -> None:
    receipts = [
        _summary("r-direct-A", directness="direct"),
        _summary("r-mech-X", directness="mechanistic"),
        _summary("r-mech-Y", directness="mechanistic"),
    ]
    out = q3_retry_user_prompt("BASE", receipts)
    assert "BASE" in out
    assert "r-direct-A" in out
    assert "r-mech-X" in out
    assert "r-mech-Y" in out
    assert "Q3 RETRY GUIDANCE" in out
    assert "transition phrases" in out


def test_retry_prompt_handles_empty_directness_groups() -> None:
    receipts_only_direct = [_summary("r-A", directness="direct")]
    out = q3_retry_user_prompt("BASE", receipts_only_direct)
    assert "(none)" in out  # mechanistic side empty


# --- module-level constants ---------------------------------------------


def test_transition_phrases_match_audit_set() -> None:
    """If audit's _TRANSITION_PHRASES drifts, this test must be updated
    in lockstep. The two sets are intentionally duplicated rather than
    imported (writer→audit cycle) but they MUST remain identical."""
    from agent.synthesis_audit import _TRANSITION_PHRASES
    assert tuple(Q3_TRANSITION_PHRASES) == tuple(_TRANSITION_PHRASES)


def test_retry_budget_is_one() -> None:
    """Day 10.16e contract: a model that under-integrates twice in a
    row is unlikely to do better on attempt 3. Budget is finite."""
    assert SYNTHESIS_Q3_RETRY_BUDGET == 1
