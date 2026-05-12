"""Fix #25 — `## What This Synthesis Adds` deterministic section.

Trust spine: the originality claim is grounded in pipeline data
(receipts + matrix + thesis), not LLM rhetoric. These tests pin the
template behaviour."""
from __future__ import annotations

from agent.paper_writer_deterministic import (
    build_what_this_adds_section,
)
from agent.synthesis_schemas import (
    EffectDirection,
    OutcomeClass,
    ReceiptSummary,
    SynthesisThesis,
    Tension,
    TensionMatrix,
)


def _r(
    rid: str, *,
    tier: str = "A1", directness: str = "direct",
    outcome: OutcomeClass = "muscle_function",
    direction: EffectDirection = "negative",
    spar_verdict: str = "accept_clean",
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text=f"thesis for {rid}",
        spar_verdict=spar_verdict,
        n_claims=10, n_failed_traces=0,
        canonical_trial_id=None,
        evidence_tier=tier, directness=directness,
        outcome_class=outcome, effect_direction=direction,
        p_values=("p < 0.001",), population_summary="older adults",
    )


def _matrix(receipts, pairs=()) -> TensionMatrix:
    return TensionMatrix(receipts=tuple(receipts), pairs=tuple(pairs))


def _thesis(text: str = "Metformin shows mixed evidence") -> SynthesisThesis:
    return SynthesisThesis(
        text=text, receipt_ids_referenced=(),
        tensions_addressed=(), rejected_candidates=(),
        picker_rationale="test",
    )


def test_section_has_required_heading() -> None:
    """The section MUST start with `## What This Synthesis Adds` so
    readers can navigate to it directly."""
    md = build_what_this_adds_section(
        [_r("Walton 2019")], _matrix([_r("Walton 2019")]), _thesis(),
        topic="metformin",
    )
    assert md.startswith("## What This Synthesis Adds")


def test_section_includes_corpus_size_and_outcome_count() -> None:
    """The opening sentence must report N sources and N outcome
    classes — the corpus characterisation that grounds originality."""
    receipts = [
        _r("Walton 2019", outcome="muscle_function"),
        _r("Witham 2025", outcome="frailty"),
        _r("Konopka 2019", outcome="cardiometabolic"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="metformin",
    )
    assert "3 eligible sources" in md
    assert "3 outcome classes" in md
    assert "metformin" in md


def test_section_does_not_quote_picked_thesis_verbatim() -> None:
    """The selector thesis can carry internal inventory language; the
    public section states the contribution shape instead."""
    thesis_text = (
        "Metformin's longevity signal coexists with an "
        "exercise-adaptation penalty in older-adult RCTs."
    )
    md = build_what_this_adds_section(
        [_r("Walton 2019")], _matrix([_r("Walton 2019")]),
        _thesis(thesis_text), topic="metformin",
    )
    assert thesis_text not in md
    assert "Central contribution" in md
    assert "Selected thesis" not in md
    assert "Picked thesis" not in md
    assert "Tournament selector" not in md


def test_section_strips_pipeline_direction_inventory_from_thesis() -> None:
    thesis_text = (
        "Across 27 curated papers, the profile is context-dependent. "
        "Positive signals appear in: cardiometabolic, longevity. "
        "Negative signals appear in: muscle function. "
        "Null findings dominate: frailty. "
        "The synthesis surfaces 102 non-orthogonal tensions across "
        "outcome classes — see Cross-Domain Synthesis. "
        "The anti-aging claim remains bounded by functional tradeoffs."
    )
    md = build_what_this_adds_section(
        [_r("Walton 2019")], _matrix([_r("Walton 2019")]),
        _thesis(thesis_text), topic="metformin",
    )
    assert "Positive signals appear in" not in md
    assert "Negative signals appear in" not in md
    assert "Null findings dominate" not in md
    assert "The synthesis surfaces" not in md
    assert "boundary-condition map" in md


def test_section_highlights_load_bearing_tension() -> None:
    """The highest-severity tension surfaces as the load-bearing
    cross-domain pair — that's the boundary condition the synthesis
    actually adjudicated."""
    receipts = [_r("Walton 2019"), _r("Konopka 2019")]
    pairs = (
        Tension(
            receipt_a_id="Walton 2019", receipt_b_id="Konopka 2019",
            kind="directionality_disagreement",
            outcome_class="muscle_function",
            summary="Walton vs Konopka on muscle/mitochondrial endpoints",
            severity=4,
        ),
    )
    md = build_what_this_adds_section(
        receipts, _matrix(receipts, pairs), _thesis(),
        topic="metformin",
    )
    assert "load-bearing" in md.lower()
    assert "Walton 2019" in md and "Konopka 2019" in md
    assert "directionality disagreement" in md or (
        "directionality_disagreement" in md
    )


def test_section_keeps_prior_review_comparison_citation_free() -> None:
    """The prior-review comparison is framing, not source-bound
    evidence; keep named citations out of this sentence so the public
    consistency audit has a single source of truth for claims."""
    receipts = [
        _r("Walton 2019", tier="A1", directness="direct"),
        _r("Mohammed 2021", tier="B1", directness="review"),
        _r("Keys 2025", tier="B1", directness="review"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="metformin",
    )
    assert "Prior reviews" in md
    assert "Mohammed 2021" not in md
    assert "Keys 2025" not in md


def test_section_uses_fallback_framing_when_no_reviews() -> None:
    """Corpus without B1 receipts → falls back to non-comparative
    'this synthesis adds' phrasing rather than a misleading
    'prior reviews' claim with no anchor."""
    receipts = [
        _r("Walton 2019", tier="A1"),
        _r("Konopka 2019", tier="A1"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="metformin",
    )
    assert "Prior reviews" not in md
    assert "This synthesis adds" in md


def test_section_handles_empty_matrix_gracefully() -> None:
    """Defensive: matrix=None → section skips the load-bearing
    tension SENTENCE, never crashes. Note 'load-bearing' may still
    appear in the trailing 'evidence-weighting' description; we
    check for the specific tension phrasing."""
    md = build_what_this_adds_section(
        [_r("Walton 2019")], None, _thesis(), topic="metformin",
    )
    assert "## What This Synthesis Adds" in md
    assert "load-bearing cross-domain tension" not in md.lower()


def test_section_returns_str_not_synthesis_section() -> None:
    """Returns raw markdown so the orchestrator can splice between
    Conclusion and Tables without polluting SectionName Literal."""
    out = build_what_this_adds_section(
        [_r("Walton 2019")], _matrix([_r("Walton 2019")]), _thesis(),
        topic="metformin",
    )
    assert isinstance(out, str)
    assert out.endswith("\n")


def test_section_filters_to_accepted_receipts_only() -> None:
    """Rejected receipts MUST NOT contribute to the corpus count
    or appear in the named-reviews list — they're quarantined
    everywhere else in the trust spine."""
    receipts = [
        _r("Walton 2019", spar_verdict="accept_clean"),
        _r("Rejected 2020",
           spar_verdict="reject_majority", tier="B1"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="metformin",
    )
    assert "1 eligible source" in md
    assert "Rejected 2020" not in md


def test_section_keeps_research_contribution_compact() -> None:
    receipts = [
        _r("Direct 2024", outcome="cardiometabolic", directness="direct"),
        _r("Indirect 2023", outcome="cognitive", directness="indirect",
           tier="B2"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="metformin",
    )
    body = md.split("\n", 1)[1]
    assert "### Boundary-Condition Matrix" not in md
    assert "### Evidence-Gap Priority" not in md
    assert "### Next-Study Design Recommendation" not in md
    assert len(body.split()) <= 220


def test_section_uses_design_weighting_not_risk_rollup_language() -> None:
    md = build_what_this_adds_section(
        [_r("Direct 2024", tier="A1")],
        _matrix([_r("Direct 2024", tier="A1")]),
        _thesis(),
        topic="rapamycin",
    )
    assert "design-level evidence weighting" in md
    assert "tension matrix" not in md.lower()
    assert "risk-of-bias roll-up" not in md
    assert "overall RoB" not in md


def test_section_has_no_public_audit_jargon_or_main_table_refs() -> None:
    md = build_what_this_adds_section(
        [_r("Direct 2024", tier="A1")],
        _matrix([_r("Direct 2024", tier="A1")]),
        _thesis(),
        topic="caloric restriction",
    )
    banned = (
        "trust-spine",
        "Selected thesis:",
        "Tournament selector",
        "Table 3",
        "Table 4",
        "Table 5",
        "risk-of-bias roll-up",
        "structured evidence-audit workflow",
    )
    for phrase in banned:
        assert phrase not in md
    assert "design-level evidence weighting" in md


def test_what_adds_keeps_outcome_labels_out_of_main_summary() -> None:
    receipts = [
        _r("Direct 2024", outcome="muscle_function", directness="direct"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="urolithin A",
    )
    assert "outcome class" in md
    assert "muscle_function" not in md


def test_what_adds_does_not_inline_next_study_design_table() -> None:
    receipts = [
        _r("Direct Cardio", outcome="cardiometabolic", directness="direct"),
        _r("Indirect Frailty", outcome="frailty", directness="indirect",
           tier="B2"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="caloric restriction",
    )
    assert "Next-Study Design Recommendation" not in md
    assert "pre-register the primary endpoint" not in md
    assert len(md.split()) <= 220
