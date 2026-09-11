"""Byte-equivalence determinism guard for the deterministic render path.

Locks the "CODE DISPOSES / reproducible" guarantee: rendering the same receipts
twice — and rendering an equal-but-freshly-built set — must produce identical
output. A future change that leaks nondeterminism (dict/set iteration order,
a timestamp, a hash seed) into the bibliography render fails here.

Pattern noted in GrepSeek (Apache-2.0, "semantics-preserving" byte-equivalence
check); re-implemented as our own minimal test, no external code.
"""
from __future__ import annotations

from agent.paper_writer_deterministic import (
    build_references_full_section,
    format_bibliographic_citation,
)
from agent.synthesis_schemas import ReceiptSummary


def _receipt(rid: str, *, title: str, year: int, venue: str, pmid: str) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="resveratrol",
        thesis_text="t", spar_verdict="accept_clean", n_claims=3, n_failed_traces=0,
        canonical_trial_id=None, evidence_tier="A1", directness="direct",
        outcome_class="cardiometabolic", effect_direction="positive",
        p_values=("p=0.01",), population_summary="older adults",
        source_title=title, source_year=year, source_venue=venue, source_pmid=pmid,
    )


def _receipts() -> list[ReceiptSummary]:
    return [
        _receipt("r-001", title="Resveratrol and vascular function", year=2025,
                 venue="J Aging", pmid="111"),
        _receipt("r-002", title="A trial of resveratrol in older adults", year=2024,
                 venue="Circulation", pmid="222"),
        _receipt("r-003", title="Resveratrol pharmacokinetics", year=2023,
                 venue="Clin Pharm", pmid="333"),
    ]


def test_bibliographic_citation_is_byte_stable() -> None:
    for r in _receipts():
        a = format_bibliographic_citation(r)
        assert a == format_bibliographic_citation(r)
        assert a  # non-empty render


def test_references_section_is_byte_stable_across_calls() -> None:
    receipts = _receipts()
    assert build_references_full_section(receipts) == build_references_full_section(receipts)


def test_references_section_stable_across_equal_receipt_rebuild() -> None:
    # Freshly-built but value-equal receipts must render identically — proves the
    # output depends only on receipt content, not object identity or hidden state.
    assert build_references_full_section(_receipts()) == build_references_full_section(_receipts())
