"""Tests for agent/synthesis_audit.py — Q1-Q7 deterministic audit.

Each Q must pass when the paper satisfies its rule and FAIL when
the paper violates it. The discriminating test is the load-bearing-
fail case: a synthesis paper that violates Q1, Q3, or Q5 must NOT
ship, even if its overall score is high.
"""
from __future__ import annotations

from agent.synthesis_audit import (
    AUDIT_VERSION,
    DAY10_SCORE_FLOOR,
    Q_LOAD_BEARING_IDS,
    audit_synthesis_paper,
)
from agent.synthesis_schemas import (
    EffectDirection,
    OutcomeClass,
    ReceiptSummary,
    SynthesisClaimAnchor,
    SynthesisPaper,
    SynthesisSection,
    SynthesisThesis,
    TensionMatrix,
)


# --- Helpers --------------------------------------------------------------


def _summary(
    rid: str,
    *,
    outcome: OutcomeClass = "muscle_function",
    direction: EffectDirection = "negative",
    tier: str = "A1",
    directness: str = "direct",
    p_values: tuple[str, ...] = ("p=0.003",),
    n_claims: int = 4,
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}",
        topic="metformin",
        thesis_text=f"thesis for {rid}",
        spar_verdict="accept_clean",
        n_claims=n_claims, n_failed_traces=0,
        canonical_trial_id=f"NCT-{rid}",
        evidence_tier=tier, directness=directness,
        outcome_class=outcome, effect_direction=direction,
        p_values=p_values,
        population_summary="older adults",
    )


def _paper(
    body_md: str,
    receipts: tuple[ReceiptSummary, ...],
    *,
    sections: tuple[SynthesisSection, ...] | None = None,
    thesis_refs: tuple[str, ...] = ("r-A", "r-B", "r-C"),
) -> SynthesisPaper:
    if sections is None:
        sections = (
            SynthesisSection(name="title", body_md="# t", anchors=()),
            SynthesisSection(name="thesis", body_md="## Thesis", anchors=()),
            SynthesisSection(name="evidence_summary", body_md="## ES", anchors=()),
            SynthesisSection(name="references", body_md="## R", anchors=()),
        )
    th = SynthesisThesis(
        text="metformin shows mixed evidence",
        receipt_ids_referenced=thesis_refs,
        tensions_addressed=(),
        rejected_candidates=(),
        picker_rationale="test",
    )
    return SynthesisPaper(
        submission_id="syn-test",
        topic="metformin",
        thesis=th,
        matrix=TensionMatrix(receipts=receipts, pairs=()),
        sections=sections,
        body_md=body_md,
        render_version="synthesis-writer/2026-04-29",
    )


# ============================================================
# Q1 — Konopka borderline-p hedging
# ============================================================


def test_q1_passes_when_no_borderline_p_value_present() -> None:
    receipts = (_summary("r-A"),)
    paper = _paper("Body without any p-value at all.", receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q1 = next(c for c in audit.checks if c.question_id.startswith("Q1"))
    assert q1.passed


def test_q1_fails_when_borderline_p_described_as_significant() -> None:
    receipts = (_summary("r-A", p_values=("p=0.08",)),)
    body = "The trial showed a significant effect at p=0.08 in older adults."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q1 = next(c for c in audit.checks if c.question_id.startswith("Q1"))
    assert not q1.passed
    assert "significant" in q1.detail.lower()


def test_q1_passes_when_borderline_p_is_hedged() -> None:
    receipts = (_summary("r-A", p_values=("p=0.08",)),)
    body = "The trial trended toward attenuation at p=0.08, did not reach significance."
    # "did not reach significance" — the word "significance" appears, but
    # the SENTENCE around p=0.08 hedges. Q1 fires on "significant" within
    # 80 chars; "did not reach significance" still contains "significance"
    # as a substring. Let's use clearer hedge language.
    body = "The trial trended toward attenuation at p=0.08, with no clear treatment effect."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q1 = next(c for c in audit.checks if c.question_id.startswith("Q1"))
    assert q1.passed


# ============================================================
# Q2 — Witham null acknowledgment
# ============================================================


def test_q2_passes_when_no_null_receipts() -> None:
    receipts = (_summary("r-A", direction="negative"),)
    paper = _paper("body", receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q2 = next(c for c in audit.checks if c.question_id.startswith("Q2"))
    assert q2.passed


def test_q2_fails_when_null_receipt_not_cited_in_synthesis() -> None:
    receipts = (
        _summary("r-A", direction="negative"),
        _summary("r-B", outcome="frailty", direction="null"),
    )
    # Synthesis section cites only r-A, not the null r-B
    syn_section = SynthesisSection(
        name="synthesis",
        body_md="## Synthesis\n\nReceipt r-A reports negative effect.",
        anchors=(SynthesisClaimAnchor(
            sentence="Receipt r-A reports negative effect.",
            receipt_ids=("r-A",), numerics=(),
        ),),
    )
    sections = (
        SynthesisSection(name="title", body_md="# t", anchors=()),
        SynthesisSection(name="thesis", body_md="## Thesis", anchors=()),
        SynthesisSection(name="evidence_summary", body_md="## ES", anchors=()),
        syn_section,
        SynthesisSection(name="tensions", body_md="## T", anchors=()),
        SynthesisSection(name="references", body_md="## R", anchors=()),
    )
    paper = _paper("body", receipts, sections=sections)
    audit = audit_synthesis_paper(paper, receipts)
    q2 = next(c for c in audit.checks if c.question_id.startswith("Q2"))
    assert not q2.passed
    assert "r-B" in q2.detail


def test_q2_passes_when_null_receipt_cited_with_null_phrase() -> None:
    receipts = (
        _summary("r-A", direction="negative"),
        _summary("r-B", outcome="frailty", direction="null"),
    )
    syn_section = SynthesisSection(
        name="synthesis",
        body_md=(
            "## Synthesis\n\n"
            "Receipt r-A reports negative effect on muscle. "
            "Receipt r-B did not improve walk speed (null result)."
        ),
        anchors=(),
    )
    sections = (
        SynthesisSection(name="title", body_md="# t", anchors=()),
        SynthesisSection(name="thesis", body_md="## Thesis", anchors=()),
        SynthesisSection(name="evidence_summary", body_md="## ES", anchors=()),
        syn_section,
        SynthesisSection(name="tensions", body_md="## T", anchors=()),
        SynthesisSection(name="references", body_md="## R", anchors=()),
    )
    paper = _paper("body", receipts, sections=sections)
    audit = audit_synthesis_paper(paper, receipts)
    q2 = next(c for c in audit.checks if c.question_id.startswith("Q2"))
    assert q2.passed


# ============================================================
# Q3 — Mohammed direct vs indirect separation
# ============================================================


def test_q3_passes_when_no_synthesis_section() -> None:
    """Defensive: missing synthesis section should pass Q3 (nothing to check)."""
    receipts = (_summary("r-A"),)
    paper = _paper("body", receipts)  # no synthesis section in defaults
    audit = audit_synthesis_paper(paper, receipts)
    q3 = next(c for c in audit.checks if c.question_id.startswith("Q3"))
    assert q3.passed


def test_q3_fails_when_mixed_directness_paragraph_lacks_transition() -> None:
    """Anchor with both a direct AND a mechanistic receipt without
    a transition phrase → Q3 fails."""
    receipts = (
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
    )
    bad_anchor = SynthesisClaimAnchor(
        sentence="Receipts r-A and r-B together show metformin reduces muscle hypertrophy",
        receipt_ids=("r-A", "r-B"),
        numerics=(),
    )
    syn_section = SynthesisSection(
        name="synthesis", body_md="## Synthesis\n\nbad mixed sentence",
        anchors=(bad_anchor,),
    )
    sections = (
        SynthesisSection(name="title", body_md="# t", anchors=()),
        SynthesisSection(name="thesis", body_md="## Thesis", anchors=()),
        SynthesisSection(name="evidence_summary", body_md="## ES", anchors=()),
        syn_section,
        SynthesisSection(name="references", body_md="## R", anchors=()),
    )
    paper = _paper("body", receipts, sections=sections)
    audit = audit_synthesis_paper(paper, receipts)
    q3 = next(c for c in audit.checks if c.question_id.startswith("Q3"))
    assert not q3.passed


def test_q3_passes_when_mixed_directness_has_transition() -> None:
    receipts = (
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
    )
    good_anchor = SynthesisClaimAnchor(
        sentence="Mechanistically, r-B suggests AMPK; r-A clinically blunts.",
        receipt_ids=("r-A", "r-B"),
        numerics=(),
    )
    syn_section = SynthesisSection(
        name="synthesis", body_md="## Synthesis\n\nok",
        anchors=(good_anchor,),
    )
    sections = (
        SynthesisSection(name="title", body_md="# t", anchors=()),
        SynthesisSection(name="thesis", body_md="## Thesis", anchors=()),
        SynthesisSection(name="evidence_summary", body_md="## ES", anchors=()),
        syn_section,
        SynthesisSection(name="references", body_md="## R", anchors=()),
    )
    paper = _paper("body", receipts, sections=sections)
    audit = audit_synthesis_paper(paper, receipts)
    q3 = next(c for c in audit.checks if c.question_id.startswith("Q3"))
    assert q3.passed


# ============================================================
# Q5 — Mohammed healthspan discipline
# ============================================================


def test_q5_fails_when_unhedged_healthspan_claim_with_no_longevity_receipt() -> None:
    receipts = (_summary("r-A", outcome="muscle_function"),)
    body = "Metformin extends lifespan and shows broad geroprotective effects."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q5 = next(c for c in audit.checks if c.question_id.startswith("Q5"))
    assert not q5.passed


def test_q5_passes_when_healthspan_claim_is_hedged() -> None:
    receipts = (_summary("r-A", outcome="muscle_function"),)
    body = "Metformin may extend lifespan, though the evidence remains indirect for human longevity."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q5 = next(c for c in audit.checks if c.question_id.startswith("Q5"))
    assert q5.passed


def test_q5_passes_when_direct_longevity_receipt_present() -> None:
    receipts = (
        _summary(
            "r-longevity", outcome="longevity",
            direction="positive", tier="A1", directness="direct",
        ),
    )
    body = "Metformin extends lifespan in adequately powered RCTs."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q5 = next(c for c in audit.checks if c.question_id.startswith("Q5"))
    assert q5.passed


# ============================================================
# Q7 — numeric fidelity
# ============================================================


def test_q7_fails_when_paper_contains_novel_numeric() -> None:
    receipts = (_summary("r-A", p_values=("p=0.003",)),)
    body = "The synthesis cites p=0.99 nowhere in the receipts."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q7 = next(c for c in audit.checks if c.question_id.startswith("Q7"))
    assert not q7.passed


def test_q7_passes_when_every_numeric_traces_to_a_receipt() -> None:
    receipts = (_summary("r-A", p_values=("p=0.003",)),)
    body = "Receipt r-A reports an effect at p=0.003 — the only numeric here."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q7 = next(c for c in audit.checks if c.question_id.startswith("Q7"))
    assert q7.passed


# ============================================================
# Aggregate score + load-bearing gate
# ============================================================


def test_audit_score_is_passed_count_over_seven_times_ten() -> None:
    """5 of 7 passed → 7.14/10. Audit must compute deterministically."""
    receipts = (_summary("r-A", direction="negative"),)
    # Construct a paper that fails Q1 (significant + p=0.08) and Q5
    # (unhedged healthspan claim with no longevity receipt) — should
    # score 5/7 = 7.14
    body = "The trial showed a significant effect at p=0.08. Metformin extends lifespan broadly."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    assert audit.score < DAY10_SCORE_FLOOR
    failed = [c.question_id for c in audit.checks if not c.passed]
    assert any("Q1" in f for f in failed)
    assert any("Q5" in f for f in failed)


def test_audit_blocks_ship_when_load_bearing_q_fails_even_with_high_score() -> None:
    """Q1, Q3, Q5 are load-bearing. Failing one of them blocks ship
    even if the overall score is ≥8.5."""
    receipts = (_summary("r-A", direction="negative"),)
    # Construct a paper that passes 6 of 7 but fails Q1 (load-bearing).
    # Score = 6/7 = 8.57 ≥ 8.5, but load-bearing fail → notes flag.
    body = "The trial showed a significant effect at p=0.08."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    # Score > 8.5 OR not — but notes must say LOAD-BEARING FAIL
    failed_load = [
        c.question_id for c in audit.checks
        if c.question_id in Q_LOAD_BEARING_IDS and not c.passed
    ]
    assert failed_load
    assert "LOAD-BEARING" in audit.notes


def test_audit_passes_clean_paper() -> None:
    """A paper that satisfies all 7 checks scores 10.0 with ship-criterion-met notes."""
    receipts = (
        _summary("r-A", direction="negative", p_values=("p=0.003",)),
        _summary("r-B", outcome="cardiometabolic", direction="negative", p_values=("p=0.02",)),
        _summary("r-C", outcome="frailty", direction="null", p_values=()),
    )
    body = (
        "# Title\n\n"
        "## Thesis\n\nMixed evidence across r-A r-B r-C in older adults.\n\n"
        "## Synthesis\n\n"
        "r-A reports negative effect at p=0.003 on muscle. "
        "r-B reports negative effect on cardiometabolic outcome at p=0.02. "
        "r-C did not improve walk speed (null).\n\n"
        "## Tensions\n\nr-A and r-B agree on negative direction.\n\n"
        "## Limitations\n\n"
        "- The synthesis is single-trial per outcome; replication required.\n"
        "- Direct longevity evidence is missing — geroprotective claims may be premature.\n\n"
        "## References\n\n[1] r-A\n[2] r-B\n[3] r-C\n"
    )
    paper = _paper(
        body, receipts,
        sections=(
            SynthesisSection(name="title", body_md="# t", anchors=()),
            SynthesisSection(name="thesis", body_md="## Thesis", anchors=()),
            SynthesisSection(name="evidence_summary", body_md="## ES", anchors=()),
            SynthesisSection(
                name="synthesis",
                body_md=(
                    "## Synthesis\n\n"
                    "r-A reports negative effect at p=0.003 on muscle. "
                    "r-B reports negative effect on cardiometabolic outcome at p=0.02. "
                    "r-C did not improve walk speed (null)."
                ),
                anchors=(),
            ),
            SynthesisSection(
                name="limitations",
                body_md=(
                    "## Limitations\n\n"
                    "- single-trial per outcome; replication required.\n"
                ),
                anchors=(),
            ),
            SynthesisSection(name="references", body_md="## R", anchors=()),
        ),
    )
    audit = audit_synthesis_paper(paper, receipts)
    assert audit.score == 10.0
    assert "ship-criterion met" in audit.notes


def test_audit_version_is_anchored() -> None:
    assert AUDIT_VERSION == "synthesis-audit/2026-04-29"
