from __future__ import annotations

from typing import Any
from collections import Counter

_ADMISSION_ROWS = (
    ("Receipt candidate union", "receipt_candidate_union"), ("Classified receipt candidates", "classified_receipt_candidates"),
    ("No extractable claims", "candidate_no_claims"), ("None-only claim binding", "candidate_none_only"),
    ("Mixed partial-or-none claim-binding candidates", "candidate_partial_and_none_only"),
    ("Partial-only claim-binding candidates", "candidate_partial_only"),
    ("Strict high-confidence receipts", "original_strict_high_confidence_receipts"),
    ("Admitted final receipts", "admitted_receipts"),
)


def receipt_admission_rows(receipt_funnel: Any) -> list[tuple[str, Any]]:
    if not isinstance(receipt_funnel, dict):
        return []
    counts = receipt_funnel.get("counts") or receipt_funnel
    if not isinstance(counts, dict):
        counts = {}
    values = {
        **receipt_funnel, **counts,
        "admitted_receipts": counts.get("admitted_receipts", counts.get("accepted_high_confidence")),
    }
    return [(label, values.get(key)) for label, key in _ADMISSION_ROWS if values.get(key) is not None]


def render_selection_flow_lines(receipt_funnel: Any) -> list[str]:
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
        ("Excluded outside active/classified scope", counts.get("outside_active_or_classified_scope")),
    ]
    lines = ["### Selection flow (PRISMA-style counts)", "", "These are audit counts, not a PRISMA claim. Mixed partial-or-none candidates and partial-only candidates are distinct audit buckets, not additive exclusion totals.", "", "| Stage | n |", "|---|---:|"]
    lines.extend(f"| {label} | {'not recorded' if value is None else value} |" for label, value in rows)
    return lines + [""]


def render_admission(log: dict[str, Any]) -> str:
    decisions = log["decisions"]
    included = sum(row["included"] for row in decisions.values())
    reasons_by_decision = Counter((row["included"], row["reason"]) for row in decisions.values())
    reasons = "; ".join(f"{'included' if kept else 'excluded'} — {reason.replace('_', ' ')}: {count}" for (kept, reason), count in sorted(reasons_by_decision.items())) or "none"
    prior = render_admission(log["selection_assessment"]) + "\n\n" if log.get("selection_assessment") else ""
    return prior + (f"Selection assessment ({log['scope']}) dated {log['assessed_at']}, rule {log['rule_version']}: "
            f"{log['rule']} Assessed {len(decisions)} candidate sources; included {included}; "
            f"excluded {len(decisions) - included}. Decision reasons: {reasons}. "
            "The source-by-source decisions and identifiers are in source_admission.json. "
            "This assessment records the stated candidate scope on this date; it does not reconstruct "
            "unrecorded historical screening or equate retrieval totals with assessed candidates.")
