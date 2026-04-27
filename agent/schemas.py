"""Proof 001 schemas — the structured representation that IS the source of truth.

Stdlib only. All cross-stage objects are frozen dataclasses (slots=True).

`agent/types.py` keeps the V1 spine types (Source, EvidenceItem, Fact, ...).
This module is additive — new shapes that the claim-court pipeline introduces:
Claim, ClaimEdge, ClaimGraph, CitationTrace, JudgeReview, SPARReview.

Hard rule (also posted at top of compiler.py and every relevant prompt):
  LLM PROPOSES. CODE DISPOSES.
  - Role assignment: registry override > deterministic abstract classifier. Never LLM.
  - Fact identity: extracted by LLM, schema-validated, source-text-traced.
  - Claim membership in paper.md: gated by claim_graph.json. LLM cannot add claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "ClaimType",
    "Directness",
    "EvidenceTier",
    "Confidence",
    "EdgeKind",
    "TraceType",
    "JudgeRole",
    "JudgeVerdict",
    "SPARVerdict",
    "Claim",
    "ClaimEdge",
    "ClaimGraph",
    "CitationTrace",
    "JudgeReview",
    "SPARReview",
    "ClaimGraphInvariantError",
    "SPARInvariantError",
    "assert_claim_graph_invariants",
    "assert_spar_invariants",
    "compute_spar_verdict",
]

# --- Enums (Literal aliases) -----------------------------------------------

ClaimType = Literal["efficacy", "safety", "mechanism", "indirect", "context"]
Directness = Literal["direct", "indirect", "mechanistic"]
EvidenceTier = Literal["A1", "A2", "B", "mixed"]
Confidence = Literal["high", "moderate", "low"]
EdgeKind = Literal["supports", "qualifies", "contradicts", "mechanism_of"]
TraceType = Literal[
    "nct_exists",
    "percentage_in_text",
    "p_value_in_text",
    "alias_match",
    "role_match",
]
JudgeRole = Literal["evidence_auditor", "domain_skeptic", "final_judge"]
JudgeVerdict = Literal["accept", "reject"]
SPARVerdict = Literal[
    "accept_clean",
    "accept_caveated",
    "reject_majority",
    "reject_critical",
]


# --- Claim graph (the source of truth) -------------------------------------


@dataclass(frozen=True, slots=True)
class Claim:
    """One contestable claim. Cited by prose; never invented by it.

    `falsifiability` is populated for the thesis claim (winner of thesis
    tournament); empty tuple for supporting claims.
    """

    claim_id: str
    text: str
    claim_type: ClaimType
    supporting_refs: tuple[int, ...]
    opposing_refs: tuple[int, ...]
    directness: Directness
    evidence_tier: EvidenceTier
    confidence: Confidence
    attack_surface: tuple[str, ...]
    falsifiability: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClaimEdge:
    """Typed relationship between two claims in the graph."""

    from_claim: str
    to_claim: str
    kind: EdgeKind


@dataclass(frozen=True, slots=True)
class ClaimGraph:
    """The compiled set of claims + edges. `thesis_claim_id` is the spine."""

    claims: tuple[Claim, ...]
    edges: tuple[ClaimEdge, ...]
    thesis_claim_id: str


# --- Citation trace (the moat) ---------------------------------------------


@dataclass(frozen=True, slots=True)
class CitationTrace:
    """Result of one trace check on one (claim_id, ref) pair.

    Pass and fail are both written to the receipt — failure dashboard
    aggregates from these.
    """

    claim_id: str
    ref: int
    trace_type: TraceType
    passed: bool
    detail: str
    source_excerpt: str | None = None


# --- SPAR adjudication -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class JudgeReview:
    """One agent's verdict + rationale. Always published in the receipt."""

    judge_role: JudgeRole
    model: str
    verdict: JudgeVerdict
    score: int
    rationale: str
    flagged_claims: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SPARReview:
    """Three role-bound agents + deterministic tie-break. Dissent always public.

    `dissent` is populated when verdict is `accept_caveated` or `reject_majority`
    (any 2-1 split); None for unanimous outcomes.
    """

    submission_id: str
    reviews: tuple[JudgeReview, ...]
    verdict: SPARVerdict
    dissent: JudgeReview | None
    final_judge_resolution: str


# --- Invariants ------------------------------------------------------------


class ClaimGraphInvariantError(AssertionError):
    """Raised when a ClaimGraph violates structural invariants."""


class SPARInvariantError(AssertionError):
    """Raised when a SPARReview violates structural invariants."""


def assert_claim_graph_invariants(graph: ClaimGraph) -> None:
    """Verify ClaimGraph is structurally well-formed.

    - thesis_claim_id must exist in claims.
    - Every edge must reference real claim_ids on both ends.
    - Claim ids must be unique.
    """
    ids = [c.claim_id for c in graph.claims]
    id_set = set(ids)
    if len(ids) != len(id_set):
        raise ClaimGraphInvariantError(
            f"duplicate claim_ids: {[i for i in ids if ids.count(i) > 1]}"
        )
    if graph.thesis_claim_id not in id_set:
        raise ClaimGraphInvariantError(
            f"thesis_claim_id={graph.thesis_claim_id!r} not present in claims"
        )
    for edge in graph.edges:
        if edge.from_claim not in id_set:
            raise ClaimGraphInvariantError(
                f"edge.from_claim={edge.from_claim!r} not in claims"
            )
        if edge.to_claim not in id_set:
            raise ClaimGraphInvariantError(
                f"edge.to_claim={edge.to_claim!r} not in claims"
            )


def assert_spar_invariants(review: SPARReview) -> None:
    """Verify SPARReview is structurally well-formed.

    - Exactly 3 reviews (the locked Proof 001 cast).
    - The 3 judge_roles must be unique and cover {auditor, skeptic, final_judge}.
    - 2-1 verdicts MUST have dissent populated; unanimous MUST have dissent=None.
    - final_judge_resolution non-empty.
    """
    if len(review.reviews) != 3:
        raise SPARInvariantError(
            f"SPARReview must have exactly 3 reviews; got {len(review.reviews)}"
        )
    roles = {r.judge_role for r in review.reviews}
    expected = {"evidence_auditor", "domain_skeptic", "final_judge"}
    if roles != expected:
        raise SPARInvariantError(
            f"SPARReview roles must be exactly {expected}; got {roles}"
        )
    if not review.final_judge_resolution.strip():
        raise SPARInvariantError("final_judge_resolution must not be empty")

    is_split = review.verdict in ("accept_caveated", "reject_majority")
    if is_split and review.dissent is None:
        raise SPARInvariantError(
            f"verdict={review.verdict!r} (split) requires dissent to be populated"
        )
    if not is_split and review.dissent is not None:
        raise SPARInvariantError(
            f"verdict={review.verdict!r} (unanimous) requires dissent=None"
        )


def compute_spar_verdict(reviews: tuple[JudgeReview, ...]) -> SPARVerdict:
    """Deterministic tie-break — DESIGN-001 §8 table.

    | Vote        | Verdict           |
    |-------------|-------------------|
    | 3-0 accept  | accept_clean      |
    | 2-1 accept  | accept_caveated   |
    | 1-2 reject  | reject_majority   |
    | 0-3 reject  | reject_critical   |

    This is pure code — no LLM input. Called by spar.py to assign the verdict
    given the three judge votes.
    """
    if len(reviews) != 3:
        raise SPARInvariantError(
            f"compute_spar_verdict requires exactly 3 reviews; got {len(reviews)}"
        )
    accepts = sum(1 for r in reviews if r.verdict == "accept")
    if accepts == 3:
        return "accept_clean"
    if accepts == 2:
        return "accept_caveated"
    if accepts == 1:
        return "reject_majority"
    return "reject_critical"
