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
    """A paper that satisfies all 7 checks scores 10.0 with ship-criterion-met notes.

    Day 10.10: clean paper now requires mixed-directness corpus + a
    mixed-directness synthesis paragraph with a transition phrase, so
    Q3 (load-bearing) is applicable AND passes — load-bearing N/A is
    no longer accepted as a ship pass."""
    receipts = (
        _summary("r-A", direction="negative", p_values=("p=0.003",), directness="direct"),
        _summary("r-B", outcome="cardiometabolic", direction="negative", p_values=("p=0.02",), directness="direct"),
        _summary("r-C", outcome="frailty", direction="null", p_values=(), directness="mechanistic"),
    )
    body = (
        "# Title\n\n"
        "## Thesis\n\nMixed evidence across r-A r-B r-C in older adults.\n\n"
        "## Synthesis\n\n"
        "r-A reports negative effect at p=0.003 on muscle. "
        "Mechanistically, r-A and r-C both implicate AMPK pathway involvement "
        "in muscle outcomes. "
        "r-C did not improve walk speed (null).\n\n"
        "## Tensions\n\nr-A and r-B agree on negative direction.\n\n"
        "## Limitations\n\n"
        "- The synthesis is single-trial per outcome; replication required.\n"
        "- Direct longevity evidence is missing — geroprotective claims may be premature.\n\n"
        "## References\n\n[1] r-A\n[2] r-B\n[3] r-C\n"
    )
    # Synthesis section anchors include a mixed-directness sentence
    # ("Mechanistically, r-A and r-C..." cites direct + mechanistic
    # with the required transition phrase).
    synthesis_anchors = (
        SynthesisClaimAnchor(
            sentence="r-A reports negative effect at p=0.003 on muscle.",
            receipt_ids=("r-A",), numerics=("p=0.003",),
        ),
        SynthesisClaimAnchor(
            sentence="Mechanistically, r-A and r-C both implicate AMPK pathway involvement in muscle outcomes.",
            receipt_ids=("r-A", "r-C"), numerics=(),
        ),
        SynthesisClaimAnchor(
            sentence="r-C did not improve walk speed (null).",
            receipt_ids=("r-C",), numerics=(),
        ),
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
                    "Mechanistically, r-A and r-C both implicate AMPK pathway "
                    "involvement in muscle outcomes. "
                    "r-C did not improve walk speed (null)."
                ),
                anchors=synthesis_anchors,
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
    assert audit.score == 10.0, audit.notes
    assert "ship-criterion met" in audit.notes


def test_audit_version_is_anchored() -> None:
    """Day 10.7 bumped after the reviewer-P1/P2 fix (dedup, Q4 unique
    trials, N/A handling)."""
    assert AUDIT_VERSION == "synthesis-audit/2026-04-29-day10-10"


# ============================================================
# Day 10.7 — reviewer P1/P2 fixes
# ============================================================


def test_q2_marked_not_applicable_when_no_null_receipts() -> None:
    """Reviewer P2: vacuous passes (no null receipts to check) must
    not inflate the score. Q2 returns applicable=False instead of
    pretending the corpus passed."""
    receipts = (_summary("r-A", direction="negative"),)
    paper = _paper("body", receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q2 = next(c for c in audit.checks if c.question_id.startswith("Q2"))
    assert q2.passed is True  # nothing to fail
    assert q2.applicable is False
    assert "N/A" in q2.detail


def test_q4_fails_for_single_trial_corpus_without_replication_phrase() -> None:
    """Reviewer P1: 12 receipts from the same trial must not pass Q4
    as "rich". Q4 now counts UNIQUE trials, not raw receipt count."""
    same_trial = "NCT02308228"
    receipts = tuple(
        ReceiptSummary(
            receipt_id=f"r-{i}", receipt_path="x", topic="metformin",
            thesis_text="muscle thesis", spar_verdict="accept_clean",
            n_claims=4, n_failed_traces=0,
            canonical_trial_id=same_trial, evidence_tier="A1",
            directness="direct", outcome_class="muscle_function",
            effect_direction="negative", p_values=("p=0.003",),
            population_summary="",
        )
        for i in range(12)
    )
    # Thesis references all 12 receipts but they're all the same trial.
    # Limitations section has NO replication phrase → Q4 must fail.
    paper = _paper(
        "body without replication phrase",
        receipts,
        thesis_refs=tuple(r.receipt_id for r in receipts),
    )
    audit = audit_synthesis_paper(paper, receipts)
    q4 = next(c for c in audit.checks if c.question_id.startswith("Q4"))
    assert not q4.passed
    assert "1 unique trial" in q4.detail.lower() or "1 unique" in q4.detail.lower()


def test_q4_passes_when_three_unique_trials_referenced() -> None:
    """Three distinct trials → cross-trial synthesis → Q4 doesn't
    require a replication phrase."""
    receipts = tuple(
        _summary(f"r-{trial}", p_values=("p=0.003",))
        for trial in ("trial-A", "trial-B", "trial-C")
    )
    receipts = tuple(
        ReceiptSummary(
            receipt_id=r.receipt_id, receipt_path="x", topic="metformin",
            thesis_text=r.thesis_text, spar_verdict=r.spar_verdict,
            n_claims=r.n_claims, n_failed_traces=0,
            canonical_trial_id=f"NCT-{r.receipt_id}",
            evidence_tier="A1", directness="direct",
            outcome_class="muscle_function", effect_direction="negative",
            p_values=("p=0.003",), population_summary="",
        )
        for r in receipts
    )
    paper = _paper(
        "body", receipts,
        thesis_refs=tuple(r.receipt_id for r in receipts),
    )
    audit = audit_synthesis_paper(paper, receipts)
    q4 = next(c for c in audit.checks if c.question_id.startswith("Q4"))
    assert q4.passed
    assert "3 unique trials" in q4.detail or "cross-trial" in q4.detail


def test_score_excludes_n_a_checks() -> None:
    """Reviewer P2: applicable-only score formula. Don't divide by 7
    when 3 of the 7 checks are N/A — that vacuously inflates the
    score."""
    # Single negative receipt — no nulls (Q2 N/A), no safety (Q6 N/A),
    # no synthesis section in defaults (Q3 N/A). Q1/Q4/Q5/Q7 applicable.
    receipts = (_summary("r-A", direction="negative", p_values=("p=0.003",)),)
    body = "Receipt r-A reports negative effect at p=0.003."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    applicable = [c for c in audit.checks if c.applicable]
    assert len(applicable) < 7  # some checks are N/A
    passed_applicable = sum(1 for c in applicable if c.passed)
    expected_score = passed_applicable / len(applicable) * 10
    assert audit.score == round(expected_score, 2)


def test_insufficient_coverage_blocks_ship_even_at_high_score() -> None:
    """Reviewer P2: with applicable_count < MIN_APPLICABLE_CHECKS,
    the audit notes flag insufficient coverage so it doesn't ship as
    a high score from a narrow corpus."""
    # Tiny corpus that only triggers a few applicable checks.
    receipts = (_summary("r-A", direction="negative"),)
    body = "Receipt r-A reports negative effect at p=0.003."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    applicable_count = sum(1 for c in audit.checks if c.applicable)
    if applicable_count < 4:
        assert "INSUFFICIENT COVERAGE" in audit.notes
        assert "ship-criterion met" not in audit.notes


# ============================================================
# Q8 — rejected-evidence leakage (Day 10.17 — load-bearing)
# ============================================================
# Found empirically in 10.17a verification: the Background section of
# the rendered paper cited cfab-c02, the SPAR-rejected frailty receipt.
# Day 10.10 trust-spine ordering says rejected receipts may only
# appear in their dedicated "Rejected / Contested Evidence" section
# (and the deterministic Methods + References blocks that describe
# the rejection). Anywhere else = trust-spine violation. Q8 is
# load-bearing — leaking rejected evidence into headline prose
# undermines the SPAR gate's whole purpose.


def _rejected(rid: str) -> ReceiptSummary:
    """Helper: build a SPAR-rejected receipt for Q8 tests."""
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text=f"thesis for {rid}",
        spar_verdict="reject_majority",
        n_claims=1, n_failed_traces=0, canonical_trial_id=None,
        evidence_tier="A1", directness="direct",
        outcome_class="frailty", effect_direction="null",
        p_values=("p=0.96",), population_summary="older adults",
    )


def test_q8_passes_when_no_rejected_receipts() -> None:
    """No rejected receipts in corpus → Q8 has nothing to check (N/A)."""
    receipts = (_summary("r-A"),)
    paper = _paper("body without any rejected ID", receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q8 = next(c for c in audit.checks if c.question_id.startswith("Q8"))
    assert q8.applicable is False
    assert q8.passed is True


def test_q8_fails_when_rejected_id_appears_in_background_prose() -> None:
    """Rejected receipt cited outside the quarantine section → fail."""
    receipts = (_summary("r-A"), _rejected("r-rej-X"))
    body = (
        "## Background\n\nMetformin trials covered diverse outcomes; "
        "for example, r-rej-X investigated walk speed.\n\n"
        "## Rejected / Contested Evidence\n\nr-rej-X was rejected.\n"
    )
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q8 = next(c for c in audit.checks if c.question_id.startswith("Q8"))
    assert q8.applicable is True
    assert q8.passed is False, q8.detail
    assert "r-rej-X" in q8.detail


def test_q8_passes_when_rejected_id_only_in_quarantine_section() -> None:
    """Rejected receipt cited ONLY in Rejected/Contested Evidence,
    Methods (which describes SPAR), or References → pass."""
    receipts = (_summary("r-A"), _rejected("r-rej-X"))
    body = (
        "## Background\n\nGeneral metformin background prose.\n\n"
        "## Rejected / Contested Evidence\n\n"
        "r-rej-X was rejected by SPAR for over-generalization.\n\n"
        "## References\n\n[5] r-rej-X (QUARANTINED)\n"
    )
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q8 = next(c for c in audit.checks if c.question_id.startswith("Q8"))
    assert q8.passed is True, q8.detail


def test_q8_is_load_bearing() -> None:
    assert "Q8-quarantine-leakage" in Q_LOAD_BEARING_IDS


# ============================================================
# Q9 — receipt-ID format validity (Day 10.17)
# ============================================================
# Found empirically in 10.17a verification: line 341 of full_paper.md
# cited `cfab-01` and `cfab-04` instead of `cfab-c01` and `cfab-c04`.
# The LLM dropped the `c` prefix in inline prose. The audit's existing
# anchor validator only checks the `_Cited:` markers below each
# paragraph; it doesn't scan inline citations within prose. Q9 closes
# this hole by extracting every receipt-id-shaped token from the body
# and verifying it matches a real receipt_id from the corpus.


def test_q9_passes_when_all_inline_ids_match_corpus() -> None:
    """Realistic-shape receipt IDs (4+ hyphens). Both cited tokens
    match the corpus → pass."""
    receipts = (
        _summary("metformin-multi-001-cfab-c01"),
        _summary("metformin-multi-001-cfab-c02"),
    )
    body = (
        "Background prose citing metformin-multi-001-cfab-c01 and "
        "metformin-multi-001-cfab-c02 only."
    )
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q9 = next(c for c in audit.checks if c.question_id.startswith("Q9"))
    assert q9.passed is True, q9.detail


def test_q9_fails_on_malformed_receipt_id_in_inline_prose() -> None:
    """Empirical bug: `cfab-01` (missing the `c`) appears in line 341
    of the 10.17a full paper. Real id is `cfab-c01`. Q9 must catch."""
    receipts = (
        _summary("metformin-multi-001-cfab-c01"),
        _summary("metformin-multi-001-cfab-c04"),
    )
    # Note "...cfab-01" / "...cfab-04" — missing the c prefix on the
    # last segment. Same overall hyphen count as valid IDs so Q9 cannot
    # discriminate by length alone — must check actual id match.
    body = (
        "Conversely, CT scans suggested metformin-multi-001-cfab-01 "
        "found suppression. Preclinical data from "
        "metformin-multi-001-cfab-04 showed extension."
    )
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q9 = next(c for c in audit.checks if c.question_id.startswith("Q9"))
    assert q9.passed is False, q9.detail
    assert (
        "metformin-multi-001-cfab-01" in q9.detail
        or "metformin-multi-001-cfab-04" in q9.detail
    )


def test_q9_ignores_receipt_id_lookalikes_that_are_not_in_token_form() -> None:
    """Q9 only checks tokens that look like our receipt-id format
    (slug-with-multiple-hyphens-and-cluster-suffix). Bare numbers,
    NCT IDs, ISRCTN IDs, and dates don't trigger."""
    receipts = (_summary("metformin-multi-001-cfab-c01"),)
    body = (
        "Trial NCT02308228 in 2023 enrolled p=0.005 patients per arm. "
        "Citing metformin-multi-001-cfab-c01 for the result."
    )
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q9 = next(c for c in audit.checks if c.question_id.startswith("Q9"))
    assert q9.passed is True, q9.detail


# ============================================================
# Q10 — claim-strength on tier-C / mechanistic evidence (load-bearing)
# ============================================================
# Found in three independent reviews of the 10.17a artifact: the
# rendered paper uses causal verbs ("improves", "drives", "demonstrates",
# "potent", "robust") on sentences that cite tier-C or mechanistic
# evidence — tier-C is preclinical / model organism, where the
# evidence is not strong enough for unhedged causal language. Q10
# fails when a sentence cites a tier-C or mechanistic receipt AND
# uses an unhedged causal verb.


def _mech_receipt(rid: str) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text=f"thesis for {rid}",
        spar_verdict="accept_clean",
        n_claims=1, n_failed_traces=0, canonical_trial_id=None,
        evidence_tier="C", directness="mechanistic",
        outcome_class="longevity", effect_direction="positive",
        p_values=(), population_summary="",
    )


def test_q10_passes_when_no_tier_c_receipts() -> None:
    """Corpus has only A1/direct receipts — Q10 has no tier-C to check."""
    receipts = (_summary("r-A"), _summary("r-B"))
    body = "Metformin improves muscle function via robust evidence."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q10 = next(c for c in audit.checks if c.question_id.startswith("Q10"))
    assert q10.applicable is False
    assert q10.passed is True


def test_q10_fails_when_tier_c_sentence_uses_unhedged_causal_verb() -> None:
    """Sentence cites a mechanistic receipt + uses 'demonstrates'
    without any hedge phrase → fail."""
    receipts = (
        _summary("metformin-multi-001-cfab-c01"),
        _mech_receipt("metformin-multi-001-cfab-c04"),
    )
    body = (
        "Metformin demonstrates a robust effect on longevity in "
        "model organisms (metformin-multi-001-cfab-c04)."
    )
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q10 = next(c for c in audit.checks if c.question_id.startswith("Q10"))
    assert q10.applicable is True
    assert q10.passed is False, q10.detail


def test_q10_passes_when_tier_c_sentence_includes_hedge() -> None:
    """Same causal verb as above, but sentence contains 'may' or
    'suggests' or 'consistent with' — passes."""
    receipts = (
        _summary("metformin-multi-001-cfab-c01"),
        _mech_receipt("metformin-multi-001-cfab-c04"),
    )
    body = (
        "Evidence suggests metformin may demonstrate effects on "
        "longevity in model organisms (metformin-multi-001-cfab-c04)."
    )
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q10 = next(c for c in audit.checks if c.question_id.startswith("Q10"))
    assert q10.passed is True, q10.detail


def test_q10_passes_when_unhedged_sentence_only_cites_direct_receipt() -> None:
    """Q10 only fires on sentences citing tier-C / mechanistic receipts.
    A direct A1 receipt with an unhedged causal verb is fine — that's
    what direct clinical evidence is for."""
    receipts = (_summary("r-A", directness="direct", tier="A1"),)
    body = "Metformin demonstrates a robust suppression effect (r-A)."
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q10 = next(c for c in audit.checks if c.question_id.startswith("Q10"))
    # No tier-C receipts in corpus → N/A.
    assert q10.applicable is False
    assert q10.passed is True


def test_q10_is_load_bearing() -> None:
    assert "Q10-claim-strength-discipline" in Q_LOAD_BEARING_IDS


def test_q10_ignores_cited_footer_markdown() -> None:
    """Day 10.17 Phase 1.5 false-positive: the writer emits a
    `_Cited: \\`receipt-id\\`, ..._` markdown footer below each
    anchored paragraph. That line contains receipt IDs but no prose,
    so Q10 must strip it before sentence-scanning — otherwise the
    sentence regex absorbs it into surrounding prose and false-fails
    when an unrelated paragraph happens to use a causal verb."""
    receipts = (
        _summary("metformin-multi-001-cfab-c01"),
        _mech_receipt("metformin-multi-001-cfab-c04"),
    )
    body = (
        "Metformin may demonstrate a hedged effect on longevity in "
        "model organisms (metformin-multi-001-cfab-c04).\n"
        "  _Cited: `metformin-multi-001-cfab-c04`, "
        "`metformin-multi-001-cfab-c01`_\n\n"
        "Unrelated next paragraph with no overclaim ends here."
    )
    paper = _paper(body, receipts)
    audit = audit_synthesis_paper(paper, receipts)
    q10 = next(c for c in audit.checks if c.question_id.startswith("Q10"))
    assert q10.passed is True, q10.detail
