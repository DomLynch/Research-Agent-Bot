"""Tests for agent/paper_writer.py — full-paper rendering helpers.

Day 10.17 Fix A coverage: _build_user_prompt must not include
rejected (SPAR-quarantined) receipts in the LLM prompt context. The
LLM should physically not see what it's not allowed to cite.
"""
from __future__ import annotations

import asyncio

from agent import paper_writer
from agent.paper_writer_helpers import strip_rendered_citation_markers
from agent.paper_writer import _build_user_prompt, write_results_section
from agent.synthesis_schemas import (
    EffectDirection,
    OutcomeClass,
    ReceiptSummary,
    SynthesisSection,
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


def test_results_writer_wraps_each_outcome_after_citation_fix(monkeypatch) -> None:
    receipts = [
        _summary("r-immune", outcome="immune"),
        _summary("r-longevity", outcome="longevity"),
    ]
    parsed_by_call = iter([
        {"subsections": [{
            "outcome_class": "immune",
            "paragraphs": [{
                "text": "Immune evidence remains mixed across included sources.",
                "receipt_ids": ["r-immune"],
            }],
        }]},
        {"subsections": [{
            "outcome_class": "longevity",
            "paragraphs": [{
                "text": "Longevity evidence discusses lifespan and offspring context.",
                "receipt_ids": ["r-longevity"],
            }],
        }]},
    ])

    async def fake_call(**_kwargs):
        return next(parsed_by_call)

    async def fake_citation_fix(section, **_kwargs):
        if section and "### Longevity Outcomes" in section.body_md:
            return SynthesisSection(
                name="results",
                body_md=section.body_md.replace("### Longevity Outcomes\n\n", ""),
                anchors=section.anchors,
            )
        return section

    monkeypatch.setattr(paper_writer, "_call_llm_section", fake_call)
    monkeypatch.setattr(paper_writer, "_run_citation_fix_pass", fake_citation_fix)
    monkeypatch.setattr(paper_writer, "SECTION_RETRY_BUDGET", 0)

    section = asyncio.run(write_results_section(
        receipts, [], _matrix(receipts), _thesis(),
        topic="caloric_restriction", chain=(),
    ))

    assert "### Immune Outcomes" in section.body_md
    assert "### Longevity Outcomes" in section.body_md
    immune_body = section.body_md.split("### Immune Outcomes", 1)[1].split("###", 1)[0]
    assert "lifespan" not in immune_body


def test_strip_rendered_citation_markers_removes_body_metadata() -> None:
    md = (
        "## Results\n\n"
        "_Cited: `Moel 2025`_\n"
        "Rapamycin evidence remains bounded.\n"
    )
    out = strip_rendered_citation_markers(md)
    assert "_Cited:" not in out
    assert "Rapamycin evidence remains bounded." in out


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


# ============ Fix #27 — prose-compression word floors ===============


def test_section_word_floors_protect_analytical_depth() -> None:
    """Fix #45 (post Fix #27 review): the two intellectual-core
    sections — Discussion and Cross-Domain Synthesis — must have
    floors at or above downstream audit/surface gates so the writer cannot land at 310 / 525 words
    (the grok-smart paper's desk-reject regression). Lean
    Introduction/Background floors stay (Fix #27 was right for
    those — they're not analytical sections)."""
    from agent.paper_writer import SECTION_WORD_FLOORS
    assert SECTION_WORD_FLOORS["abstract"] <= 250
    assert SECTION_WORD_FLOORS["introduction"] <= 1000
    assert SECTION_WORD_FLOORS["background"] <= 800
    assert SECTION_WORD_FLOORS["results"] <= 1700
    # Analytical-core floors RESTORED after Fix #27 over-compression
    assert SECTION_WORD_FLOORS["cross_domain_synthesis"] >= 850
    assert SECTION_WORD_FLOORS["discussion"] >= 900
    assert SECTION_WORD_FLOORS["limitations_full"] <= 500
    assert SECTION_WORD_FLOORS["conclusion"] <= 300


def test_section_prompts_use_explicit_targets() -> None:
    """Mixed contract per Fix #27 + Fix #45:
      - Lean sections (Intro/Background/Results/Limitations/Conclusion)
        use `TARGET RANGE` (Fix #27 prose compression)
      - Analytical sections (Discussion/CrossDomain) use
        `HARD MINIMUM` (Fix #45 depth restoration)
    Either explicit-target language is acceptable; what matters is
    the prompt isn't silent on word count."""
    from agent.paper_writer_prompts import (
        BACKGROUND_SYSTEM_PROMPT, CONCLUSION_SYSTEM_PROMPT,
        CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT,
        DISCUSSION_SYSTEM_PROMPT, INTRODUCTION_SYSTEM_PROMPT,
        LIMITATIONS_FULL_SYSTEM_PROMPT, RESULTS_SYSTEM_PROMPT,
    )
    for name, prompt in (
        ("BACKGROUND", BACKGROUND_SYSTEM_PROMPT),
        ("CONCLUSION", CONCLUSION_SYSTEM_PROMPT),
        ("CROSS_DOMAIN", CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT),
        ("DISCUSSION", DISCUSSION_SYSTEM_PROMPT),
        ("INTRODUCTION", INTRODUCTION_SYSTEM_PROMPT),
        ("LIMITATIONS", LIMITATIONS_FULL_SYSTEM_PROMPT),
        ("RESULTS", RESULTS_SYSTEM_PROMPT),
    ):
        assert (
            "TARGET RANGE" in prompt
            or "HARD MINIMUM" in prompt
            or "Fix #27" in prompt
            or "Fix #45" in prompt
        ), f"{name} prompt missing explicit word-count target"


def test_discussion_and_cross_domain_prompts_demand_900_word_floor() -> None:
    """Fix #45: the analytical-core sections explicitly require ≥900
    words to prevent the grok-smart 310/525 regression."""
    from agent.paper_writer_prompts import (
        CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT,
        DISCUSSION_SYSTEM_PROMPT,
    )
    for name, prompt in (
        ("DISCUSSION", DISCUSSION_SYSTEM_PROMPT),
        ("CROSS_DOMAIN", CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT),
    ):
        assert "900" in prompt, (
            f"{name} prompt no longer carries the 900-word floor "
            "(Fix #45 regression)"
        )
        assert "adjudicate" in prompt.lower(), (
            f"{name} prompt no longer requires per-paragraph "
            "tension adjudication"
        )


def test_conclusion_prompt_demands_clinical_practice_statement() -> None:
    """2026-05-09 peer-review fix (Bug 3): the panel found the conclusion
    correctly hedged "evidence is mixed and incomplete" but did not state
    the actionable clinical-practice implication. The prompt now requires
    an off-label-use statement."""
    from agent.paper_writer_prompts import CONCLUSION_SYSTEM_PROMPT
    assert "clinical-practice" in CONCLUSION_SYSTEM_PROMPT.lower(), (
        "Conclusion prompt no longer demands a clinical-practice "
        "statement (peer-review fix 2026-05-09 regression)"
    )
    assert "off-label" in CONCLUSION_SYSTEM_PROMPT.lower(), (
        "Conclusion prompt no longer references off-label-use guidance"
    )
    assert "Pending further trials" in CONCLUSION_SYSTEM_PROMPT, (
        "Conclusion prompt no longer carries the canonical "
        "'Pending further trials' phrase template"
    )


def test_conclusion_prompt_lists_required_content_item_5() -> None:
    """The required-content list must enumerate the new clinical-practice
    requirement as item 5 — older runs had only 4 items."""
    from agent.paper_writer_prompts import CONCLUSION_SYSTEM_PROMPT
    # The literal "5." marker for required content is load-bearing —
    # the writer LLM keys off the numbered list.
    assert "5." in CONCLUSION_SYSTEM_PROMPT
    # Sanity: the prior 4 items must still be present.
    for marker in ("1.", "2.", "3.", "4."):
        assert marker in CONCLUSION_SYSTEM_PROMPT


def test_conclusion_prompt_word_target_accommodates_extra_clause() -> None:
    """Adding the clinical-practice clause bumped target from
    250-350 → 280-380 words. The prompt's word target should reflect this."""
    from agent.paper_writer_prompts import CONCLUSION_SYSTEM_PROMPT
    assert "280-380" in CONCLUSION_SYSTEM_PROMPT or "280" in CONCLUSION_SYSTEM_PROMPT


def test_conclusion_prompt_retains_overclaim_guard() -> None:
    """Regression: the new clause must not weaken the existing overclaim
    guard (no unhedged 'extends lifespan' or similar)."""
    from agent.paper_writer_prompts import CONCLUSION_SYSTEM_PROMPT
    assert "extends lifespan" in CONCLUSION_SYSTEM_PROMPT  # in the do-NOT list
    assert "unhedged clinical claim" in CONCLUSION_SYSTEM_PROMPT.lower()
