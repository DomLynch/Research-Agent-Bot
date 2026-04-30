"""Tests for agent/synthesis_writer.py — Day 10.4 sectioned renderer.

Discriminating tests:
  - deterministic sections render expected content (table rows,
    bullet lists, references) for every input shape
  - LLM-anchored sections drop sentences that fail validation
    (unknown receipt_ids, novel numerics, empty)
  - render_synthesis_paper produces a SynthesisPaper that satisfies
    assert_synthesis_invariants
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
    SynthesisThesis,
    Tension,
    TensionMatrix,
    assert_synthesis_invariants,
)
from agent.synthesis_writer import (
    WRITER_VERSION,
    build_direct_evidence_section,
    build_evidence_summary_section,
    build_indirect_evidence_section,
    build_references_section,
    build_rejected_evidence_section,
    build_spar_adjudication_section,
    build_thesis_section,
    build_title_section,
    filter_accepted,
    is_accepted_for_synthesis,
    render_synthesis_paper,
    validate_anchored_sentence,
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
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}",
        topic="metformin",
        thesis_text=f"thesis for {rid}",
        spar_verdict="accept_clean",
        n_claims=4, n_failed_traces=0,
        canonical_trial_id=f"NCT-{rid}",
        evidence_tier=tier, directness=directness,
        outcome_class=outcome, effect_direction=direction,
        p_values=p_values,
        population_summary="older adults",
    )


def _thesis(refs: tuple[str, ...] = ("r-A", "r-B", "r-C")) -> SynthesisThesis:
    return SynthesisThesis(
        text="metformin shows mixed evidence across muscle and frailty trials",
        receipt_ids_referenced=refs,
        tensions_addressed=("r-A and r-B agree on muscle",),
        rejected_candidates=(),
        picker_rationale="picked from 3 candidates",
    )


def _matrix(receipts) -> TensionMatrix:
    return TensionMatrix(
        receipts=tuple(receipts),
        pairs=(
            Tension(
                receipt_a_id="r-A", receipt_b_id="r-B",
                kind="agreement", outcome_class="muscle_function",
                summary="r-A and r-B agree on muscle", severity=2,
            ),
        ),
    )


def _spec() -> CallSpec:
    return CallSpec(
        base_url="https://api.example.com/v1",
        api_key="k", model="test/model", timeout_sec=5.0,
    )


def _mock_handler(paragraphs_payload: dict):
    """Build an httpx MockTransport handler that always returns the
    given paragraphs payload."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": json.dumps(paragraphs_payload),
            }}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 80},
        })
    return handler


# ============================================================
# validate_anchored_sentence
# ============================================================


def test_validate_anchor_passes_well_formed_sentence() -> None:
    receipts = [_summary("r-A"), _summary("r-B")]
    ok, _ = validate_anchored_sentence(
        "Metformin has agreement at p=0.003", ("r-A",), receipts=receipts,
    )
    assert ok


def test_validate_anchor_rejects_unknown_receipt_id() -> None:
    receipts = [_summary("r-A")]
    ok, reason = validate_anchored_sentence(
        "Some sentence", ("r-FAKE",), receipts=receipts,
    )
    assert not ok
    assert "unknown_receipt_ids" in reason


def test_validate_anchor_rejects_novel_numeric() -> None:
    """Sentence cites p=0.99 but no receipt has it."""
    receipts = [_summary("r-A", p_values=("p=0.003",))]
    ok, reason = validate_anchored_sentence(
        "The result was p=0.99", ("r-A",), receipts=receipts,
    )
    assert not ok
    assert "novel_numeric" in reason


def test_validate_anchor_rejects_no_anchor() -> None:
    receipts = [_summary("r-A")]
    ok, reason = validate_anchored_sentence(
        "Some sentence", (), receipts=receipts,
    )
    assert not ok
    assert reason == "no_receipt_anchor"


# ============================================================
# Deterministic sections
# ============================================================


def test_evidence_summary_section_renders_table_for_every_receipt() -> None:
    receipts = [_summary("r-A"), _summary("r-B"), _summary("r-C")]
    sect = build_evidence_summary_section(receipts)
    assert sect.name == "evidence_summary"
    assert sect.anchors == ()
    assert "## Evidence Summary" in sect.body_md
    assert "r-A" in sect.body_md
    assert "r-B" in sect.body_md
    assert "r-C" in sect.body_md
    # Each receipt must show its outcome class
    assert "muscle_function" in sect.body_md


def test_direct_evidence_section_lists_only_direct_receipts() -> None:
    receipts = [
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
        _summary("r-C", directness="direct"),
    ]
    sect = build_direct_evidence_section(receipts)
    assert "r-A" in sect.body_md
    assert "r-C" in sect.body_md
    # mechanistic receipt does NOT appear in Direct Evidence
    assert "**r-B**" not in sect.body_md


def test_indirect_evidence_section_lists_only_mechanistic_or_indirect() -> None:
    receipts = [
        _summary("r-A", directness="direct"),
        _summary("r-B", directness="mechanistic"),
        _summary("r-C", directness="indirect"),
    ]
    sect = build_indirect_evidence_section(receipts)
    # direct does NOT appear here
    assert "**r-A**" not in sect.body_md
    assert "r-B" in sect.body_md
    assert "r-C" in sect.body_md


def test_direct_evidence_section_handles_empty_corpus() -> None:
    """No accepted direct receipts → render placeholder, don't crash.
    Day 10.10 phrasing: 'No SPAR-accepted direct (RCT-tier) receipts'."""
    receipts = [_summary("r-A", directness="mechanistic")]
    sect = build_direct_evidence_section(receipts)
    assert "direct" in sect.body_md.lower()
    assert "no" in sect.body_md.lower()


def test_references_section_lists_every_receipt_with_index() -> None:
    receipts = [_summary("r-A"), _summary("r-B")]
    sect = build_references_section(receipts)
    assert sect.name == "references"
    assert "[1]" in sect.body_md
    assert "[2]" in sect.body_md
    assert "## References" in sect.body_md


# Day 10.17 Phase 3 — publication-grade citations
# All three external reviewers flagged that internal cfab-c01 receipt
# IDs in References are a credibility-killer for any external reader.
# Phase 3 surfaces Title / Year / Venue / PMID / DOI from
# evidence_cards.json bibliographic fields. Receipt IDs stay visible
# below each citation for audit traceability.


def test_references_use_real_citation_when_bibliographic_data_present() -> None:
    """When the receipt has source_title / source_year / source_venue /
    source_pmid / source_doi populated, References must surface them
    in publication-grade format — not just the cfab-c01 internal ID."""
    receipt_with_bib = ReceiptSummary(
        receipt_id="metformin-multi-001-cfab-c01",
        receipt_path="runs/x", topic="metformin",
        thesis_text="Metformin blunts hypertrophy in older adults",
        spar_verdict="accept_clean", n_claims=4, n_failed_traces=0,
        canonical_trial_id="NCT02308228",
        evidence_tier="A1", directness="direct",
        outcome_class="muscle_function", effect_direction="negative",
        p_values=("p=0.005",), population_summary="older adults",
        source_title=(
            "Metformin blunts muscle hypertrophy in response to "
            "progressive resistance exercise training"
        ),
        source_year=2019,
        source_venue="Aging Cell",
        source_pmid="31557380",
        source_doi="10.1111/acel.13039",
    )
    sect = build_references_section([receipt_with_bib])
    body = sect.body_md
    assert "Aging Cell" in body, "venue must appear in citation"
    assert "2019" in body, "year must appear in citation"
    assert "PMID: 31557380" in body, "PMID must appear in citation"
    assert "10.1111/acel.13039" in body, "DOI must appear in citation"
    assert "Metformin blunts muscle hypertrophy" in body, "title must appear"
    # Receipt ID stays for audit traceability but is no longer the
    # only thing the reader sees.
    assert "metformin-multi-001-cfab-c01" in body


def test_references_falls_back_to_receipt_id_when_no_bibliographic_data() -> None:
    """When bibliographic fields are all None (older fixtures, malformed
    evidence_cards), the formatter falls back to the receipt ID. The
    reference still exists; it just lacks the publication metadata."""
    receipt_no_bib = _summary("r-A")  # source_* fields default to None
    sect = build_references_section([receipt_no_bib])
    assert "r-A" in sect.body_md


def test_references_handle_empty_string_bib_fields_gracefully() -> None:
    """Reviewer pin: upstream JSON parsers may coerce missing fields to
    "" rather than None. The formatter's truthy guards must skip empty
    strings the same way they skip None — no `". (). . PMID: . "`
    citation in the output."""
    receipt_partial = ReceiptSummary(
        receipt_id="metformin-multi-001-cfab-c01",
        receipt_path="runs/x", topic="metformin",
        thesis_text="thesis", spar_verdict="accept_clean",
        n_claims=1, n_failed_traces=0, canonical_trial_id=None,
        evidence_tier="A1", directness="direct",
        outcome_class="muscle_function", effect_direction="negative",
        p_values=(), population_summary="",
        source_title="", source_year=None, source_venue="",
        source_pmid="", source_doi="",
    )
    sect = build_references_section([receipt_partial])
    body = sect.body_md
    # Empty fields must be silently skipped — no "PMID: ." or "doi:."
    # or stray standalone period clusters.
    assert "PMID: ." not in body
    assert "doi:." not in body
    assert "(). " not in body
    # The receipt-id fallback path is what should fire for a fully-
    # empty bibliographic record.
    assert "metformin-multi-001-cfab-c01" in body


def test_full_paper_references_use_publication_grade_citation() -> None:
    """The full-paper References section (paper_writer_deterministic)
    must also surface publication-grade citations — same shared
    formatter as the brief, but with the verdict tag preserved."""
    from agent.paper_writer_deterministic import build_references_full_section
    rich = ReceiptSummary(
        receipt_id="metformin-multi-001-cfab-c01",
        receipt_path="runs/x", topic="metformin",
        thesis_text="Metformin blunts hypertrophy",
        spar_verdict="accept_clean", n_claims=4, n_failed_traces=0,
        canonical_trial_id="NCT02308228",
        evidence_tier="A1", directness="direct",
        outcome_class="muscle_function", effect_direction="negative",
        p_values=("p=0.005",), population_summary="older adults",
        source_title="MASTERS trial paper",
        source_year=2019, source_venue="Aging Cell",
        source_pmid="31557380", source_doi="10.1111/acel.13039",
    )
    sect = build_references_full_section([rich])
    body = sect.body_md
    assert "MASTERS trial paper" in body
    assert "Aging Cell" in body
    assert "PMID: 31557380" in body
    assert "10.1111/acel.13039" in body
    assert "[accepted: accept_clean]" in body
    # Receipt ID still present for audit traceability.
    assert "metformin-multi-001-cfab-c01" in body


def test_spar_adjudication_section_renders_verdict_table() -> None:
    receipts = [_summary("r-A"), _summary("r-B")]
    sect = build_spar_adjudication_section(receipts)
    assert "accept_clean" in sect.body_md
    assert "## SPAR Adjudication" in sect.body_md


def test_thesis_section_includes_rationale_and_anchor() -> None:
    th = _thesis()
    sect = build_thesis_section(th)
    assert sect.name == "thesis"
    assert th.text in sect.body_md
    assert th.picker_rationale in sect.body_md
    assert len(sect.anchors) == 1
    assert sect.anchors[0].receipt_ids == th.receipt_ids_referenced


def test_title_section_uses_thesis_text_as_h1() -> None:
    th = _thesis()
    sect = build_title_section(th, topic="metformin")
    assert sect.name == "title"
    assert sect.body_md.startswith(f"# {th.text}")


# ============================================================
# render_synthesis_paper — end-to-end with mocked LLM
# ============================================================


def test_render_synthesis_paper_produces_all_required_sections() -> None:
    """Discriminating test: end-to-end render must produce a
    SynthesisPaper whose `sections` covers every name in
    SECTION_ORDER and whose body_md contains all section headings.
    """
    receipts = [
        _summary("r-A", outcome="muscle_function", directness="direct"),
        _summary("r-B", outcome="muscle_function", directness="mechanistic"),
        _summary("r-C", outcome="frailty", directness="direct", direction="null"),
    ]
    matrix = _matrix(receipts)
    th = _thesis()

    # Mock LLM returns one valid paragraph per section
    handler = _mock_handler({
        "paragraphs": [
            {
                "sentence": "Receipt r-A and r-B agree on muscle outcome",
                "receipt_ids": ["r-A", "r-B"],
                "numerics": [],
            },
        ],
    })

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await render_synthesis_paper(
                receipts, matrix, th,
                topic="metformin", submission_id="syn-001",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    paper = asyncio.run(go())
    section_names = {s.name for s in paper.sections}
    expected = {
        "title", "thesis", "evidence_summary", "direct_evidence",
        "indirect_evidence", "rejected_evidence", "tensions",
        "synthesis", "limitations", "spar_adjudication", "references",
    }
    assert section_names == expected
    # body_md should contain every section heading
    for heading in (
        "# metformin", "## Thesis", "## Evidence Summary",
        "## Direct Evidence", "## Indirect / Mechanistic Evidence",
        "## Rejected / Contested Evidence",
        "## Tensions", "## Synthesis", "## Limitations",
        "## SPAR Adjudication", "## References",
    ):
        assert heading in paper.body_md, f"missing: {heading}"
    # render_version stamped
    assert paper.render_version == WRITER_VERSION
    # Schema invariants pass
    assert_synthesis_invariants(paper)


def test_render_synthesis_paper_drops_invalid_anchored_sentences() -> None:
    """When the LLM returns a sentence with an unknown receipt_id,
    the writer drops it (not crashes). Section's body_md falls back
    to the deterministic stub when nothing valid survives."""
    receipts = [
        _summary("r-A", outcome="muscle_function", directness="direct"),
        _summary("r-B", outcome="muscle_function", directness="mechanistic"),
        _summary("r-C", outcome="frailty", directness="direct", direction="null"),
    ]
    matrix = _matrix(receipts)
    th = _thesis()

    handler = _mock_handler({
        "paragraphs": [
            {
                "sentence": "Made-up sentence about r-FAKE",
                "receipt_ids": ["r-FAKE"],  # not in input
                "numerics": [],
            },
        ],
    })

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await render_synthesis_paper(
                receipts, matrix, th,
                topic="metformin", submission_id="syn-002",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    paper = asyncio.run(go())
    # Tensions / synthesis / limitations all received the same bad
    # paragraph payload — every LLM-anchored section should fall back
    # to deterministic stub. body_md must still render without crash.
    assert "Made-up" not in paper.body_md
    assert "r-FAKE" not in paper.body_md
    # Stubs are present
    assert "validation" in paper.body_md.lower()
    # Schema invariants STILL hold (no anchor with unknown receipt)
    assert_synthesis_invariants(paper)


def test_render_synthesis_paper_handles_empty_tensions_matrix() -> None:
    """Matrix with only orthogonal pairs → tensions section renders
    placeholder text without making any LLM call."""
    receipts = [
        _summary("r-A", outcome="muscle_function"),
        _summary("r-B", outcome="cognitive"),
        _summary("r-C", outcome="frailty"),
    ]
    # All cross-outcome → orthogonal
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
    th = _thesis()

    handler = _mock_handler({
        "paragraphs": [
            {
                "sentence": "Synthesis sentence",
                "receipt_ids": ["r-A", "r-B"],
                "numerics": [],
            },
        ],
    })

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await render_synthesis_paper(
                receipts, matrix, th,
                topic="metformin", submission_id="syn-003",
                chain=(_spec(),), client=client,
            )
        finally:
            await client.aclose()

    paper = asyncio.run(go())
    tensions_section = next(s for s in paper.sections if s.name == "tensions")
    # Placeholder body, no LLM call needed
    assert "No non-orthogonal" in tensions_section.body_md
    # No anchors (deterministic placeholder)
    assert tensions_section.anchors == ()


def test_writer_version_is_anchored() -> None:
    assert WRITER_VERSION == "synthesis-writer/2026-04-29-day10-10"


# ============================================================
# Day 10.10 — trust-spine ordering: filter_accepted +
# build_rejected_evidence_section + accepted-only filtering in
# direct/indirect evidence sections.
# ============================================================


def test_is_accepted_for_synthesis_only_for_accept_verdicts() -> None:
    """SPAR is the gate. Only accept_clean and accept_caveated are
    eligible to be cited as evidence in the synthesis layer."""
    accepted = _summary("r-A")  # default verdict accept_clean
    caveated = ReceiptSummary(**{**dataclasses_asdict(accepted), "spar_verdict": "accept_caveated"})
    rejected_critical = ReceiptSummary(**{**dataclasses_asdict(accepted), "spar_verdict": "reject_critical"})
    rejected_majority = ReceiptSummary(**{**dataclasses_asdict(accepted), "spar_verdict": "reject_majority"})
    assert is_accepted_for_synthesis(accepted) is True
    assert is_accepted_for_synthesis(caveated) is True
    assert is_accepted_for_synthesis(rejected_critical) is False
    assert is_accepted_for_synthesis(rejected_majority) is False


def test_filter_accepted_keeps_only_accept_verdicts() -> None:
    accepted = _summary("r-A")
    rejected = ReceiptSummary(
        **{**dataclasses_asdict(accepted), "receipt_id": "r-B", "spar_verdict": "reject_critical"}
    )
    out = filter_accepted([accepted, rejected])
    assert len(out) == 1
    assert out[0].receipt_id == "r-A"


def test_direct_evidence_section_excludes_spar_rejected() -> None:
    """Day 10.10 trust-spine ordering: a SPAR-rejected receipt is NOT
    citable evidence, even if it's `directness=direct`."""
    accepted = _summary("r-A", directness="direct")
    rejected_direct = ReceiptSummary(**{
        **dataclasses_asdict(accepted),
        "receipt_id": "r-B",
        "spar_verdict": "reject_critical",
    })
    section = build_direct_evidence_section([accepted, rejected_direct])
    assert "r-A" in section.body_md
    assert "r-B" not in section.body_md


def test_indirect_evidence_section_excludes_spar_rejected() -> None:
    accepted = _summary("r-A", directness="mechanistic")
    rejected_mech = ReceiptSummary(**{
        **dataclasses_asdict(accepted),
        "receipt_id": "r-B",
        "spar_verdict": "reject_majority",
    })
    section = build_indirect_evidence_section([accepted, rejected_mech])
    assert "r-A" in section.body_md
    assert "r-B" not in section.body_md


def test_rejected_evidence_section_lists_only_rejected() -> None:
    """The quarantine section lists rejected receipts for transparency
    but explicitly notes they are NOT cited as evidence."""
    accepted = _summary("alpha")
    rejected = ReceiptSummary(**{
        **dataclasses_asdict(accepted),
        "receipt_id": "beta",
        "canonical_trial_id": None,
        "spar_verdict": "reject_critical",
    })
    section = build_rejected_evidence_section([accepted, rejected])
    assert "**alpha**" not in section.body_md
    assert "**beta**" in section.body_md
    assert "reject_critical" in section.body_md
    assert "not cited" in section.body_md.lower()


def test_rejected_evidence_section_empty_when_all_accepted() -> None:
    accepted = _summary("r-A")
    section = build_rejected_evidence_section([accepted])
    assert "Nothing to quarantine" in section.body_md or "nothing to quarantine" in section.body_md.lower()


# Helper for tests above — needed because tests want to mutate a single
# field of a frozen dataclass.
def dataclasses_asdict(obj):
    import dataclasses as _dc
    return _dc.asdict(obj)
