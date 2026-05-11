"""Phase 3 framework-section adapter.

End-to-end builder for the "Engagement with Established Frameworks"
section: takes manifest-shaped receipts + an optional citation registry
+ optional background references, calls `agent.field_engagement.
evaluate_engagement`, and renders deterministic markdown.

Stdlib-only. No LLM. No raw-paper shortcut. The five named frameworks
(Mannick, Lamming, Kennedy, Kaeberlein, Lopez-Otin) are emitted only
when the corpus actually contains supporting receipts; insufficient
support is rendered honestly with a [provisional] marker rather than
fabricated.

Section format:

    ## Engagement with Established Frameworks

    Of the {N} evaluated frameworks: {S} support, {C} challenge,
    {E} extends, {I} insufficient.

    ### Mannick
    [status-driven paragraph citing matched receipts]
    ...
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from agent.field_engagement import (
    FIELD_FRAMEWORK_REGISTRY,
    Framework,
    FrameworkEngagement,
    evaluate_engagement,
)
from agent.synthesis_schemas import ReceiptSummary, SynthesisSection, TensionMatrix

__all__ = [
    "SectionConfig",
    "build_framework_engagement_records",
    "build_framework_engagement_section",
    "build_framework_section",
    "build_novel_framework_section",
    "render_engagement_section",
    "render_engagement_summary_line",
    "render_framework_paragraph",
    "enrich_receipts_with_registry",
]


@dataclass(frozen=True, slots=True)
class SectionConfig:
    """Render-time options for the engagement section.

    include_insufficient — emit an entry for each framework with status
                           "insufficient", marked [provisional]. False
                           hides them entirely (use when corpus is final
                           and the gap is uninformative).
    heading_level         — top-level heading level (## by default).
    framework_order       — explicit framework name order; None preserves
                           input order.
    """

    include_insufficient: bool = True
    heading_level: int = 2
    framework_order: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not (1 <= self.heading_level <= 4):
            raise ValueError(
                f"heading_level must be 1..4, got {self.heading_level}"
            )


_STATUS_LEAD = {
    "support": "Our corpus supports the {name} framework",
    "challenge": "Our corpus challenges the {name} framework",
    "extends": "Our corpus extends the {name} framework",
    "insufficient": "Our corpus does not yet evaluate the {name} framework",
}


def enrich_receipts_with_registry(
    receipts: Sequence[dict],
    citation_registry: Mapping[str, dict] | None,
) -> list[dict]:
    """Copy receipts and attach `citation_token` from a citation registry
    keyed by `receipt_id`. Receipts that already carry `citation_token`
    are left unchanged. Receipts whose ID is not in the registry are
    passed through unmodified."""
    if not citation_registry:
        return [dict(r) for r in receipts]
    enriched: list[dict] = []
    for receipt in receipts:
        e = dict(receipt)
        if "citation_token" not in e:
            entry = citation_registry.get(receipt.get("receipt_id", ""))
            if isinstance(entry, dict):
                token = entry.get("body_citation") or entry.get("citation_token")
                if isinstance(token, str) and token:
                    e["citation_token"] = token
        enriched.append(e)
    return enriched


def _entry_dict(entry: object) -> dict:
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


def build_framework_engagement_records(
    receipts: Sequence[ReceiptSummary],
    background_refs: Sequence[object] = (),
) -> tuple[FrameworkEngagement, ...]:
    """Return structured engagement records from writer-safe inputs."""
    receipt_rows = [_receipt_dict(r) for r in receipts]
    background_rows = [_entry_dict(r) for r in background_refs]
    return tuple(evaluate_engagement(receipt_rows, background_rows))


def build_novel_framework_section(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    *,
    topic: str = "",
) -> SynthesisSection:
    """Render a deterministic organizing framework from corpus structure.

    Wave 23 universal fix: the prior version hardcoded 'rapamycin
    evidence should be interpreted ...' which leaked into every paper
    regardless of the actual topic — violating the universal-no-
    hardcoding rule. This version takes the live `topic` and substitutes
    it. When `topic` is empty/unknown, the prose falls back to the
    domain-agnostic 'the corpus' phrasing."""
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
        ) if label in tension_kinds
    ) or "cross-receipt"
    outcome_classes = {str(r.outcome_class).lower() for r in receipts}
    has_metabolic = any(
        "cardio" in o or "metabolic" in o or "weight" in o
        for o in outcome_classes
    )
    has_functional = any(
        "muscle" in o or "frailty" in o or "function" in o or "bone" in o
        for o in outcome_classes
    )
    framework_name = (
        "Metabolic-Functional Tradeoff Framework"
        if has_metabolic and has_functional
        else "Endpoint-Sensitivity Framework"
    )
    subject = (topic.strip() or "the corpus").rstrip("_").replace("_", " ")
    body = [
        f"## {framework_name}",
        "",
        f"We propose a {framework_name} for this corpus: "
        f"{subject} evidence should be interpreted along a gradient from "
        "proximal pathway effects, through intermediate functional or "
        "biomarker endpoints, to distal observable outcomes.",
        "",
        f"The accepted receipt graph contains {directness_phrase} evidence, "
        "so the manuscript should not collapse mechanistic plausibility and "
        "downstream observed effect into one verdict.",
        "",
        "The framework is useful here because the matrix contains "
        f"{tension_phrase} tensions that can otherwise be mistaken for simple "
        "inconsistency.",
        "",
        "A falsifying test would be a study in the same context that shows "
        "concordant movement across pathway markers, intermediate endpoints, "
        "and distal observed outcomes; discordance across those layers would "
        "preserve the framework.",
        "",
        "This is a paper-level organizing claim, not an added receipt: it can "
        "guide interpretation only where the manifest, tension matrix, and "
        "citation registry already supply support.",
    ]
    return SynthesisSection(
        name="novel_framework",
        body_md="\n".join(body).rstrip() + "\n",
        anchors=(),
    )


def build_framework_engagement_section(
    receipts: Sequence[ReceiptSummary],
    background_refs: Sequence[object] = (),
) -> SynthesisSection:
    """Render the paper-safe framework engagement section.

    This intentionally avoids tally numerics from the artifact renderer so
    paper-level numeric audit remains source-traceable.
    """
    engagements = build_framework_engagement_records(receipts, background_refs)
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
            # Wave 23 universal fix: 'no matched source in the accepted
            # evidence registry' was engine-internal jargon that the
            # public_manuscript_contract correctly flagged as residue.
            # Use plain language readers can parse.
            support = "no matching source in this corpus"
        body.append(
            f"- **{item.framework_name}: {item.status}.** {support}."
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


def _format_receipt_list(receipt_ids: Sequence[str]) -> str:
    if not receipt_ids:
        return "no anchor-author receipts present"
    if len(receipt_ids) == 1:
        return f"one matching receipt ({receipt_ids[0]})"
    return f"{len(receipt_ids)} matching receipts ({', '.join(receipt_ids)})"


def render_framework_paragraph(engagement: FrameworkEngagement) -> str:
    """Render the body paragraph for one framework. Status-driven, citation-
    backed. `[provisional]` prefix on insufficient entries."""
    lead = _STATUS_LEAD[engagement.status].format(name=engagement.framework_name)
    receipts_phrase = _format_receipt_list(engagement.matched_receipts)
    bg_phrase = ""
    if engagement.matched_background_refs:
        bg_phrase = (
            f" The background-literature surface also lists "
            f"{len(engagement.matched_background_refs)} reference(s) "
            f"({', '.join(engagement.matched_background_refs)})."
        )
    body = (
        f"{lead}: {receipts_phrase}.{bg_phrase} "
        f"Audit rationale: {engagement.rationale}"
    )
    if engagement.status == "insufficient":
        body = f"[provisional] {body}"
    return body


def render_engagement_summary_line(engagements: Iterable[FrameworkEngagement]) -> str:
    """One-line status tally line."""
    counts = {"support": 0, "challenge": 0, "extends": 0, "insufficient": 0}
    total = 0
    for e in engagements:
        counts[e.status] += 1
        total += 1
    return (
        f"Of the {total} evaluated framework(s): "
        f"{counts['support']} support, "
        f"{counts['challenge']} challenge, "
        f"{counts['extends']} extends, "
        f"{counts['insufficient']} insufficient."
    )


def render_engagement_section(
    engagements: Sequence[FrameworkEngagement],
    *,
    config: SectionConfig | None = None,
) -> str:
    """Render the section markdown from pre-computed engagements. Pure
    rendering; no evaluation."""
    config = config or SectionConfig()
    top_marker = "#" * config.heading_level
    sub_marker = "#" * (config.heading_level + 1)

    out: list[str] = [f"{top_marker} Engagement with Established Frameworks", ""]
    if not engagements:
        out.append("_No framework engagements computed._")
        return "\n".join(out)

    if config.framework_order is not None:
        order_index = {name: i for i, name in enumerate(config.framework_order)}
        ordered = sorted(
            engagements,
            key=lambda e: (
                order_index.get(e.framework_name, len(order_index)),
                e.framework_name,
            ),
        )
    else:
        ordered = list(engagements)

    visible = [
        e for e in ordered
        if config.include_insufficient or e.status != "insufficient"
    ]

    out.append(render_engagement_summary_line(ordered))
    out.append("")
    if not visible:
        out.append(
            "_All framework engagements were insufficient; "
            "section suppressed by config._"
        )
        return "\n".join(out)

    for engagement in visible:
        out.append(f"{sub_marker} {engagement.framework_name}")
        out.append("")
        out.append(render_framework_paragraph(engagement))
        out.append("")
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def build_framework_section(
    receipts: Sequence[dict],
    *,
    citation_registry: Mapping[str, dict] | None = None,
    background_refs: Sequence[dict] = (),
    frameworks: Sequence[Framework] | None = None,
    config: SectionConfig | None = None,
) -> str:
    """End-to-end: enrich receipts with citation tokens (if registry
    given), call `evaluate_engagement`, render the section.

    The five canonical frameworks (FIELD_FRAMEWORK_REGISTRY) are used by
    default; pass `frameworks=` for a custom subset."""
    enriched = enrich_receipts_with_registry(receipts, citation_registry)
    engagements = evaluate_engagement(
        receipts=enriched,
        background_refs=background_refs,
        frameworks=frameworks if frameworks is not None else FIELD_FRAMEWORK_REGISTRY,
    )
    return render_engagement_section(engagements, config=config)
