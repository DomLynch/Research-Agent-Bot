"""Deterministic research-contribution scaffolds.

Builds a boundary-condition matrix, gap priorities, and next-study
scaffolds from structured manifest/claim/tension fields only. No LLM
calls, no topic branches, no novel scientific content.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class BoundaryCondition:
    outcome_class: str
    direct_receipts: int
    indirect_receipts: int
    mechanistic_receipts: int
    review_receipts: int
    effect_directions: tuple[str, ...]
    max_conflict_severity: int
    boundary: str

    @property
    def total_evidence(self) -> int:
        return (
            self.direct_receipts
            + self.indirect_receipts
            + self.mechanistic_receipts
            + self.review_receipts
        )


@dataclass(frozen=True, slots=True)
class GapPriority:
    outcome_class: str
    score: int
    gap_type: str
    rationale: str


@dataclass(frozen=True, slots=True)
class TrialDesignRecommendation:
    outcome_class: str
    endpoint_class: str
    recommendation: str
    fail_closed: bool


@dataclass(frozen=True, slots=True)
class NovelFrameworkProposal:
    title: str
    premise: str
    axes: tuple[str, ...]
    validation_status: str


def build_boundary_condition_matrix(
    manifest: Mapping[str, Any],
    *,
    claims: Iterable[Mapping[str, Any]] = (),
    tensions: Iterable[Any] = (),
) -> tuple[BoundaryCondition, ...]:
    rows = _evidence_rows(manifest, claims)
    if not rows:
        return ()
    severity = _max_severity_by_outcome(tensions)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["outcome_class"]].append(row)
    out: list[BoundaryCondition] = []
    for outcome, items in grouped.items():
        directness = Counter(i["directness"] for i in items)
        directions = tuple(sorted({i["effect_direction"] for i in items}))
        conflict = severity.get(outcome, 0)
        out.append(
            BoundaryCondition(
                outcome_class=outcome,
                direct_receipts=directness["direct"],
                indirect_receipts=directness["indirect"],
                mechanistic_receipts=directness["mechanistic"],
                review_receipts=directness["review"],
                effect_directions=directions or ("unclear",),
                max_conflict_severity=conflict,
                boundary=_boundary_label(directness, conflict, len(items)),
            )
        )
    return tuple(sorted(out, key=lambda r: r.outcome_class))


def rank_gap_priorities(
    matrix: Iterable[BoundaryCondition],
) -> tuple[GapPriority, ...]:
    gaps: list[GapPriority] = []
    for row in matrix:
        score = _gap_score(row)
        if score <= 0:
            continue
        gaps.append(
            GapPriority(
                outcome_class=row.outcome_class,
                score=score,
                gap_type=row.boundary,
                rationale=(
                    f"{row.direct_receipts} direct, "
                    f"{row.indirect_receipts + row.mechanistic_receipts + row.review_receipts} "
                    f"non-direct; conflict severity {row.max_conflict_severity}; "
                    f"directions: {', '.join(row.effect_directions)}"
                ),
            )
        )
    return tuple(sorted(gaps, key=lambda g: (-g.score, g.outcome_class)))


def build_trial_design_recommendation(
    gap: GapPriority,
    matrix: Iterable[BoundaryCondition],
    *,
    min_evidence: int = 3,
) -> TrialDesignRecommendation:
    row = next((r for r in matrix if r.outcome_class == gap.outcome_class), None)
    endpoint = _endpoint_class(gap.outcome_class)
    if row is None or row.total_evidence < min_evidence:
        return TrialDesignRecommendation(
            outcome_class=gap.outcome_class,
            endpoint_class=endpoint,
            recommendation=(
                "Insufficient structured evidence for a trial-design "
                "recommendation; expand the corpus before proposing a study."
            ),
            fail_closed=True,
        )
    if row.direct_receipts == 0:
        action = "prioritize a direct clinical design"
    elif row.max_conflict_severity >= 3:
        action = "prioritize a conflict-resolution design"
    else:
        action = "prioritize a replication design"
    return TrialDesignRecommendation(
        outcome_class=row.outcome_class,
        endpoint_class=endpoint,
        recommendation=(
            f"Next study should {action} using a pre-registered "
            f"{endpoint} endpoint class, separated safety/adherence capture, "
            "and explicit direct-vs-mechanistic endpoint separation."
        ),
        fail_closed=False,
    )


def propose_novel_framework(
    matrix: Iterable[BoundaryCondition],
    gaps: Iterable[GapPriority],
) -> NovelFrameworkProposal:
    rows = tuple(matrix)
    priorities = tuple(gaps)
    if len(rows) < 2 or not priorities:
        return NovelFrameworkProposal(
            title="Boundary-condition evidence map",
            premise="Insufficient structured evidence for a novel framework claim.",
            axes=(),
            validation_status="insufficient_structured_evidence",
        )
    return NovelFrameworkProposal(
        title="Boundary-condition evidence map",
        premise=(
            "The contribution is a deterministic map of where evidence "
            "changes meaning across directness, outcome class, effect "
            "direction, and conflict severity."
        ),
        axes=("outcome_class", "directness", "effect_direction", "conflict_severity"),
        validation_status="validated_scaffold",
    )


def _evidence_rows(
    manifest: Mapping[str, Any],
    claims: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in list(manifest.get("receipts") or []) + list(claims):
        if not isinstance(item, Mapping):
            continue
        outcome = _clean(item.get("outcome_class") or item.get("endpoint_class"))
        if not outcome:
            continue
        rows.append(
            {
                "outcome_class": outcome,
                "directness": _directness(item.get("directness")),
                "effect_direction": _clean(item.get("effect_direction")) or "unclear",
            }
        )
    return rows


def _max_severity_by_outcome(tensions: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in tensions:
        outcome = _clean(_get(item, "outcome_class"))
        if not outcome:
            continue
        severity = int(_get(item, "severity") or 0)
        out[outcome] = max(out.get(outcome, 0), severity)
    return out


def _boundary_label(counts: Counter[str], conflict: int, total: int) -> str:
    if total < 3:
        return "coverage gap"
    if conflict >= 3:
        return "conflict-resolution gap"
    if counts["direct"] == 0:
        return "directness gap"
    if counts["direct"] == 1:
        return "replication gap"
    return "mapped boundary"


def _gap_score(row: BoundaryCondition) -> int:
    score = 0
    if row.total_evidence < 3:
        score += 30
    if row.direct_receipts == 0:
        score += 40
    elif row.direct_receipts == 1:
        score += 15
    score += min(row.max_conflict_severity, 5) * 10
    if len(row.effect_directions) > 1:
        score += 5
    return score


def _endpoint_class(outcome_class: str) -> str:
    return outcome_class.replace("_", " ").strip() or "unspecified outcome"


def _directness(value: Any) -> str:
    directness = _clean(value)
    return (
        directness
        if directness in {"direct", "indirect", "mechanistic", "review"}
        else "indirect"
    )


def _clean(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _get(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


__all__ = [
    "BoundaryCondition",
    "GapPriority",
    "NovelFrameworkProposal",
    "TrialDesignRecommendation",
    "build_boundary_condition_matrix",
    "build_trial_design_recommendation",
    "propose_novel_framework",
    "rank_gap_priorities",
]
