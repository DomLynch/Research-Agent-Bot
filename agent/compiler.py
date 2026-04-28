"""Compiler — facts → Claims → ClaimGraph.

Hard rule (printed at the top of every prompt that touches the trust spine):
  LLM PROPOSES. CODE DISPOSES.
  - Role assignment: registry override > deterministic abstract classifier. Never LLM.
  - Fact identity: extracted by LLM, schema-validated, source-text-traced.
  - Claim membership in paper.md: gated by claim_graph.json. LLM cannot add claims.

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


def _largest_cohesive_cluster(
    claims: Sequence[Claim],
    *,
    canonical_refs: frozenset[int] = frozenset(),
) -> tuple[Claim, ...]:
    """Group claims by their source paper(s) and return the largest cluster.

    Day 6.3: a heterogeneous live corpus produces claims from disparate
    papers (PRT muscle / AMD / longevity). Rendering all of them in one
    artifact yields the "shotgun" pattern SPAR correctly rejects on
    coherence. The fix: build the artifact from the LARGEST topically-
    coherent cluster — claims that share source papers — so the writer
    has a cohesive story to tell.

    Algorithm: union-find over `supporting_refs`. Two claims are in the
    same cluster iff their supporting_refs sets intersect (they share
    one source paper). The cluster with the most members wins; ties
    broken by smallest min(supporting_refs) so the choice is
    deterministic regardless of input order.

    Activation rule: filter only kicks in when at least one cluster has
    ≥2 members. With all-singleton clusters (each claim from its own
    paper, no overlap), filtering would arbitrarily drop everything but
    one — that scenario has no shotgun risk to begin with, so leave the
    claim list untouched.
    """
    if len(claims) <= 1:
        return tuple(claims)

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

    clusters: dict[int, list[int]] = {}
    for i in range(len(claims)):
        clusters.setdefault(find(i), []).append(i)

    largest_size = max(len(idx_list) for idx_list in clusters.values())
    if largest_size < 2:
        # No paper has multiple claims; activating the filter would
        # arbitrarily drop most of the corpus to keep one singleton.
        return tuple(claims)

    # Day 6.3 / 8.0 / 8.1: cluster preference order:
    #   1. canonical-trial bonus — clusters containing a topic_pack
    #      canonical NCT win over equally-tiered non-canonical clusters.
    #      Without this, two A1 direct papers tie on directness+tier and
    #      the smallest-ref tiebreaker is fragile (Day 8 Proof 001
    #      regression: a non-canonical metformin paper out-tied MASTERS
    #      because the LLM happened to extract one extra fact for it).
    #   2. directness — direct beats mechanistic (V1.1 mechanism-to-clinic
    #      failure mode caught at the cluster level)
    #   3. tier — A1 beats A2 beats B beats C. Topic packs pin oncology /
    #      transplant evidence to tier B; without this rank, an everolimus
    #      run picks the 4-claim renal-cell-carcinoma RCT cluster over
    #      the 1-claim PROTECTOR aging RCT.
    #   4. larger size wins.
    #   5. smallest min(ref) for determinism.
    _DIRECTNESS_RANK = {"direct": 0, "indirect": 1, "mechanistic": 2}
    _TIER_RANK = {"A1": 0, "A2": 1, "B": 2, "C": 3, "mixed": 4}

    def cluster_has_canonical(idx_list: list[int]) -> int:
        """0 when the cluster contains a canonical-trial ref, else 1."""
        if not canonical_refs:
            return 0  # no pack data — neutral
        for i in idx_list:
            if any(r in canonical_refs for r in claims[i].supporting_refs):
                return 0
        return 1

    def cluster_directness(idx_list: list[int]) -> int:
        return min(
            _DIRECTNESS_RANK.get(claims[i].directness, 9) for i in idx_list
        )

    def cluster_tier(idx_list: list[int]) -> int:
        return min(
            _TIER_RANK.get(claims[i].evidence_tier, 9) for i in idx_list
        )

    def cluster_sort_key(idx_list: list[int]) -> tuple[int, int, int, int, int]:
        return (
            cluster_has_canonical(idx_list),  # 1: canonical-trial cluster wins
            cluster_directness(idx_list),     # 2: direct beats mechanistic
            cluster_tier(idx_list),           # 3: A1 beats A2 beats B
            -len(idx_list),                   # 4: more claims wins
            min(min(claims[i].supporting_refs) for i in idx_list),  # tiebreak
        )

    best_indices = min(clusters.values(), key=cluster_sort_key)
    # Day 8.0: the earlier "fall back to largest if winner is singleton"
    # rule was too aggressive — it overrode a direct A1 singleton with
    # an indirect B 5-claim cluster on the everolimus run, exactly the
    # signal-vs-volume failure mode the directness+tier ranks were
    # meant to fix. Trust the sort: a strong singleton outranks weaker
    # body. Empty graphs are still impossible because the largest_size<2
    # guard above returns the full list when no cluster has ≥2 members.
    return tuple(claims[i] for i in best_indices)


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
