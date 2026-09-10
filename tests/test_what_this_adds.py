"""Fix #25 — `## What This Synthesis Adds` deterministic section.

Trust spine: the originality claim is grounded in pipeline data
(receipts + matrix + thesis), not LLM rhetoric. These tests pin the
template behaviour."""
from __future__ import annotations

from agent.paper_writer_deterministic import (
    _outcome_rows,
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
    """The opening sentence must report N receipts and N outcome
    classes — the corpus characterisation that grounds originality."""
    receipts = [
        _r("Walton 2019", outcome="muscle_function"),
        _r("Witham 2025", outcome="frailty"),
        _r("Konopka 2019", outcome="cardiometabolic"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="metformin",
    )
    assert "3 included sources" in md
    assert "3 outcome classes" in md
    assert "metformin" in md


def test_section_uses_reader_safe_dense_tension_wording() -> None:
    receipts = [
        _r(f"Source {i} 2026", outcome="cardiometabolic")
        for i in range(67)
    ]
    pairs = tuple(
        Tension(
            receipt_a_id=receipts[i % len(receipts)].receipt_id,
            receipt_b_id=receipts[(i + 1) % len(receipts)].receipt_id,
            kind="disagreement",
            outcome_class="cardiometabolic",
            summary="dense disagreement map",
            severity=2,
        )
        for i in range(727)
    )

    md = build_what_this_adds_section(
        receipts, _matrix(receipts, pairs), _thesis(), topic="taurine",
    )

    assert "727 cross-study disagreement" not in md
    assert "high-density pairwise disagreement map" in md


def test_section_quotes_picked_thesis_verbatim() -> None:
    """The selected thesis remains visible without internal selector labels."""
    thesis_text = (
        "Metformin's longevity signal coexists with an "
        "exercise-adaptation penalty in older-adult RCTs."
    )
    md = build_what_this_adds_section(
        [_r("Walton 2019")], _matrix([_r("Walton 2019")]),
        _thesis(thesis_text), topic="metformin",
    )
    assert thesis_text in md
    assert "Picked thesis" not in md
    assert "Tournament selector" not in md


def test_section_highlights_load_bearing_tension() -> None:
    """The highest-severity tension surfaces as the load-bearing
    cross-domain pair — that's the boundary condition the synthesis
    actually adjudicated."""
    receipts = [_r("Walton 2019"), _r("Konopka 2019")]
    pairs = (
        Tension(
            receipt_a_id="Walton 2019", receipt_b_id="Konopka 2019",
            kind="disagreement",
            outcome_class="muscle_function",
            summary="Walton vs Konopka on muscle/mitochondrial endpoints",
            severity=4,
        ),
    )
    md = build_what_this_adds_section(
        receipts, _matrix(receipts, pairs), _thesis(),
        topic="metformin",
    )
    assert "strongest unresolved contrast" in md.lower()
    assert "Walton 2019" in md and "Konopka 2019" in md
    assert "disagreement" in md


def test_section_names_b1_review_citations_when_present() -> None:
    """The 'beyond prior reviews' framing names the B1 systematic
    reviews actually in the corpus — concrete originality, not
    abstract claim."""
    receipts = [
        _r("Walton 2019", tier="A1", directness="direct"),
        _r("Mohammed 2021", tier="B1", directness="review"),
        _r("Keys 2025", tier="B1", directness="review"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="metformin",
    )
    assert "Mohammed 2021" in md
    assert "Keys 2025" in md
    assert "Prior reviews" in md


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
    assert "This synthesis adds a design-level evidence-weighting" in md


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
    assert "1 included source" in md
    assert "Rejected 2020" not in md


def test_section_includes_research_contribution_layer() -> None:
    receipts = [
        _r("Direct 2024", outcome="cardiometabolic", directness="direct"),
        _r("Indirect 2023", outcome="cognitive", directness="indirect",
           tier="B2"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="metformin",
    )
    assert "### Boundary-Condition Matrix" in md
    assert "source counts are cumulative within each outcome class" in md
    assert "reconcile to the Results outcome-class roster" in md
    assert "### Evidence-Gap Priority" not in md
    assert "### Next-Study Design Recommendation" not in md
    assert "| cognitive | 0 | 1 |" in md
    assert "no direct source in this retained set" in md
    assert "participants per arm" not in md
    assert "priority population" not in md
    assert "at least 12 months" not in md


def test_research_contribution_layer_humanizes_public_labels() -> None:
    receipts = [
        _r("Direct 2024", outcome="muscle_function", directness="direct"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="urolithin A",
    )
    assert "muscle function" in md
    assert "muscle_function" not in md


def test_boundary_matrix_merges_canonical_outcome_aliases() -> None:
    receipts = [
        _r("Direct 2024", outcome="immune", directness="direct"),
        _r("Indirect 2023", outcome="immune_inflammation", directness="indirect"),
    ]
    md = build_what_this_adds_section(
        receipts, _matrix(receipts), _thesis(), topic="urolithin A",
    )
    assert md.count("| immune and inflammation |") == 1
    assert "| immune and inflammation | 1 | 1 |" in md
    rows = _outcome_rows(receipts, _matrix(receipts))
    assert rows[0][:3] == ("immune_inflammation", 1, 1)


def test_source_counts_do_not_assign_research_priority_or_trial_design() -> None:
    receipts = [
        _r("Direct Cardio", outcome="cardiometabolic", directness="direct"),
        _r("Indirect Frailty", outcome="frailty", directness="indirect",
           tier="B2"),
    ]
    for added in ([], [_r(f"Extra {i}", outcome="frailty") for i in range(8)]):
        current = receipts + added
        md = build_what_this_adds_section(current, _matrix(current), _thesis(), topic="caloric restriction")
        assert f"| frailty | {len(added)} | 1 |" in md
        assert "target the **frailty** evidence gap" not in md
        assert "Next-Study Design Recommendation" not in md
        assert "participants per arm" not in md
        assert "They do not establish literature coverage, evidence certainty, research priorities" in md
        assert md.index("| cardiometabolic |") < md.index("| frailty |")


def test_boundary_matrix_counts_protocols_without_treating_them_as_findings() -> None:
    receipts = [
        _r("Protocol 2025", outcome="cardiometabolic", directness="protocol", tier="D1", direction="positive"),
        _r("Second protocol", outcome="frailty", directness="protocol", tier="D1", direction="positive"),
        _r("Completed trial", outcome="frailty", direction="null"),
    ]
    md = build_what_this_adds_section(receipts, _matrix(receipts), _thesis(), topic="resistance training")
    assert "Indirect / mechanism / protocol sources" in md
    assert "| cardiometabolic | 0 | 1 | not applicable | protocol records; no completed findings |" in md
    assert "| frailty | 1 | 1 | null |" in md
    assert "positive" not in md
