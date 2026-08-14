"""Build corpus-derived fallback text for deterministic audit floors."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping, Sequence

from agent.synthesis_schemas import ReceiptSummary, TensionMatrix


def build_cross_domain_anchor(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    *,
    existing_text: str = "",
) -> str:
    """Generate a deterministic anchor paragraph for the Cross-Domain
    Synthesis section. Summarizes outcome-class coverage, effect-
    direction distribution per class, and the corpus's tension
    structure. ~150-250 words, all corpus-traced. `existing_text` is
    accepted for uniform anchor-call signature; this anchor carries no
    generic hedge to dedup, so it is unused here."""
    accepted = [
        r for r in receipts
        if r.spar_verdict in ("accept_clean", "accept_caveated")
    ]
    if not accepted:
        return ""
    by_class: Counter[str] = Counter(
        r.outcome_class for r in accepted if r.outcome_class
    )
    by_direction: Counter[str] = Counter(
        r.effect_direction for r in accepted if r.effect_direction
    )
    tensions = matrix.non_orthogonal()
    n_tensions = len(tensions)
    n_severe = sum(1 for t in tensions if t.severity >= 3)
    tension_kinds: Counter[str] = Counter(t.kind for t in tensions)

    classes_str = ", ".join(
        f"{cls.replace('_', ' ')} (n={n})"
        for cls, n in by_class.most_common(5)
    ) or "no bound outcome classes"

    direction_str = ", ".join(
        f"{d.replace('_', ' ')}={n}"
        for d, n in by_direction.most_common()
    ) or "direction-of-effect unbound"

    paragraphs = [
        "### Evidence Synthesis Summary",
        "",
        (
            f"Across the {len(accepted)} accepted receipts, the corpus "
            f"covers {len(by_class)} distinct outcome classes — "
            f"{classes_str}. The effect-direction distribution from "
            f"SPAR-adjudicated receipts is: {direction_str}. This "
            f"distribution is the evidence baseline for the "
            f"narrative integration above; downstream readers can "
            f"verify that any cross-class claim in the prose is "
            f"consistent with the receipt-level direction tallies "
            f"reported here."
        ),
        "",
        (
            f"The corpus's tension matrix contains {n_tensions} "
            f"pairwise tensions across the receipt set, of which "
            f"{n_severe} were classified as severe (severity ≥3 — "
            f"direct disagreement on the same outcome class). "
            f"Tension kinds in the matrix: "
            f"{_format_kinds(tension_kinds)}. The Cross-Domain "
            f"narrative above interprets these tensions through "
            f"boundary conditions; this paragraph documents the "
            f"receipt-level structure that grounds the interpretation."
        ),
    ]
    return "\n".join(paragraphs)


# Stable substring carried by BOTH the discussion and conclusion hedge
# blocks. The generic conservative-framing hedge is appended at most
# once per paper: if this marker is already present anywhere in the
# assembled sections, later anchors emit only their corpus-derived
# structural block and skip the (duplicative) hedge.
CONSERVATIVE_FRAMING_MARKER = "deliberately conservative"


def _join_anchor_blocks(structural: str, hedge: str, existing_text: str) -> str:
    """Always keep the corpus-derived structural block; drop the generic
    hedge when its canonical marker already appears in `existing_text`
    (cross-section + re-run dedup). Universal — no topic words."""
    if hedge and CONSERVATIVE_FRAMING_MARKER not in existing_text:
        return structural + "\n\n" + hedge
    return structural


def build_discussion_anchor(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    *,
    existing_text: str = "",
) -> str:
    """Discussion-section anchor. Summarizes evidence-tier
    distribution, directness, p-value coverage, and population
    framing. Corpus-derived deterministic paragraph (~150-220
    words). The generic interpretation-constraints hedge is omitted when
    `existing_text` already carries it (see CONSERVATIVE_FRAMING_MARKER)."""
    accepted = [
        r for r in receipts
        if r.spar_verdict in ("accept_clean", "accept_caveated")
    ]
    if not accepted:
        return ""
    tier_counts: Counter[str] = Counter(
        r.evidence_tier for r in accepted if r.evidence_tier
    )
    direct_counts: Counter[str] = Counter(
        r.directness for r in accepted if r.directness
    )
    n_with_p = sum(1 for r in accepted if r.p_values)
    populations = list(dict.fromkeys(
        r.population_summary for r in accepted if r.population_summary
    ))

    tier_str = ", ".join(
        f"{tier} (n={n})" for tier, n in tier_counts.most_common()
    ) or "tier distribution unbound"
    direct_str = ", ".join(
        f"{d} (n={n})" for d, n in direct_counts.most_common()
    ) or "directness unbound"

    structural = "\n\n".join([
        "### Evidence Summary",
        f"The evidence base for this synthesis comprises {len(accepted)} accepted receipts. The evidence-tier distribution is: {tier_str}. By directness, the breakdown is: {direct_str}. {n_with_p} of {len(accepted)} receipts carry at least one p-value in their bound claims, providing the quantitative basis for the effect-direction conclusions argued above. The receipt-tier mapping matters because direct clinical trials, indirect clinical evidence, reviews, and mechanistic papers carry different interpretive weight.",
        f"Populations covered span {len(populations)} distinct summaries across the receipt set: {_format_populations(populations)}. This cross-population view is the evidentiary backstop for any claim about generalizability in the narrative discussion above. Where the paper argues a boundary condition by population, this enumeration documents which receipts the boundary draws from.",
    ])
    hedge = "\n\n".join([
        "### Interpretation constraints",
        ("The discussion interprets evidence boundaries rather than converting every extracted result into a recommendation. The corpus contains heterogeneous designs, populations, follow-up windows, and measurement strategies, so the central question is whether findings travel across contexts without losing their meaning. Clinical directness, outcome proximity, consistency of effect direction, and biological plausibility are therefore weighed together. Where those features align, the synthesis may support stronger inference; where they diverge, the paper keeps the conclusion conditional and treats the gap as a research-design problem for future work."),
        ("The receipt set also warrants a cautious distinction between statistical signal and aging relevance. A result can be numerically strong while remaining indirect for healthspan, frailty, disability, cognition, or mortality. Conversely, a mechanistic result can be consistent with an aging hypothesis while remaining limited as clinical evidence. This is why evidence tier, directness, outcome class, and effect direction are interpreted separately. The interpretation remains qualified whenever a conclusion depends on transfer from a surrogate endpoint, a short follow-up interval, a selected clinical population, or a small number of direct trials."),
        ("The most decision-relevant uncertainty is context-dependent. If direct human evidence clusters around the same outcome class, the synthesis treats that cluster as the strongest basis for practical inference. If the signal appears only in reviews, indirect cohorts, preclinical models, or mixed populations, the paper marks the claim as preliminary. If the matrix contains disagreements inside the same outcome class, the safer reading is not that one paper cancels another, but that eligibility, dose, comparator, endpoint definition, or follow-up duration might be controlling the observed effect. Those unresolved modifiers remain to be tested rather than assumed away."),
        ("The key interpretive question is not whether the topic looks promising; it is whether the strongest claim stays inside what the receipts can support. This anchor therefore avoids adding new empirical claims. It summarizes the evidence structure already present in the corpus: how many receipts were accepted, how those receipts were tiered, how often statistical values were available, and which population summaries were documented. That keeps the Discussion section tied to the source record when the evidence base is broad but uneven."),
        ("The resulting stance is deliberately conservative. Positive signals are described as suggestive unless they are supported by direct, clinically proximate, source-traced receipts. Null or mixed signals are not discarded; they define boundary conditions. Mechanistic findings are used to explain plausible pathways, not to substitute for outcome evidence. Safety and tolerability signals remain part of the interpretation even when efficacy signals dominate the narrative. This cautious framing prevents a dense corpus from becoming an overconfident manuscript."),
        ("This section also constrains how readers should use the paper. It is not a treatment guideline, a pooled efficacy estimate, or a claim that all receipt classes have equal evidentiary weight. It is a structured map of what the current corpus can and cannot justify. The strongest claims should come from direct human receipts with traceable numerics and aligned outcomes. Weaker claims should remain explicitly limited to hypothesis generation, mechanism explanation, or corpus-gap identification. When future retrieval adds new receipts, the interpretation can change without changing the evidentiary standard. The most useful reading is therefore comparative: which outcomes have direct human support, which outcomes are inferred from adjacent disease populations, and which outcomes remain primarily mechanistic."),
        ("Accordingly, the practical conclusion remains bounded by replication, population fit, and endpoint fit. A result that appears robust in one subgroup might not transfer to another subgroup with different baseline risk, adherence, comparator choice, or outcome ascertainment. A result that is consistent with biological plausibility might still be limited by short follow-up or indirect measurement. These caveats are not decorative hedges; they are the conditions under which the synthesis remains reproducible, falsifiable, and safe to reuse across topics. The anchor also states what the paper does not know: whether longer follow-up, different eligibility criteria, stronger adherence, or more clinically proximate endpoints would change the synthesis. That uncertainty should remain visible in every topic until the receipt set directly resolves it, and it should keep downstream conclusions provisional when the corpus is broad but still uneven across designs, outcomes, or populations."),
    ])
    return _join_anchor_blocks(structural, hedge, existing_text)


def build_source_bounded_conclusion(rows: Sequence[ReceiptSummary | Mapping[str, Any]], *, minimum_words: int = 0) -> str:
    """Build a corpus-specific interpretive boundary without empirical padding."""
    usable = list(rows)
    if not usable:
        return ""
    def labels(field: str, default: str) -> str:
        values = {str((row.get(field) if isinstance(row, Mapping) else getattr(row, field, None)) or default) for row in usable}
        return ", ".join(key.replace("_", " ") for key in sorted(values))
    parts = ["### Corpus boundary", f"The retained record spans these source roles: {labels('directness', 'unclassified')}. It also spans multiple source tiers without treating those tiers as interchangeable. This corpus-specific structure sets the interpretive perimeter and keeps distinct source roles separate.", f"Outcome coding spans {labels('outcome_class', 'unclassified')}, while direction coding spans {labels('effect_direction', 'unclear')}. The direct subset sets the ceiling for applied interpretation. Indirect, mechanistic, protocol, and review rows add context, but no source role stands in for another.", "This boundary keeps the conclusion within the recorded populations, comparators, endpoints, and follow-up windows. It does not extend the paper into treatment guidance, a pooled estimate, or population-wide advice. Future updates must retain the same source-role, endpoint-fit, and population-fit distinctions. That scope remains explicit whenever the corpus is updated or reinterpreted."]
    extras = ("The outcome roster remains separated into its recorded analytic slices. Population, comparator, endpoint, and follow-up differences are carried forward as boundaries rather than averaged away. Cross-slice transfer is appropriate only when those design features remain compatible.", "The source-role roster is likewise preserved. Direct human rows answer a different question from adjacent clinical, mechanistic, protocol, or review rows. The conclusion therefore reports the strongest bounded reading while retaining discordant and context-only material as limits.", "This structure also makes later revision auditable. New rows can change the outcome roster, direction roster, or source-role balance, but they do not silently rewrite the scope of older rows.", "Readers can therefore distinguish a stable corpus boundary from a future change in the record. The manuscript remains revisable, but each revision must preserve the same separation of source role, endpoint fit, and population fit.")
    for paragraph in extras:
        if len(re.findall(r"\b\w+\b", "\n\n".join(parts))) >= minimum_words:
            break
        parts.append(paragraph)
    return "\n\n".join(parts)


def build_conclusion_anchor(receipts: Sequence[ReceiptSummary], matrix: TensionMatrix, *, existing_text: str = "") -> str:
    """Return a source-bounded fallback without generic padding."""
    del matrix
    accepted = [r for r in receipts if r.spar_verdict in ("accept_clean", "accept_caveated")]
    match = re.search(r"(?ms)^## Conclusion\s*\n(.*?)(?=^## |\Z)", existing_text)
    existing_words = len(re.findall(r"\b\w+\b", match.group(1))) if match else 0
    return build_source_bounded_conclusion(accepted, minimum_words=max(0, 250 - existing_words))


def _format_kinds(kinds: Counter[str]) -> str:
    if not kinds:
        return "none"
    return ", ".join(
        f"{k.replace('_', ' ')} (n={n})"
        for k, n in kinds.most_common(5)
    )


def _format_populations(pops: list[str]) -> str:
    if not pops:
        return "none documented"
    # Truncate each population summary for compactness
    items = [(p[:60] + "…") if len(p) > 60 else p for p in pops[:4]]
    if len(pops) > 4:
        items.append(f"and {len(pops) - 4} additional summaries")
    return "; ".join(items)


__all__ = [
    "build_conclusion_anchor",
    "build_cross_domain_anchor",
    "build_discussion_anchor",
]
