"""Deterministic tension-selection and paragraph-planning primitive.

Phase 7 of the WORLDCLASS rapamycin sprint. Stdlib-only, no LLM.

Selects the top-N tensions from a structured tension corpus by severity,
combined evidence weight, and directness; emits a deterministic paragraph
plan per selected tension. The plan names paper A, paper B, the numeric
anchors, the conflict type, two plausible hypotheses, and the corpus-
weight winner. Prose generation is a downstream concern; this layer is
the planning gate.

Hard rule: LLM PROPOSES, CODE DISPOSES. Hypotheses come from a fixed
registry keyed on conflict_type — they are not invented per call.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "TensionRecord",
    "TensionPlan",
    "DEFAULT_TOP_N",
    "HYPOTHESIS_REGISTRY",
    "DEFAULT_HYPOTHESES",
    "select_top_tensions",
    "build_plan",
]

DEFAULT_TOP_N: int = 5

_VALID_DIRECTNESS: frozenset[str] = frozenset(("direct", "indirect", "mechanistic"))

# Higher score = higher rank for selection.
_DIRECTNESS_RANK: Mapping[str, int] = {
    "direct": 2,
    "indirect": 1,
    "mechanistic": 0,
}

# Two plausible hypotheses per conflict type. Used verbatim by callers; the
# rewriter (a separate layer) may rephrase but cannot replace.
HYPOTHESIS_REGISTRY: Mapping[str, tuple[str, str]] = {
    "null_vs_positive": (
        "Effect is endpoint-distance dependent: positive at proximal endpoints, null at distal endpoints.",
        "Effect is population-stratified: detectable only in subgroups with elevated baseline pathway activity.",
    ),
    "disagreement": (
        "Dose-regime difference: intermittent vs chronic dosing produces qualitatively different effects.",
        "Co-intervention interaction: a concurrent intervention (e.g., exercise) modifies the drug effect.",
    ),
    "preclinical_vs_clinical": (
        "Translational dose mismatch: rodent dosing does not map onto human geroprotective dosing.",
        "Endpoint-translation gap: model-organism endpoints (lifespan) do not transfer to human surrogates.",
    ),
    "positive_vs_unclear": (
        "The unclear receipt is mechanistic-only and lacks a clinical-endpoint readout.",
        "Effect-direction noise dominates at the indirect endpoint; direct endpoints retain signal.",
    ),
    "null_vs_unclear": (
        "Both arms are consistent with no effect; reported difference is within measurement noise.",
        "Power is insufficient: a true small effect is masked by sample size or follow-up duration.",
    ),
}

# Fallback when conflict_type is not in the registry. Keeps the planning
# pipeline auditable rather than silently degrading.
DEFAULT_HYPOTHESES: tuple[str, str] = (
    "Population or dose-regime difference between the two studies modifies the effect.",
    "Endpoint-distance from pathway substrate explains the directional disagreement.",
)


@dataclass(frozen=True, slots=True)
class TensionRecord:
    """One cross-paper tension. Severity is 1-5 (5 = load-bearing).

    weight_a/weight_b: per-study evidence weights (e.g., from a tier ×
    directness rollup). Directness should be one of "direct" | "indirect"
    | "mechanistic"; the higher of the two arms drives selection rank."""

    tension_id: str
    paper_a: str
    paper_b: str
    conflict_type: str
    outcome_class: str
    severity: int
    weight_a: float = 1.0
    weight_b: float = 1.0
    directness_a: str = "direct"
    directness_b: str = "direct"
    numeric_anchors_a: tuple[str, ...] = ()
    numeric_anchors_b: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.tension_id:
            raise ValueError("tension_id must be a non-empty string")
        if not self.paper_a or not self.paper_b:
            raise ValueError("paper_a and paper_b must both be non-empty")
        if self.paper_a == self.paper_b:
            raise ValueError(
                f"paper_a and paper_b must differ; both = {self.paper_a!r}"
            )
        if not isinstance(self.severity, int) or not (1 <= self.severity <= 5):
            raise ValueError(f"severity must be int in 1..5, got {self.severity!r}")
        if self.weight_a < 0 or self.weight_b < 0:
            raise ValueError("weights must be non-negative")
        if self.directness_a not in _VALID_DIRECTNESS:
            raise ValueError(
                f"invalid directness_a {self.directness_a!r}; "
                f"must be one of {sorted(_VALID_DIRECTNESS)}"
            )
        if self.directness_b not in _VALID_DIRECTNESS:
            raise ValueError(
                f"invalid directness_b {self.directness_b!r}; "
                f"must be one of {sorted(_VALID_DIRECTNESS)}"
            )

    @property
    def total_weight(self) -> float:
        return self.weight_a + self.weight_b

    @property
    def best_directness_rank(self) -> int:
        return max(
            _DIRECTNESS_RANK[self.directness_a],
            _DIRECTNESS_RANK[self.directness_b],
        )


@dataclass(frozen=True, slots=True)
class TensionPlan:
    """Deterministic paragraph plan for one tension. The two hypotheses
    are drawn from HYPOTHESIS_REGISTRY (or DEFAULT_HYPOTHESES) keyed on
    conflict_type. The corpus_weight_winner names the higher-weight paper
    or 'tie' when weights are equal."""

    tension_id: str
    paper_a: str
    paper_b: str
    conflict_type: str
    outcome_class: str
    severity: int
    numeric_anchors: tuple[str, ...]
    hypotheses: tuple[str, str]
    corpus_weight_winner: str  # paper_a | paper_b | "tie"

    def __post_init__(self) -> None:
        if len(self.hypotheses) != 2:
            raise ValueError("hypotheses must be a 2-tuple")
        if self.corpus_weight_winner not in (self.paper_a, self.paper_b, "tie"):
            raise ValueError(
                f"corpus_weight_winner {self.corpus_weight_winner!r} must be "
                f"paper_a, paper_b, or 'tie'"
            )


def _selection_key(record: TensionRecord) -> tuple[int, float, int, str]:
    """Sort key — higher is better in the first three components, then
    lexicographic on tension_id for deterministic tie-breaking."""
    return (
        -record.severity,
        -record.total_weight,
        -record.best_directness_rank,
        record.tension_id,
    )


def select_top_tensions(
    records: Sequence[TensionRecord], *, top_n: int = DEFAULT_TOP_N
) -> list[TensionPlan]:
    """Select up to top_n tensions and emit deterministic paragraph plans.

    Sort order: severity DESC, total weight DESC, best directness DESC,
    tension_id ASC (final tie-break). Returns at most top_n plans; fewer
    when len(records) < top_n. Raises ValueError on duplicate tension_id."""
    if top_n <= 0:
        raise ValueError(f"top_n must be positive, got {top_n}")
    seen: set[str] = set()
    for r in records:
        if r.tension_id in seen:
            raise ValueError(f"duplicate tension_id: {r.tension_id!r}")
        seen.add(r.tension_id)
    ranked = sorted(records, key=_selection_key)
    return [build_plan(r) for r in ranked[:top_n]]


def build_plan(record: TensionRecord) -> TensionPlan:
    """Build a TensionPlan from a single TensionRecord. Hypotheses come
    from HYPOTHESIS_REGISTRY (fallback to DEFAULT_HYPOTHESES)."""
    hypotheses = HYPOTHESIS_REGISTRY.get(record.conflict_type, DEFAULT_HYPOTHESES)
    if record.weight_a > record.weight_b:
        winner = record.paper_a
    elif record.weight_b > record.weight_a:
        winner = record.paper_b
    else:
        winner = "tie"
    return TensionPlan(
        tension_id=record.tension_id,
        paper_a=record.paper_a,
        paper_b=record.paper_b,
        conflict_type=record.conflict_type,
        outcome_class=record.outcome_class,
        severity=record.severity,
        numeric_anchors=tuple(record.numeric_anchors_a) + tuple(record.numeric_anchors_b),
        hypotheses=hypotheses,
        corpus_weight_winner=winner,
    )
