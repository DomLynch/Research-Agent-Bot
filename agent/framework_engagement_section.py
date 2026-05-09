"""Deterministic Phase 3 framework sections for full-paper rendering."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent.field_engagement import evaluate_engagement
from agent.synthesis_schemas import ReceiptSummary, SynthesisSection, TensionMatrix

__all__ = [
    "build_novel_framework_section",
    "build_framework_engagement_section",
]


def _entry_dict(entry: Any) -> dict:
    if isinstance(entry, dict):
        return dict(entry)
    citation = str(getattr(entry, "citation_token", "") or "")
    key = str(getattr(entry, "key", "") or citation)
    context = str(getattr(entry, "context", "") or "")
    return {
        "receipt_id": key,
        "citation_token": citation,
        "study_id": citation or key,
        "context": context,
    }


def _receipt_dict(receipt: ReceiptSummary) -> dict:
    return {
        "receipt_id": receipt.receipt_id,
        "citation_token": receipt.receipt_id,
        "outcome_class": receipt.outcome_class,
        "effect_direction": receipt.effect_direction,
        "evidence_tier": receipt.evidence_tier,
        "directness": receipt.directness,
    }


def _sentence(text: str, receipt_ids: Sequence[str] = ()) -> tuple[str, tuple[str, ...]]:
    return text.strip(), tuple(r for r in receipt_ids if r)


def build_novel_framework_section(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
) -> SynthesisSection:
    """Render a deterministic organizing framework from corpus structure.

    The section proposes an interpretation of the receipt graph, not a new
    empirical claim. It uses only tier/directness/outcome/tension metadata.
    """
    directness = {str(r.directness).lower() for r in receipts}
    tension_kinds = {t.kind for t in matrix.non_orthogonal()}
    directness_phrase = ", ".join(
        label for label in ("direct", "indirect", "mechanistic")
        if label in directness
    ) or "accepted"
    tension_phrase = ", ".join(
        label.replace("_", "-") for label in (
            "mechanism_vs_clinical",
            "null_vs_positive",
            "dose_response",
        ) if label in tension_kinds
    ) or "cross-receipt"
    sentences = [
        _sentence(
            "We propose an Endpoint-Sensitivity framework for this corpus: "
            "rapamycin evidence should be interpreted along a gradient from "
            "proximal pathway effects, through intermediate functional or "
            "biomarker endpoints, to distal clinical outcomes."
        ),
        _sentence(
            f"The accepted receipt graph contains {directness_phrase} "
            "evidence, so the manuscript should not collapse "
            "mechanistic plausibility and clinical efficacy into one verdict.",
            [r.receipt_id for r in receipts[:3]],
        ),
        _sentence(
            "The framework is useful here because the matrix contains "
            f"{tension_phrase} tensions that can otherwise be mistaken "
            "for simple inconsistency.",
            [t.receipt_a_id for t in matrix.non_orthogonal()[:2]]
            + [t.receipt_b_id for t in matrix.non_orthogonal()[:2]],
        ),
        _sentence(
            "A falsifying test would be a direct clinical trial in the same "
            "dosing context that shows concordant movement across pathway "
            "markers, functional endpoints, and distal clinical outcomes; "
            "discordance across those layers would preserve the framework."
        ),
        _sentence(
            "This is a paper-level organizing claim, not an added receipt: "
            "it can guide interpretation only where the manifest, tension "
            "matrix, and citation registry already supply support."
        ),
    ]
    body = ["## Novel Synthesis Framework", ""]
    body.extend(text for text, _ in sentences)
    return SynthesisSection(
        name="novel_framework",
        body_md="\n\n".join(body).rstrip() + "\n",
        anchors=(),
    )


def build_framework_engagement_section(
    receipts: Sequence[ReceiptSummary],
    background_refs: Sequence[Any] = (),
) -> SynthesisSection:
    receipt_rows = [_receipt_dict(r) for r in receipts]
    background_rows = [_entry_dict(r) for r in background_refs]
    engagements = evaluate_engagement(receipt_rows, background_rows)
    body = ["## Engagement with Established Frameworks", ""]
    for item in engagements:
        if item.matched_receipts:
            support = "receipt-level evidence matches " + ", ".join(
                item.matched_receipts
            )
        elif item.matched_background_refs:
            support = "background context matches " + ", ".join(
                item.matched_background_refs
            )
        else:
            support = "no matched source in the accepted evidence registry"
        body.append(
            f"- **{item.framework_name}: {item.status}.** "
            f"{support}."
        )
    body.append(
        "\nStatus labels are deterministic and conservative: background-only "
        "matches establish field presence but do not support or challenge a "
        "framework without receipt-level outcome and direction fields."
    )
    return SynthesisSection(
        name="framework_engagement",
        body_md="\n".join(body).rstrip() + "\n",
        anchors=(),
    )
