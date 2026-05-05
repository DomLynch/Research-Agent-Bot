"""Large-corpus writer mode — Slice 8 step E (2026-05-05).

When the SPAR-accepted receipt set is large (≥ LARGE_CORPUS_THRESHOLD),
the Results section can balloon to 20K+ words via paper-by-paper
dumps — exactly what tripped Q13 on metformin's Slice 7 step 5
SHIP-BLOCKED run (analytical ratio 9.4% < 15%). This module
provides cluster-summary-based Results: one short paragraph per
EvidenceCluster, regardless of how many receipts that cluster
contains. Universal across topics + domains.

Hard rule (Slice 8 acceptance gate): Q13 stays at 15%. Body length
control is the writer's job, not the audit's. The cluster-summary
mode caps Results at O(n_clusters) prose, not O(n_receipts).

This module ALSO emits the deterministic Methods section since
that depends on the funnel (retrieval → classification → extraction
→ SPAR → clustering → synthesis) which only the large-corpus path
fully captures.
"""
from __future__ import annotations

from typing import Any

from agent.evidence_clusters import (
    EvidenceCluster, format_cluster_summary,
)

# Receipts above this threshold trigger cluster-summary mode. Below
# threshold, the legacy paper-by-paper writer path applies. Universal
# across topics — the threshold is a structural composition rule,
# not a quality threshold.
LARGE_CORPUS_THRESHOLD = 20

# Per-cluster paragraph word target. Keeps body length controlled:
# 15 clusters * 80 words = 1,200 words for Results, leaving room
# for Discussion (≥800) + Cross-Domain (≥800) within the Q13 ratio.
CLUSTER_PARAGRAPH_WORDS = 80


def is_large_corpus(n_receipts: int) -> bool:
    return n_receipts >= LARGE_CORPUS_THRESHOLD


def build_results_section_clustered(
    clusters: list[EvidenceCluster],
    *,
    topic: str,
) -> str:
    """Compose Results as one paragraph per cluster. Output is
    O(n_clusters) prose — independent of n_receipts. Universal:
    no topic-specific text, no biomedical-only framing.

    Each paragraph carries:
      - cluster label (outcome × design)
      - n_total / n_kept summary
      - top-receipt citations
      - 1-sentence direction-of-effect framing pulled from the
        cluster's top receipt's effect_direction field
    """
    if not clusters:
        return _empty_results_placeholder(topic)
    lines: list[str] = [
        f"## Results",
        "",
        f"This synthesis groups the SPAR-accepted receipt pool "
        f"into {len(clusters)} evidence cluster(s) by outcome × "
        f"design. Each cluster summary below carries the cluster's "
        f"top {clusters[0].n_kept if clusters else 0} highest-"
        f"composite-score receipts; full per-paper detail is in "
        f"the structured evidence tables. Cluster-summary mode "
        f"prevents body inflation when the receipt pool exceeds "
        f"the {LARGE_CORPUS_THRESHOLD}-receipt threshold.",
        "",
    ]
    # Header line per outcome class, then one paragraph per design
    by_outcome: dict[str, list[EvidenceCluster]] = {}
    for c in clusters:
        by_outcome.setdefault(c.outcome_class, []).append(c)
    for oc in sorted(by_outcome):
        lines.append(f"### {oc.replace('_', ' ').title()}")
        lines.append("")
        for cluster in sorted(
            by_outcome[oc], key=lambda x: -x.cluster_score,
        ):
            lines.append(format_cluster_summary(cluster))
            # Add a direction-of-effect summary if the top receipt
            # has effect_direction. Universal — uses the field
            # naming any synthesis pipeline would produce.
            if cluster.top_receipts:
                top = cluster.top_receipts[0]
                eff = (
                    top.get("effect_direction") if isinstance(top, dict)
                    else getattr(top, "effect_direction", None)
                )
                if eff:
                    direction_sentence = (
                        f"  Direction-of-effect: {eff}."
                    )
                    lines.append(direction_sentence)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _empty_results_placeholder(topic: str) -> str:
    """Q13-compatible placeholder when SPAR accepted no receipts.
    Honest: the audit is meant to flag thin synthesis."""
    return (
        f"## Results\n\n"
        f"_The SPAR adjudicator accepted zero receipts on this "
        f"{topic} run. No evidence clusters were formed; the "
        f"synthesis cannot make first-order claims. See the Corpus "
        f"Expansion To-Do in the final verdict for the actionable "
        f"gap._\n"
    )


def build_methods_section_clustered(
    *,
    topic: str,
    submission_id: str,
    funnel: dict[str, int] | None = None,
    clusters: list[EvidenceCluster] | None = None,
) -> str:
    """Cluster-aware Methods. Replaces the legacy build_methods_section
    when large-corpus mode is active. Pulls counters from the
    extraction funnel + cluster summary so the prose is grounded in
    the actual run, not boilerplate.

    Universal across topics + domains. Pure-Python; no LLM. Methods
    is a deterministic narrative of the funnel that produced the
    receipts."""
    f = funnel or {}
    n_clusters = len(clusters) if clusters else 0
    n_kept_top = sum(c.n_kept for c in (clusters or []))
    n_total_recpts = sum(c.n_total for c in (clusters or []))
    return (
        f"## Methods\n\n"
        f"This synthesis was produced by the Researka v0.6 "
        f"calibrated-retrieval + cluster-summary pipeline "
        f"(submission `{submission_id}`, topic *{topic}*). The "
        f"pipeline operates on the load-bearing principle that LLM "
        f"output proposes; deterministic code disposes.\n\n"
        f"### Retrieval funnel\n\n"
        f"- Retrieved (post-source-dedupe): "
        f"**{f.get('retrieved', 'n/a')}**\n"
        f"- Classified — kept (core_on_thesis + "
        f"background_mechanism + adjacent_clinical): "
        f"**{f.get('classified_keep', 'n/a')}**\n"
        f"- Classified — dropped (off_thesis + reject): "
        f"**{f.get('classified_drop', 'n/a')}**\n"
        f"- Extracted to quant_claims (kept pool only): "
        f"**{(f.get('extracted_ok', 0) or 0) + (f.get('extracted_cached', 0) or 0)}**\n"
        f"- SPAR-accepted as receipts: "
        f"**{f.get('spar_accepted', n_total_recpts)}**\n\n"
        f"### Cluster summary\n\n"
        f"The receipt pool was grouped by outcome × design into "
        f"**{n_clusters}** evidence cluster(s); the top "
        f"**{n_kept_top}** composite-scored receipts (tier + "
        f"directness + recency + claim density) carry the "
        f"cluster summary text in the Results section. Per-paper "
        f"detail is in the structured evidence tables; the cluster "
        f"summary controls body length (Q13 analytical-ratio gate "
        f"stays strict at ≥15%) without paper-by-paper dump.\n\n"
        f"### Trust spine\n\n"
        f"Every numeric in the body traces to a corpus-extracted "
        f"quant_claim or to a registered background-literature "
        f"entry. Receipts that fail SPAR adjudication (insufficient "
        f"evidence-tier, insufficient binding confidence, or "
        f"directness mismatch) are quarantined under \"Rejected / "
        f"Contested Evidence\". The audit chain (Stage 1: 13-Q "
        f"checks; Stage 2: consistency; Stage 3: source-context "
        f"drift; Stage 4: adversarial reviewer) runs after writing "
        f"and is the gating layer for AAA / Trust-Spine Pass / "
        f"SHIP-BLOCKED verdicts.\n"
    )


__all__ = [
    "LARGE_CORPUS_THRESHOLD",
    "CLUSTER_PARAGRAPH_WORDS",
    "is_large_corpus",
    "build_results_section_clustered",
    "build_methods_section_clustered",
]
