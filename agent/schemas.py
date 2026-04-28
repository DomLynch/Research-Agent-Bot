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
    "GateOverride",
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
class GateOverride:
    """Records when the deterministic trace gate overrode the panel verdict.

    The LLM panel's votes are preserved verbatim in `SPARReview.reviews`;
    the panel's natural verdict is captured in `pre_gate_verdict`; the
    canonical `SPARReview.verdict` reflects the gate's decision (always
    a `reject_*` value when this is non-None).

    This exists because the Auditor's prompt instructs judges to reject
    on failed citation traces, but the deterministic spine cannot rely
    on LLM compliance — if all three judges vote accept while traces
    have failed, code must dispose.
    """

    pre_gate_verdict: SPARVerdict
    failed_trace_count: int
    rationale: str


@dataclass(frozen=True, slots=True)
class SPARReview:
    """Three role-bound agents + deterministic tie-break. Dissent always public.

    `dissent` is populated when verdict is `accept_caveated` or `reject_majority`
    (any 2-1 split); None for unanimous outcomes.

    `gate_override` is populated when the deterministic trace gate forced
    a reject_* verdict despite the panel's vote tally pointing at accept_*;
    None on the normal path.
    """

    submission_id: str
    reviews: tuple[JudgeReview, ...]
    verdict: SPARVerdict
    dissent: JudgeReview | None
    final_judge_resolution: str
    gate_override: GateOverride | None = None


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
    - **Verdict matches the votes**: review.verdict must equal
      `compute_spar_verdict(review.reviews)`. This is the consistency check
      that prevents stale or hand-edited verdicts from contradicting the
      published vote tally — a re-judging artifact would otherwise slip
      through and corrupt the audit trail.
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

    panel_verdict = compute_spar_verdict(review.reviews)
    if review.gate_override is None:
        # Normal path — verdict matches the panel's vote tally exactly.
        if review.verdict != panel_verdict:
            accepts = sum(1 for r in review.reviews if r.verdict == "accept")
            raise SPARInvariantError(
                f"SPARReview.verdict={review.verdict!r} contradicts the votes "
                f"({accepts} accepts / {3 - accepts} rejects → expected "
                f"{panel_verdict!r}). Hand-edited or stale verdict suspected."
            )
    else:
        # Gate-override path — panel pointed at accept_*, gate forced reject_*.
        # Both halves must hold or the override is structurally invalid.
        if review.gate_override.pre_gate_verdict != panel_verdict:
            raise SPARInvariantError(
                f"gate_override.pre_gate_verdict="
                f"{review.gate_override.pre_gate_verdict!r} does not match "
                f"the actual panel tally {panel_verdict!r}."
            )
        if panel_verdict not in ("accept_clean", "accept_caveated"):
            raise SPARInvariantError(
                f"gate_override only applies when the panel would have "
                f"accepted (got panel_verdict={panel_verdict!r})."
            )
        if review.verdict not in ("reject_majority", "reject_critical"):
            raise SPARInvariantError(
                f"gate_override must produce a reject_* verdict; "
                f"got {review.verdict!r}."
            )
        if review.gate_override.failed_trace_count <= 0:
            raise SPARInvariantError(
                f"gate_override.failed_trace_count must be > 0; "
                f"got {review.gate_override.failed_trace_count}."
            )
        if not review.gate_override.rationale.strip():
            raise SPARInvariantError(
                "gate_override.rationale must not be empty."
            )
        # On the gate path, dissent must be None — the gate itself is the
        # rejection signal, distinct from any panel-level minority voice.
        # The panel's underlying split/unanimous shape is preserved in
        # `pre_gate_verdict` for the audit trail; dissent semantics
        # only apply to the panel verdict, which the gate has overridden.
        if review.dissent is not None:
            raise SPARInvariantError(
                "gate_override path requires dissent=None — the panel's "
                "internal split is captured in pre_gate_verdict; the "
                "gate's rejection is not itself a panel vote."
            )
        return  # gate-override path complete; skip the panel-dissent rules

    is_split = review.verdict in ("accept_caveated", "reject_majority")
    if not is_split:
        if review.dissent is not None:
            raise SPARInvariantError(
                f"verdict={review.verdict!r} (unanimous) requires dissent=None"
            )
        return  # unanimous path complete

    # Split path — dissent must be populated AND must be the actual minority voice.
    if review.dissent is None:
        raise SPARInvariantError(
            f"verdict={review.verdict!r} (split) requires dissent to be populated"
        )
    if review.dissent not in review.reviews:
        raise SPARInvariantError(
            f"dissent must be one of the three reviews; got dissent with "
            f"judge_role={review.dissent.judge_role!r} not present in "
            f"reviews. Fabricated or copy-edited dissent suspected."
        )
    majority_verdict: JudgeVerdict = (
        "accept" if review.verdict == "accept_caveated" else "reject"
    )
    if review.dissent.verdict == majority_verdict:
        raise SPARInvariantError(
            f"dissent.verdict={review.dissent.verdict!r} matches the majority "
            f"({majority_verdict!r}); dissent must be the minority voice. "
            f"A majority review labelled as dissent corrupts the auditability trail."
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
