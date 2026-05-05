"""Evidence clusterer — Slice 8 step D (2026-05-05).

Group receipts by outcome × design × topic-fit; pick top-N per
cluster. Solves the "45 receipts → 23K word body" problem caught
by metformin SHIP-BLOCKED on Slice 7 step 5: large corpora must
synthesize via cluster summaries, never paper-by-paper.

Universal across topics + domains. Outcome classes come from the
domain adapter (Slice 8 step B); design comes from each receipt's
extracted role/design tag. No biomedical-only assumptions in
clustering logic.

Pipeline integration:
  receipts (post-SPAR) → cluster_receipts → top_n_per_cluster
  → large-corpus writer (Slice 8 step E) consumes the cluster list
  → Q13 stays strict because Results becomes O(n_clusters)
    short-summary text instead of O(n_receipts) paper-by-paper dump
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Default top-N per cluster. Universal across domains. Override at
# call site per topic if needed (rapamycin: tighter; metformin:
# wider).
DEFAULT_TOP_N_PER_CLUSTER = 3
# Composite scoring weights — universal across domains. Each
# component is normalised 0-1; final score is sum.
_W_TIER = 0.40        # high-tier evidence (RCT > cohort > review)
_W_DIRECT = 0.25      # direct > indirect > mechanistic
_W_RECENCY = 0.15     # last 3 yrs > 5 yrs > 10 yrs
_W_NCLAIMS = 0.20     # more bound claims = more synthesis-ready


@dataclass(frozen=True, slots=True)
class EvidenceCluster:
    """One outcome × design cluster with its top-ranked receipts."""
    outcome_class: str
    design: str             # rct / cohort / meta_analysis / etc.
    receipts: tuple[Any, ...]  # SPAR-accepted receipt-shaped objects
    top_receipts: tuple[Any, ...]
    n_total: int
    n_kept: int
    cluster_score: float    # max-of receipt scores; used for ranking

    @property
    def label(self) -> str:
        return f"{self.outcome_class}/{self.design}"


def _receipt_field(r: Any, name: str, default=None):
    """Read a field from either a dict or a dataclass-like object."""
    if isinstance(r, dict):
        return r.get(name, default)
    return getattr(r, name, default)


def _tier_rank(receipt: Any, evidence_hierarchy: tuple[str, ...]) -> float:
    """0-1, where 1 = top of hierarchy. Domain-driven via adapter."""
    tier = (_receipt_field(receipt, "evidence_tier") or "").lower()
    design = (_receipt_field(receipt, "design") or "").lower()
    # Try design first (closest to hierarchy keys), then tier
    for i, h in enumerate(evidence_hierarchy):
        if h.lower() == design or h.lower() == tier:
            return 1.0 - (i / max(len(evidence_hierarchy), 1))
    return 0.0


def _directness_rank(receipt: Any) -> float:
    d = (_receipt_field(receipt, "directness") or "").lower()
    if d == "direct":
        return 1.0
    if d in ("indirect", "review"):
        return 0.5
    if d in ("mechanistic", "preclinical"):
        return 0.2
    return 0.0


def _recency_rank(receipt: Any, current_year: int = 2026) -> float:
    y = _receipt_field(receipt, "year") or _receipt_field(
        receipt, "publication_year",
    )
    try:
        age = current_year - int(y)
    except (TypeError, ValueError):
        return 0.5
    if age <= 3:
        return 1.0
    if age <= 5:
        return 0.7
    if age <= 10:
        return 0.4
    return 0.2


def _claims_rank(
    receipt: Any, *, max_claims: int = 30,
) -> float:
    n = _receipt_field(receipt, "n_claims", 0) or 0
    return min(1.0, float(n) / max_claims)


def receipt_score(
    receipt: Any, *,
    evidence_hierarchy: tuple[str, ...] = (),
) -> float:
    """Composite 0-1 score combining tier + directness + recency +
    claim density. Universal across domains; the evidence_hierarchy
    parameter is the domain-specific input that lets the same
    function rank biomedical, economics, management, etc."""
    return (
        _W_TIER * _tier_rank(receipt, evidence_hierarchy)
        + _W_DIRECT * _directness_rank(receipt)
        + _W_RECENCY * _recency_rank(receipt)
        + _W_NCLAIMS * _claims_rank(receipt)
    )


def _cluster_key(receipt: Any) -> tuple[str, str]:
    oc = (_receipt_field(receipt, "outcome_class") or "unspecified")
    design = (
        _receipt_field(receipt, "design")
        or _receipt_field(receipt, "evidence_tier")
        or "unspecified"
    )
    return (str(oc).lower(), str(design).lower())


def cluster_receipts(
    receipts: list[Any], *,
    top_n_per_cluster: int = DEFAULT_TOP_N_PER_CLUSTER,
    evidence_hierarchy: tuple[str, ...] = (),
) -> list[EvidenceCluster]:
    """Group receipts by (outcome_class, design); within each
    cluster sort by composite score; keep top_n_per_cluster.

    Universal — the only domain-specific input is
    evidence_hierarchy (passed in, not hardcoded). Caller resolves
    it from agent.domain_evidence.get_adapter(pack.domain)."""
    grouped: dict[tuple[str, str], list[Any]] = {}
    for r in receipts:
        grouped.setdefault(_cluster_key(r), []).append(r)
    out: list[EvidenceCluster] = []
    for (oc, design), members in grouped.items():
        scored = sorted(
            members,
            key=lambda r: receipt_score(
                r, evidence_hierarchy=evidence_hierarchy,
            ),
            reverse=True,
        )
        top = tuple(scored[:top_n_per_cluster])
        cluster_score = (
            receipt_score(top[0], evidence_hierarchy=evidence_hierarchy)
            if top else 0.0
        )
        out.append(EvidenceCluster(
            outcome_class=oc,
            design=design,
            receipts=tuple(scored),
            top_receipts=top,
            n_total=len(members),
            n_kept=len(top),
            cluster_score=cluster_score,
        ))
    out.sort(key=lambda c: -c.cluster_score)
    return out


def format_cluster_summary(cluster: EvidenceCluster) -> str:
    """Single short paragraph summarising one cluster: outcome,
    design, n_total, n_kept, top-receipt citation list. Used by
    Slice 8 E large-corpus writer to emit Results as O(n_clusters)
    text instead of O(n_receipts) paper-by-paper dump."""
    cites = []
    for r in cluster.top_receipts:
        rid = (
            _receipt_field(r, "receipt_id")
            or _receipt_field(r, "paper_id") or "?"
        )
        tier = _receipt_field(r, "evidence_tier") or ""
        cites.append(f"{rid} ({tier})" if tier else str(rid))
    cite_str = ", ".join(cites) or "(no top receipts)"
    return (
        f"**{cluster.outcome_class}** — {cluster.design} cluster. "
        f"{cluster.n_total} receipt{'s' if cluster.n_total != 1 else ''} "
        f"qualified; top {cluster.n_kept} retained: {cite_str}."
    )


def cluster_funnel_summary(
    clusters: list[EvidenceCluster],
) -> dict[str, int]:
    """For the dashboard funnel: clustered_into_n + n_outcome_classes
    + n_design_types. Universal."""
    n_clusters = len(clusters)
    ocs = {c.outcome_class for c in clusters}
    designs = {c.design for c in clusters}
    return {
        "n_clusters": n_clusters,
        "n_outcome_classes": len(ocs),
        "n_design_types": len(designs),
        "n_top_receipts": sum(c.n_kept for c in clusters),
        "n_total_receipts": sum(c.n_total for c in clusters),
    }


__all__ = [
    "DEFAULT_TOP_N_PER_CLUSTER",
    "EvidenceCluster",
    "receipt_score",
    "cluster_receipts",
    "format_cluster_summary",
    "cluster_funnel_summary",
]
