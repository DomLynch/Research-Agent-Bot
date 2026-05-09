"""Receipt-funnel selection-flow rendering for manuscript appendices."""
from __future__ import annotations

from typing import Any


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
        (
            "Classified eligible candidates",
            receipt_funnel.get("classified_receipt_candidates"),
        ),
        ("Receipt candidate union", receipt_funnel.get("receipt_candidate_union")),
        (
            "Accepted high-confidence receipt papers",
            counts.get("accepted_high_confidence"),
        ),
        (
            "Excluded outside active/classified scope",
            counts.get("outside_active_or_classified_scope"),
        ),
        ("Candidate papers with no extracted claims", counts.get("candidate_no_claims")),
        ("Candidate papers with partial-only bindings", counts.get("candidate_partial_only")),
        (
            "Candidate papers with partial+none bindings",
            counts.get("candidate_partial_and_none_only"),
        ),
        ("Candidate papers with none-only bindings", counts.get("candidate_none_only")),
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
