"""Slice 25 / Lane E — regression coverage for 5 functions from the
session-handoff backlog. Each test exercises the function's contract
once with a passing case and once with a failing/edge case so the
behaviour is locked in.

Stdlib-only fixtures, no LLM. Universal — no topic-specific assumptions.
"""
from __future__ import annotations

from agent.manuscript_prisma import build_prisma_bridge_appendix
from agent.paper_writer_backstop import build_backstop_prompt
from agent.role_classifier import classify_design
from agent.synthesis_audit_q8q9q10 import check_q8, check_q9
from agent.synthesis_schemas import (
    ReceiptSummary,
    SynthesisPaper,
    SynthesisThesis,
    TensionMatrix,
)


# ---- helpers --------------------------------------------------------------


def _receipt(rid: str, *, spar_verdict: str = "accept_clean") -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid,
        receipt_path=f"/tmp/{rid}",
        topic="example_topic",
        thesis_text="stub thesis text",
        spar_verdict=spar_verdict,
        n_claims=1,
        n_failed_traces=0,
        canonical_trial_id=None,
        evidence_tier="B",
        directness="direct",
        outcome_class="cardiometabolic",
        effect_direction="unclear",
        p_values=(),
        population_summary="adult cohort",
    )


def _paper(body_md: str) -> SynthesisPaper:
    return SynthesisPaper(
        submission_id="run-test-0001",
        topic="example_topic",
        thesis=SynthesisThesis(
            text="stub thesis text",
            receipt_ids_referenced=(),
            tensions_addressed=(),
            rejected_candidates=(),
            picker_rationale="stub",
        ),
        matrix=TensionMatrix(receipts=(), pairs=()),
        sections=(),
        body_md=body_md,
        render_version="synthesis-writer/2026-05-15",
    )


# ---- build_prisma_bridge_appendix ----------------------------------------


def test_build_prisma_bridge_appendix_renders_universal_scaffolding() -> None:
    """Universal across topics: returns a markdown block with the
    PRISMA-Bridge heading, topic line, search-and-selection disclosure.
    No drug-specific text leaked from the manifest."""
    out = build_prisma_bridge_appendix(
        {"n_receipts": 12, "n_high_confidence_claims_total": 33,
         "generated_at": "2026-05-15T10:00:00Z"},
        topic="example_topic_with_no_pack",
    )
    assert "## PRISMA Bridge — Search and Selection Transparency" in out
    assert "**Topic:** example_topic_with_no_pack" in out
    # When pack is missing, function emits a NOTE about it (universal
    # fail-soft behaviour — not a fatal error).
    assert "topic pack not loaded" in out


def test_build_prisma_bridge_appendix_handles_missing_manifest_fields() -> None:
    """Empty manifest must not crash; the renderer falls back to 0 / unknown
    for unspecified counts. Universal robustness."""
    out = build_prisma_bridge_appendix({}, topic="some_topic")
    assert "PRISMA Bridge" in out
    assert "**Topic:** some_topic" in out


# ---- classify_design -----------------------------------------------------


def test_classify_design_published_results_with_randomized_marker_is_rct() -> None:
    """When role=published_results and abstract has RANDOMIZED marker,
    design must be 'rct'. The regex matches randomized/randomised/rct/
    double-blind/placebo-controlled. Universal — no topic markers."""
    assert classify_design(
        "published_results",
        "Patients were randomized to placebo or active arm.",
    ) == "rct"


def test_classify_design_published_results_without_randomized_is_observational() -> None:
    assert classify_design(
        "published_results",
        "A retrospective cohort analysis of routine care data.",
    ) == "observational"


def test_classify_design_review_with_meta_analysis_marker() -> None:
    assert classify_design(
        "review",
        "This systematic review and meta-analysis pooled 12 trials.",
    ) == "meta_analysis"


def test_classify_design_fallback_covers_all_role_branches() -> None:
    # No abstract markers needed for these branches — role determines.
    assert classify_design("published_protocol", "") == "protocol"
    assert classify_design("registered_pending", "") == "registry"
    assert classify_design("mechanistic", "") == "mechanistic"
    # Unknown role falls through to "other".
    assert classify_design("other", "") == "other"  # type: ignore[arg-type]


# ---- build_backstop_prompt -----------------------------------------------


def test_build_backstop_prompt_appends_audit_block() -> None:
    """The backstop appends a 'CRITICAL AUDIT REQUIREMENT' block that
    names the actual previous word count + the floor. Universal across
    sections; the section_name is uppercased in the leading sentence."""
    base = "Write a Discussion."
    out = build_backstop_prompt(
        base, section_name="discussion", prev_words=200, floor=800,
    )
    assert out.startswith(base)
    assert "## CRITICAL AUDIT REQUIREMENT" in out
    # Section name surfaces in uppercase per the prompt text.
    assert "DISCUSSION" in out
    # Prev/floor numbers must be literally present so the model sees
    # them — protects against quiet template drift.
    assert "ONLY 200 words" in out
    assert "below 800 words" in out
    # Generation target floor + buffer.
    assert "900 words" in out  # floor + 100


def test_build_backstop_prompt_handles_zero_prev_words() -> None:
    out = build_backstop_prompt(
        "stub base", section_name="conclusion", prev_words=0, floor=250,
    )
    assert "ONLY 0 words" in out
    assert "below 250 words" in out


# ---- check_q8 (rejected-receipt quarantine leakage) ----------------------


def test_check_q8_passes_when_no_rejected_receipts() -> None:
    receipts = (_receipt("r-001"), _receipt("r-002"))
    paper = _paper("# Body\n\nClean prose citing r-001 and r-002.\n")
    result = check_q8(paper, receipts)
    assert result.passed is True
    assert result.applicable is False
    assert "no rejected receipts" in result.detail


def test_check_q8_flags_leaked_rejected_receipt() -> None:
    """A rejected receipt appearing under a NON-quarantine section
    must be flagged. Universal — quarantine sections are Methods,
    References, Rejected/Contested."""
    rejected = _receipt("r-bad", spar_verdict="reject_unsupported")
    accepted = _receipt("r-good")
    paper = _paper(
        "## Results\n\nFinding cites r-bad in a headline result.\n"
    )
    result = check_q8(paper, (rejected, accepted))
    assert result.passed is False
    assert "r-bad" in result.detail


def test_check_q8_allows_rejected_receipt_in_quarantine_section() -> None:
    """Same rejected receipt is OK when it appears under a quarantine
    section (Methods, References, Rejected/Contested)."""
    rejected = _receipt("r-bad", spar_verdict="reject_unsupported")
    paper = _paper(
        "## Rejected / Contested Evidence\n\n"
        "r-bad was excluded because of unresolved citation traceability.\n"
    )
    result = check_q8(paper, (rejected,))
    assert result.passed is True


# ---- check_q9 (inline receipt-id format validity) -------------------------


def test_check_q9_passes_when_all_inline_ids_match_corpus() -> None:
    receipts = (_receipt("metformin-001-2026-04-28-abcd"),)
    paper = _paper(
        "Body referencing metformin-001-2026-04-28-abcd inline.\n"
    )
    result = check_q9(paper, receipts)
    assert result.passed is True


def test_check_q9_skips_when_corpus_is_empty() -> None:
    """N/A: empty corpus → passed=True + applicable=False."""
    result = check_q9(_paper("body text\n"), ())
    assert result.passed is True
    assert result.applicable is False
