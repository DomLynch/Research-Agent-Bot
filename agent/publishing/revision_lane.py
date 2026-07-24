"""Pure reviewer-request classification used by the revision lane."""
from __future__ import annotations

import re
from typing import Any


def required_revision_items(row: dict[str, Any]) -> list[str]:
    raw = row.get("requiredRevisions") or row.get("required_revisions")
    return (
        [str(item).strip() for item in raw if str(item).strip()]
        if isinstance(raw, list)
        else []
    )


def calibration_only_revision(text: str) -> bool:
    lower = " ".join(str(text or "").lower().split())
    return (
        "calibration rules" in lower
        and "revise" in lower
        and (
            "direct clinical evidence" in lower
            or "broad population-level proof is missing" in lower
            or "underlying evidence base" in lower
        )
    )


def actionable_revisions(row: dict[str, Any]) -> list[str]:
    return [
        item
        for item in required_revision_items(row)
        if not calibration_only_revision(item)
    ]


def revision_detail_score(row: dict[str, Any]) -> tuple[int, int]:
    submission_id = row.get("submissionId") or row.get("submission_id")
    return int(bool(str(submission_id or "").strip())), len(required_revision_items(row))


def revise_reason_bucket(text: str) -> str:
    lower = " ".join(str(text or "").lower().split())
    taxonomy = (
        ("directness_honesty", ("direct clinical", "direct interventional", "indirect", "adjacent", "mechanistic", "overclaim", "hypothesis-generating", "broad population-level proof", "no direct")),
        ("null_signal_reconciliation", ("null directional", "no extracted directional signal", "no directional signal", "strongest signal", "reconcile", "supports", "bounded rationale")),
        ("source_relevance_classification", ("source bundle", "source directness", "source classification", "outcome class", "evidence_type", "evidence type", "off-topic", "operationalize", "included under")),
        ("numeric_claim_rigor", ("p-value", "p value", "confidence interval", "significant", "non-significant", "effect direction", "factual error", "statistic")),
        ("readability_redundancy", ("repetitive", "duplication", "truncated", "grammatical", "readability", "verbatim repetition")),
        ("actionable_gaps", ("gaps identified", "actionable", "future research", "next steps")),
    )
    return next(
        (
            bucket
            for bucket, tokens in taxonomy
            if any(token in lower for token in tokens)
        ),
        "unknown",
    )


def requests_domain_scope_reset(feedback: str) -> bool:
    lower = " ".join(str(feedback or "").lower().split())
    frame = r"(?:framing|overlay)"
    patterns = (
        rf"does not support\b.{{0,120}}\b{frame}\b",
        rf"\b{frame}\b.{{0,120}}\bdoes not support\b",
        r"does not match\b.{0,120}\bactual (?:research )?question\b",
        r"actual (?:research )?question\b.{0,120}\bdoes not match\b",
        rf"\bremove\b.{{0,120}}\b{frame}\b",
        rf"\b{frame}\b.{{0,120}}\bremove\b",
    )
    segments = [segment for segment in re.split(r"(?:;|\.)\s+", lower) if segment]
    return bool(segments) and all(
        any(
            term in segment
            for term in (
                "geroscience",
                "anti-aging",
                "anti aging",
                "longevity",
                "healthspan",
            )
        )
        and any(re.search(pattern, segment) for pattern in patterns)
        for segment in segments
    )
