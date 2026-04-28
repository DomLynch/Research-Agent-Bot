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


def compile_claim_graph(
    claims: Sequence[Claim],
    *,
    items_by_ref: Mapping[int, EvidenceItem] | None = None,
    thesis_claim_id: str | None = None,
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
    """
    if not claims:
        raise CompileError("compile_claim_graph requires at least one claim")
    chosen = thesis_claim_id or pick_thesis(claims, items_by_ref=items_by_ref)
    graph = ClaimGraph(
        claims=tuple(claims),
        edges=(),
        thesis_claim_id=chosen,
    )
    # Re-run the schema invariant check so a bad explicit thesis_claim_id
    # surfaces before the graph escapes this module.
    assert_claim_graph_invariants(graph)
    return graph
