"""Receipt-funnel selection-flow rendering for manuscript appendices."""
from __future__ import annotations

from typing import Any


def receipt_admission_rows(receipt_funnel: Any) -> list[tuple[str, Any]]:
    """Return manuscript-facing receipt-admission rows.

    The rows are universal diagnostic counts from the receipt builder,
    not topic-specific PRISMA exclusions.
    """
    if not isinstance(receipt_funnel, dict):
        return []
    counts = receipt_funnel.get("counts") or receipt_funnel
    if not isinstance(counts, dict):
        counts = {}
    rows = [
        ("Receipt candidate union", receipt_funnel.get("receipt_candidate_union")),
        ("Classified receipt candidates", receipt_funnel.get("classified_receipt_candidates")),
        ("No extractable claims", counts.get("candidate_no_claims")),
        ("None-only claim binding", counts.get("candidate_none_only")),
        ("Partial/none-only claim binding", counts.get("candidate_partial_and_none_only")),
        ("Partial-only candidates", counts.get("candidate_partial_only")),
        ("Strict high-confidence receipts", counts.get("original_strict_high_confidence_receipts")),
        ("Admitted final receipts", counts.get("admitted_receipts", counts.get("accepted_high_confidence"))),
    ]
    return [(label, value) for label, value in rows if value is not None]


def render_selection_flow_lines(receipt_funnel: Any) -> list[str]:
    """Render audit counts as a compact PRISMA-style flow table."""
    if not isinstance(receipt_funnel, dict):
        return []
    counts = receipt_funnel.get("counts") or {}
    if not isinstance(counts, dict):
        counts = {}
    rows = [
        ("Quant-claim files screened", receipt_funnel.get("quant_claim_files")),
        ("Active candidate IDs", receipt_funnel.get("active_paper_ids")),
        *receipt_admission_rows(receipt_funnel),
        ("Primary-tier receipt anchors", counts.get("primary_tier_receipts")),
        (
            "Excluded outside active/classified scope",
            counts.get("outside_active_or_classified_scope"),
        ),
    ]
    lines = [
        "### Selection flow (PRISMA-style counts)",
        "",
        "These are audit counts, not a PRISMA claim.",
        "",
        "| Stage | n |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {label} | {'not recorded' if value is None else value} |"
        for label, value in rows
    )
    return lines + [""]
