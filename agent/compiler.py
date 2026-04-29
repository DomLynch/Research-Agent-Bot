"""Compiler — facts → Claims → ClaimGraph.

Hard rule (printed at the top of every prompt that touches the trust spine):
  LLM PROPOSES. CODE DISPOSES.
  - Role assignment: registry override > deterministic abstract classifier. Never LLM.
  - Fact identity: extracted by LLM, schema-validated, source-text-traced.
  - Claim membership in claim_receipt.md: gated by claim_graph.json. LLM cannot add claims.

Day 3.2a (this slice): the **deterministic** half. Pure functions, no LLM,
no external I/O. Takes typed `Fact` records (already produced by some
upstream — Day 3.2c will be the LLM-driven extraction; Day 3.2a is content
with synthetic / hand-curated facts) plus the `EvidenceItem`s they cite,
and emits a structurally valid `ClaimGraph`.

The contract:
  list[Fact] + list[EvidenceItem] → list[Claim] → ClaimGraph

Each Claim is derived from a single Fact (1:1). Multi-fact claim merging
is a Day 4+ concern (thesis tournament + SPAR may collapse near-duplicate
claims). Day 3.2a keeps the relationship straightforward: every Fact
becomes a Claim with one supporting ref.

The mapping rules are deterministic:
  Fact.kind="result"   → claim_type="efficacy"
  Fact.kind="protocol" → claim_type="context"
  Fact.kind="context"  → claim_type="context"
  EvidenceItem.direct=True  → directness="direct"
  EvidenceItem.direct=False → directness derived from role:
      role="mechanistic" → "mechanistic"
      otherwise         → "indirect"
  EvidenceItem.tier → claim.evidence_tier (1:1)

Confidence is derived from the (role, design, tier) triple — same
heuristic as evidence_cards.confidence_verdict, but per-claim:
  published_results + rct + A1   → high
  published_results + rct + A2   → moderate
  published_results + observational → low
  review + meta_analysis         → moderate
  registered_pending / protocol  → low
  mechanistic / off_domain       → low

The thesis claim is picked by score: highest evidence_tier (A1>A2>B>C)
within direct claims, breaking ties by confidence (high>moderate>low),
then by claim_id ascending. If the corpus has no direct claims, the
top-tiered indirect claim wins. Empty input raises ValueError — a
ClaimGraph must have at least one claim.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent.schemas import (
    Claim,
    ClaimGraph,
    Confidence,
    Directness,
    assert_claim_graph_invariants,
)
from agent.thesis_tournament import pick_thesis
from agent.types import EvidenceItem, Fact

__all__ = [
    "compile_claims",
    "compile_claim_graph",
    "compile_per_cluster_claim_graphs",
    "cluster_all_claims",
    "CompileError",
]


class CompileError(ValueError):
    """Raised when the compiler can't produce a structurally valid graph."""


# --- Per-claim derivation -------------------------------------------------


def _derive_claim_type(fact: Fact) -> str:
    """Map Fact.kind → Claim.claim_type literal.

    Day 3.2a uses the simplest mapping — Day 4 may refine when the
    thesis tournament needs `safety` / `mechanism` distinctions.
    """
    if fact.kind == "result":
        return "efficacy"
    return "context"


def _derive_directness(item: EvidenceItem) -> Directness:
    """direct/indirect/mechanistic from EvidenceItem.

    `direct=True` always wins. When False, role drives the demotion:
    `mechanistic` role → `mechanistic` directness; everything else
    → `indirect` (covers off_domain, off-population, etc.).
    """
    if item.direct:
        return "direct"
    if item.role == "mechanistic":
        return "mechanistic"
    return "indirect"


def _derive_confidence(item: EvidenceItem) -> Confidence:
    """Per-claim confidence from the (role, design, tier) triple.

    Single-paper view, not the bundle-wide confidence_verdict in
    evidence_cards.py — a claim cited by an A1 RCT is high-confidence
    even if the rest of the bundle is mechanistic noise.
    """
    if item.role == "published_results":
        if item.design == "rct" and item.tier == "A1":
            return "high"
        if item.design == "rct":
            return "moderate"
        return "low"  # observational
    if item.role == "review":
        if item.design == "meta_analysis":
            return "moderate"
        return "low"
    return "low"


def _claim_id_for(index: int) -> str:
    """Deterministic claim ids: C001, C002, ... C999. Three-digit padding
    so lexical sort matches numeric sort up to 1000 claims (well past
    the realistic Proof 001 ceiling of ~30 per topic)."""
    return f"C{index:03d}"


# --- compile_claims -------------------------------------------------------


def compile_claims(
    facts: Sequence[Fact],
    items: Sequence[EvidenceItem],
) -> list[Claim]:
    """Map (Fact, EvidenceItem) pairs to Claims (1:1 by Fact).

    Every Fact is checked against an EvidenceItem keyed by `fact.ref`.
    A Fact that references a missing item raises CompileError — the
    caller's responsibility is to ensure the bundle's invariants hold
    (assert_invariants in agent/types.py).

    Returns claims in the input fact order (stable). claim_id is
    derived from input index, not from any property of the fact, so
    re-running the compiler on the same input produces the same ids.
    """
    items_by_ref: dict[int, EvidenceItem] = {it.source.ref: it for it in items}
    out: list[Claim] = []
    for i, fact in enumerate(facts, start=1):
        item = items_by_ref.get(fact.ref)
        if item is None:
            raise CompileError(
                f"fact references ref={fact.ref} but no EvidenceItem with that ref "
                f"was provided. fact.claim={fact.claim!r}"
            )
        out.append(Claim(
            claim_id=_claim_id_for(i),
            text=fact.claim,
            claim_type=_derive_claim_type(fact),  # type: ignore[arg-type]
            supporting_refs=(fact.ref,),
            opposing_refs=(),
            directness=_derive_directness(item),
            evidence_tier=item.tier,  # type: ignore[arg-type]
            confidence=_derive_confidence(item),
            attack_surface=(),  # populated by Day 4 thesis tournament
        ))
    return out


# --- compile_claim_graph --------------------------------------------------


_DIRECTNESS_RANK = {"direct": 0, "indirect": 1, "mechanistic": 2}
_TIER_RANK = {"A1": 0, "A2": 1, "B": 2, "C": 3, "mixed": 4}


def _union_find_clusters(claims: Sequence[Claim]) -> list[list[int]]:
    """Group claims by union-find over supporting_refs intersection."""
    parent = list(range(len(claims)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    refs = [set(c.supporting_refs) for c in claims]
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            if refs[i] & refs[j]:
                union(i, j)

    grouped: dict[int, list[int]] = {}
    for i in range(len(claims)):
        grouped.setdefault(find(i), []).append(i)
    return list(grouped.values())


def _cluster_sort_key(
    idx_list: list[int],
    claims: Sequence[Claim],
    canonical_refs: frozenset[int],
) -> tuple[int, int, int, int, int]:
    """Cluster preference order (Day 6.3 / 8.0 / 8.1):
      1. canonical-trial bonus — clusters containing a topic_pack
         canonical NCT win over non-canonical equally-tiered clusters.
      2. directness — direct beats indirect beats mechanistic.
      3. tier — A1 beats A2 beats B beats C.
      4. larger size wins.
      5. smallest min(ref) for determinism.
    """
    has_canonical = 0 if (
        not canonical_refs
        or any(
            r in canonical_refs
            for i in idx_list
            for r in claims[i].supporting_refs
        )
    ) else 1
    directness = min(
        _DIRECTNESS_RANK.get(claims[i].directness, 9) for i in idx_list
    )
    tier = min(_TIER_RANK.get(claims[i].evidence_tier, 9) for i in idx_list)
    return (
        has_canonical,
        directness,
        tier,
        -len(idx_list),
        min(min(claims[i].supporting_refs) for i in idx_list),
    )


def cluster_all_claims(
    claims: Sequence[Claim],
    *,
    canonical_refs: frozenset[int] = frozenset(),
) -> tuple[tuple[Claim, ...], ...]:
    """Return ALL coherent clusters, sorted best-first by the same key
    that `_largest_cohesive_cluster` uses to pick its winner.

    Day 10.8b: multi-receipt mode iterates every cluster, emitting one
    Proof 001 receipt per cluster so the synthesis layer has multiple
    distinct trial receipts to combine. Without this, a single run
    yields one receipt and the cross-source gate (≥3 unique trials)
    can never trip from one corpus.

    Fallback semantics match `_largest_cohesive_cluster`:
      - empty input → empty tuple (caller decides whether that's an error)
      - single claim → ((claim,),)
      - all singletons (no shared refs across any pair) → ((all_claims,),)
        because filtering to one singleton would arbitrarily drop the
        rest of the corpus, same logic as the legacy single-cluster fn.
    """
    if not claims:
        return ()
    if len(claims) == 1:
        return (tuple(claims),)

    raw_clusters = _union_find_clusters(claims)
    largest_size = max(len(idx_list) for idx_list in raw_clusters)
    if largest_size < 2:
        # All-singleton corpus: no clustering signal exists. Hand back
        # the full list as one cluster so the caller doesn't lose data.
        return (tuple(claims),)

    sorted_clusters = sorted(
        raw_clusters,
        key=lambda idx_list: _cluster_sort_key(idx_list, claims, canonical_refs),
    )
    return tuple(
        tuple(claims[i] for i in idx_list) for idx_list in sorted_clusters
    )


def _largest_cohesive_cluster(
    claims: Sequence[Claim],
    *,
    canonical_refs: frozenset[int] = frozenset(),
) -> tuple[Claim, ...]:
    """Group claims by source-paper overlap and return the best cluster.

    Day 10.8b: thin wrapper over `cluster_all_claims` — picks the
    first (highest-ranked) cluster. Behavior preserved from Day 6.3:
    when no cluster has ≥2 members, returns the full list untouched.
    """
    all_clusters = cluster_all_claims(claims, canonical_refs=canonical_refs)
    if not all_clusters:
        return ()
    return all_clusters[0]


def compile_claim_graph(
    claims: Sequence[Claim],
    *,
    items_by_ref: Mapping[int, EvidenceItem] | None = None,
    thesis_claim_id: str | None = None,
    cohesive_cluster_only: bool = True,
    canonical_refs: frozenset[int] = frozenset(),
) -> ClaimGraph:
    """Bundle Claims into a ClaimGraph with a chosen thesis spine.

    Day 3.2a left `edges` empty; Day 4 SPAR will populate `supports` /
    `contradicts` / `qualifies` / `mechanism_of` edges. The graph is
    structurally valid (per `assert_claim_graph_invariants`) regardless:
    thesis_claim_id must point at one of the claims, claim_ids unique.

    `thesis_claim_id` defaults to `agent.thesis_tournament.pick_thesis`
    (Day 4.1b wired in — replaced the old in-module 3-dim heuristic).
    Pass `items_by_ref` to enable the recency dimension in the tournament;
    omit when it's not available (e.g., synthetic test cases) and the
    tournament gracefully drops to 5 dims.

    `cohesive_cluster_only=True` (Day 6.3 default): keeps only the
    LARGEST topically-coherent cluster of claims (those that share
    source papers via union-find on supporting_refs). Drops the rest
    so the writer renders a focused artifact instead of a shotgun
    list of unrelated findings — see _largest_cohesive_cluster docstring.
    Set to False to preserve the legacy "render every claim" behavior
    (used by tests that assemble synthetic single-cluster inputs).
    """
    if not claims:
        raise CompileError("compile_claim_graph requires at least one claim")

    selected: tuple[Claim, ...] = (
        _largest_cohesive_cluster(claims, canonical_refs=canonical_refs)
        if cohesive_cluster_only else tuple(claims)
    )
    chosen = thesis_claim_id or pick_thesis(selected, items_by_ref=items_by_ref)
    graph = ClaimGraph(
        claims=selected,
        edges=(),
        thesis_claim_id=chosen,
    )
    # Re-run the schema invariant check so a bad explicit thesis_claim_id
    # surfaces before the graph escapes this module.
    assert_claim_graph_invariants(graph)
    return graph


def compile_per_cluster_claim_graphs(
    claims: Sequence[Claim],
    *,
    items_by_ref: Mapping[int, EvidenceItem] | None = None,
    canonical_refs: frozenset[int] = frozenset(),
) -> tuple[ClaimGraph, ...]:
    """Build one ClaimGraph per coherent cluster (Day 10.8b multi-receipt).

    Each cluster gets its own thesis pick and structural-invariant check,
    so downstream stages (citation_trace → SPAR → writer) treat each
    cluster as an independent atomic claim receipt.

    Returns clusters in the same order as `cluster_all_claims` (best first).
    Empty input raises CompileError, matching `compile_claim_graph`.
    """
    if not claims:
        raise CompileError(
            "compile_per_cluster_claim_graphs requires at least one claim"
        )
    clusters = cluster_all_claims(claims, canonical_refs=canonical_refs)
    if not clusters:
        raise CompileError("clustering produced no groups")
    graphs: list[ClaimGraph] = []
    for cluster_claims in clusters:
        chosen = pick_thesis(cluster_claims, items_by_ref=items_by_ref)
        g = ClaimGraph(
            claims=cluster_claims,
            edges=(),
            thesis_claim_id=chosen,
        )
        assert_claim_graph_invariants(g)
        graphs.append(g)
    return tuple(graphs)
