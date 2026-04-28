"""Thesis tournament — 6-dim deterministic selector.

Replaces the temporary `compiler._pick_thesis` heuristic (3-dim:
directness / tier / confidence) with a broader scorer that incorporates
evidence-density signals (replication, recency, specificity) plus the
basic shape ranks. Day 4.1b wires this into `compiler.compile_claim_graph`.

Why deterministic and not LLM-based: thesis selection is a categorical
decision over a small candidate set; the LLM JUDGE in SPAR (Day 4.2)
provides the adversarial second opinion, and the writer is gated by
the resulting claim_graph.json. Letting the LLM pick the thesis would
re-introduce the V1.1 failure mode where the LLM contradicts typed
metadata.

Six dimensions (each ranked smaller-is-better, then combined into a
sort tuple, plus claim_id as deterministic tiebreaker):

  1. directness    — direct (0) < indirect (1) < mechanistic (2)
  2. tier          — A1 (0) < A2 (1) < B (2) < C (3) < mixed (4)
  3. confidence    — high (0) < moderate (1) < low (2)
  4. replication   — -len(supporting_refs); more refs → lower → better
  5. recency       — baseline_year - latest_supporting_year; newer → lower
  6. specificity   — -word_count(claim_text); longer → lower (proxy for
                     more-specific claim, capped at 50 to discourage
                     run-on-sentence gaming)

The dimension order is the priority order. Ties within a dimension fall
to the next; ultimate tiebreak is `claim_id` ascending. `pick_thesis`
returns the chosen `claim_id`; `score_all` exposes per-claim scores for
audit logs and for SPAR to consume in Day 4.2.

`items_by_ref` is optional: when None, the recency dimension contributes
0 (neutral) and the tournament still produces a defensible thesis from
the other five. The integrated path (Day 4.1b) always passes items.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent.schemas import Claim, Confidence, Directness, EvidenceTier
from agent.types import EvidenceItem

__all__ = [
    "ThesisScore",
    "ThesisTournamentError",
    "pick_thesis",
    "score_claim",
    "score_all",
]


class ThesisTournamentError(ValueError):
    """Raised when the tournament cannot produce a thesis (e.g., empty input)."""


_DIRECTNESS_RANK: Mapping[Directness, int] = {
    "direct": 0, "indirect": 1, "mechanistic": 2,
}
_TIER_RANK: Mapping[EvidenceTier, int] = {
    "A1": 0, "A2": 1, "B": 2, "C": 3, "mixed": 4,
}
_CONFIDENCE_RANK: Mapping[Confidence, int] = {
    "high": 0, "moderate": 1, "low": 2,
}

# Recency baseline: claims supported by papers in the last few years
# get rank 0; older papers contribute a positive delta. Far-future
# (data error) capped at 0 so a paper "from 2030" doesn't unfairly beat
# one from the actual current year.
_RECENCY_BASELINE_YEAR = 2026

# Specificity proxy cap: longer claim text usually means more specific
# (effect size, endpoint, population). Cap at 50 words so a verbose
# but unsupported claim doesn't game its way to the top.
_SPECIFICITY_WORD_CAP = 50


@dataclass(frozen=True, slots=True)
class ThesisScore:
    """Per-claim score with all 6 dimensions exposed for audit.

    Each rank is smaller-is-better. The full `sort_tuple` includes the
    six ranks plus the `claim_id` as deterministic tiebreaker.
    """
    claim_id: str
    directness: int
    tier: int
    confidence: int
    replication: int
    recency: int
    specificity: int

    @property
    def sort_tuple(self) -> tuple[int, int, int, int, int, int, str]:
        return (
            self.directness, self.tier, self.confidence,
            self.replication, self.recency, self.specificity,
            self.claim_id,
        )


def _replication_rank(claim: Claim) -> int:
    """More supporting refs is better. Negate so smaller-is-better holds."""
    return -len(claim.supporting_refs)


def _recency_rank(
    claim: Claim,
    items_by_ref: Mapping[int, EvidenceItem] | None,
) -> int:
    """`baseline_year - latest_supporting_year`. Newer evidence → lower rank.

    Returns 0 when items_by_ref is None or no supporting ref has a known
    year — the dimension contributes nothing rather than crashing the
    sort. A claim with sparse year data falls back to the other five.
    """
    if items_by_ref is None:
        return 0
    years: list[int] = []
    for ref in claim.supporting_refs:
        item = items_by_ref.get(ref)
        if item is None or item.source.year is None:
            continue
        years.append(item.source.year)
    if not years:
        return 0
    latest = max(years)
    return max(0, _RECENCY_BASELINE_YEAR - latest)


def _specificity_rank(claim: Claim) -> int:
    """Word count of claim text as proxy for specificity, capped at 50.
    Longer (up to cap) → more specific → lower rank → better thesis."""
    word_count = min(len(claim.text.split()), _SPECIFICITY_WORD_CAP)
    return -word_count


def score_claim(
    claim: Claim,
    items_by_ref: Mapping[int, EvidenceItem] | None = None,
) -> ThesisScore:
    """Compute the 6-dim score for one claim. Pure function."""
    return ThesisScore(
        claim_id=claim.claim_id,
        directness=_DIRECTNESS_RANK.get(claim.directness, 9),
        tier=_TIER_RANK.get(claim.evidence_tier, 9),
        confidence=_CONFIDENCE_RANK.get(claim.confidence, 9),
        replication=_replication_rank(claim),
        recency=_recency_rank(claim, items_by_ref),
        specificity=_specificity_rank(claim),
    )


def score_all(
    claims: Sequence[Claim],
    items_by_ref: Mapping[int, EvidenceItem] | None = None,
) -> list[ThesisScore]:
    """Score every claim. Order matches input claims order — Day 4.2 SPAR
    expects this for its audit log alignment."""
    return [score_claim(c, items_by_ref) for c in claims]


def pick_thesis(
    claims: Sequence[Claim],
    *,
    items_by_ref: Mapping[int, EvidenceItem] | None = None,
) -> str:
    """Select the strongest defensible thesis. Returns the chosen claim_id.

    Raises ThesisTournamentError when no claims are provided —
    `compile_claim_graph` already guards against empty input upstream,
    so this path is defense-in-depth.
    """
    if not claims:
        raise ThesisTournamentError(
            "cannot pick thesis from empty claim list"
        )
    return min(score_all(claims, items_by_ref), key=lambda s: s.sort_tuple).claim_id
