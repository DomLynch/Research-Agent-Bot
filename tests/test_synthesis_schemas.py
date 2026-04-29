"""Tests for agent/synthesis_schemas.py — Day 10.1 contract.

Synthesis layer types must:
- be frozen + slots (same discipline as agent/schemas.py)
- have invariants that catch malformed graphs (unknown receipt anchors,
  non-canonical pair ordering, missing required sections)
- not allow LLM-fabricated receipt_ids to silently pass
"""
from __future__ import annotations

import dataclasses

import pytest

from agent.synthesis_schemas import (
    QualityCheckResult,
    ReceiptSummary,
    SynthesisClaimAnchor,
    SynthesisInvariantError,
    SynthesisPaper,
    SynthesisQualityAudit,
    SynthesisSection,
    SynthesisThesis,
    SynthesisThesisCandidate,
    Tension,
    TensionMatrix,
    assert_synthesis_invariants,
)


def _summary(rid: str = "r-A", outcome: str = "muscle_function") -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}",
        topic="metformin", thesis_text="t",
        spar_verdict="accept_clean", n_claims=4, n_failed_traces=0,
        canonical_trial_id="NCT02308228",
        evidence_tier="A1", directness="direct",
        outcome_class=outcome,  # type: ignore[arg-type]
        effect_direction="negative",  # treatment worsens muscle outcome
        p_values=("p=0.003",),
        population_summary="older adults, 65+",
    )


# --- Frozen + slots ------------------------------------------------------


def test_summary_is_frozen_slots() -> None:
    s = _summary()
    assert dataclasses.is_dataclass(s)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.topic = "rapamycin"  # type: ignore[misc]


def test_tension_pair_is_frozen() -> None:
    t = Tension(
        receipt_a_id="A", receipt_b_id="B",
        kind="agreement", outcome_class="muscle_function",
        summary="both blunt hypertrophy", severity=3,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.severity = 5  # type: ignore[misc]


# --- Invariants ----------------------------------------------------------


def _minimal_paper() -> SynthesisPaper:
    """Smallest structurally-valid SynthesisPaper for invariant tests."""
    s_a = _summary("r-A")
    s_b = _summary("r-B")
    matrix = TensionMatrix(
        receipts=(s_a, s_b),
        pairs=(
            Tension(
                receipt_a_id="r-A", receipt_b_id="r-B",
                kind="agreement", outcome_class="muscle_function",
                summary="both negative on muscle", severity=2,
            ),
        ),
    )
    thesis = SynthesisThesis(
        text="metformin blunts muscle outcomes (r-A, r-B)",
        receipt_ids_referenced=("r-A", "r-B"),
        tensions_addressed=("both negative on muscle",),
        rejected_candidates=(),
        picker_rationale="best candidate",
    )
    sections = (
        SynthesisSection(name="title", body_md="# title", anchors=()),
        SynthesisSection(
            name="thesis", body_md="thesis prose",
            anchors=(SynthesisClaimAnchor(
                sentence="x", receipt_ids=("r-A",), numerics=(),
            ),),
        ),
        SynthesisSection(name="evidence_summary", body_md="| ... |", anchors=()),
        SynthesisSection(name="references", body_md="[1] ...", anchors=()),
    )
    return SynthesisPaper(
        submission_id="syn-001",
        topic="metformin",
        thesis=thesis,
        matrix=matrix,
        sections=sections,
        body_md="...",
        render_version="synthesis-writer/2026-04-29",
    )


def test_assert_invariants_passes_minimal_paper() -> None:
    assert_synthesis_invariants(_minimal_paper())  # does not raise


def test_thesis_must_reference_at_least_one_receipt() -> None:
    paper = dataclasses.replace(
        _minimal_paper(),
        thesis=dataclasses.replace(
            _minimal_paper().thesis,
            receipt_ids_referenced=(),
        ),
    )
    with pytest.raises(SynthesisInvariantError, match="thesis must reference"):
        assert_synthesis_invariants(paper)


def test_anchor_referencing_unknown_receipt_rejects() -> None:
    """LLM-fabricated receipt_id in a sentence anchor must be caught.
    This is the synthesis-layer analogue of the receipt-layer's
    `_validate_flagged_against_graph` in spar.py."""
    base = _minimal_paper()
    bad_section = SynthesisSection(
        name="synthesis", body_md="...",
        anchors=(SynthesisClaimAnchor(
            sentence="x", receipt_ids=("r-NOT-IN-MATRIX",), numerics=(),
        ),),
    )
    paper = dataclasses.replace(
        base, sections=base.sections + (bad_section,),
    )
    with pytest.raises(SynthesisInvariantError, match="unknown.*receipt_id"):
        assert_synthesis_invariants(paper)


def test_tension_pair_must_be_canonically_ordered() -> None:
    """Pairs must satisfy a < b lexicographically — otherwise the
    matrix double-counts (r-A, r-B) and (r-B, r-A) as distinct."""
    base = _minimal_paper()
    bad_matrix = TensionMatrix(
        receipts=base.matrix.receipts,
        pairs=(
            Tension(
                receipt_a_id="r-B", receipt_b_id="r-A",  # B > A — violation
                kind="agreement", outcome_class="muscle_function",
                summary="x", severity=1,
            ),
        ),
    )
    paper = dataclasses.replace(base, matrix=bad_matrix)
    with pytest.raises(SynthesisInvariantError, match="canonically ordered"):
        assert_synthesis_invariants(paper)


def test_required_sections_must_be_present() -> None:
    base = _minimal_paper()
    # Drop the thesis section
    paper = dataclasses.replace(
        base,
        sections=tuple(s for s in base.sections if s.name != "thesis"),
    )
    with pytest.raises(SynthesisInvariantError, match="missing required sections"):
        assert_synthesis_invariants(paper)


# --- TensionMatrix ergonomics ---------------------------------------------


def test_non_orthogonal_filters_out_orthogonal_pairs() -> None:
    s_a = _summary("r-A", outcome="muscle_function")
    s_b = _summary("r-B", outcome="cognitive")  # different outcome
    matrix = TensionMatrix(
        receipts=(s_a, s_b),
        pairs=(
            Tension(
                receipt_a_id="r-A", receipt_b_id="r-B",
                kind="orthogonal", outcome_class="muscle_function",
                summary="muscle vs cognitive — no conflict", severity=0,
            ),
        ),
    )
    assert matrix.non_orthogonal() == ()


# --- QualityCheckResult / SynthesisQualityAudit shapes --------------------


def test_quality_audit_is_serializable() -> None:
    """Audit JSON must serialize cleanly via dataclasses.asdict — that's
    what gets written to synthesis_quality_audit.json."""
    audit = SynthesisQualityAudit(
        submission_id="syn-001",
        checks=(
            QualityCheckResult(
                question_id="Q1-konopka-p008-hedging",
                question="Does the paper round borderline p-values?",
                passed=True,
                detail="No 'significant' within 80 chars of p>=0.05",
            ),
        ),
        score=10.0,
        notes="all 7 evaluated",
    )
    d = dataclasses.asdict(audit)
    assert d["submission_id"] == "syn-001"
    assert d["checks"][0]["passed"] is True


# --- Thesis tournament structure ------------------------------------------


def test_thesis_candidate_carries_validation_metadata() -> None:
    """The candidate dataclass surfaces enough fields for the picker to
    rank without re-running the LLM — receipts_referenced, tensions
    addressed, word count are all the picker needs."""
    cand = SynthesisThesisCandidate(
        text="metformin shows mixed evidence...",
        receipt_ids_referenced=("r-A", "r-B", "r-C"),
        tensions_addressed=("muscle_function disagreement",),
        word_count=42,
    )
    assert cand.word_count == 42
    assert len(cand.receipt_ids_referenced) == 3
