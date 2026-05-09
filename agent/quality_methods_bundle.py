"""Phase 4 quality-methods bundle builder.

Combines validated RoB (RoB 2 / ROBINS-I / SYRCLE) + GRADE assessments
into a single markdown bundle plus the coverage metrics the final gate
consumes. Stdlib-only.

Coverage definitions:
  rob_coverage   = len(unique RoB study_ids) / receipt_count
  grade_coverage = len(unique GRADE outcomes) / outcome_count

Both values are clamped to [0, 1]. Receipt_count or outcome_count of 0
yields coverage 0.0 (fail-closed; the caller cannot divide by zero).
Missing RoB or GRADE payloads yield coverage 0.0 plus an explicit
"_No data provided._" placeholder in the markdown — the gate metric
fails closed but the renderer still produces a readable artifact.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent.grade_schema import GradeAssessment
from agent.risk_of_bias_schema import StudyAssessment
from scripts.render_quality_tables import (
    grades_from_json,
    render_grade_table,
    render_rob_table,
    studies_from_json,
)

__all__ = [
    "QualityMethodsBundle",
    "build_quality_methods_bundle",
    "compute_rob_coverage",
    "compute_grade_coverage",
]


@dataclass(frozen=True, slots=True)
class QualityMethodsBundle:
    """Output of the quality-methods bundle builder.

    rob_assessments    — validated RoB studies (frozen tuple).
    grade_assessments  — validated GRADE outcomes (frozen tuple).
    rob_coverage       — fraction of receipts with a RoB assessment, [0,1].
    grade_coverage     — fraction of outcome classes with a GRADE
                         assessment, [0,1].
    receipt_count      — denominator for rob_coverage.
    outcome_count      — denominator for grade_coverage.
    markdown           — combined RoB + GRADE markdown.
    """

    rob_assessments: tuple[StudyAssessment, ...]
    grade_assessments: tuple[GradeAssessment, ...]
    rob_coverage: float
    grade_coverage: float
    receipt_count: int
    outcome_count: int
    markdown: str

    def __post_init__(self) -> None:
        for name in ("rob_coverage", "grade_coverage"):
            value = getattr(self, name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be in [0,1], got {value}")
        if self.receipt_count < 0 or self.outcome_count < 0:
            raise ValueError("receipt_count and outcome_count must be ≥0")


def compute_rob_coverage(
    rob_assessments: Sequence[StudyAssessment], receipt_count: int
) -> float:
    """Coverage = unique-study-id count / receipt_count, clamped to [0,1]."""
    if receipt_count <= 0:
        return 0.0
    unique_ids = {s.study_id for s in rob_assessments}
    coverage = len(unique_ids) / receipt_count
    return min(1.0, max(0.0, coverage))


def compute_grade_coverage(
    grade_assessments: Sequence[GradeAssessment], outcome_count: int
) -> float:
    """Coverage = unique-outcome count / outcome_count, clamped to [0,1]."""
    if outcome_count <= 0:
        return 0.0
    unique_outcomes = {g.outcome for g in grade_assessments}
    coverage = len(unique_outcomes) / outcome_count
    return min(1.0, max(0.0, coverage))


def _render_rob_section(rob: Sequence[StudyAssessment]) -> str:
    if not rob:
        return "# Risk-of-Bias Summary\n\n_No RoB data provided._"
    return render_rob_table(rob)


def _render_grade_section(grade: Sequence[GradeAssessment]) -> str:
    if not grade:
        return "# GRADE Certainty Summary\n\n_No GRADE data provided._"
    return render_grade_table(grade)


def _combine_markdown(rob: Sequence[StudyAssessment], grade: Sequence[GradeAssessment]) -> str:
    """Stitch RoB + GRADE sections into one markdown document."""
    parts: list[str] = []
    parts.append("# Quality Methods Bundle")
    parts.append("")
    parts.append(_render_rob_section(rob))
    parts.append("")
    parts.append(_render_grade_section(grade))
    return "\n".join(parts)


def build_quality_methods_bundle(
    *,
    rob_payload: list[dict] | None = None,
    grade_payload: list[dict] | None = None,
    receipt_count: int,
    outcome_count: int,
) -> QualityMethodsBundle:
    """Validate JSON payloads, render markdown, compute coverage.

    Validation:
      - rob_payload (if provided) must conform to risk_of_bias_schema:
        each entry validates via StudyAssessment dataclass on construction.
        Invalid → ValueError propagates.
      - grade_payload (if provided) must conform to grade_schema:
        each entry validates via GradeAssessment dataclass on construction.
        Invalid → ValueError propagates.

    Coverage:
      - rob_coverage  = unique RoB study_ids / receipt_count
      - grade_coverage = unique GRADE outcomes / outcome_count
      - 0.0 when denominator is 0 or payload is empty (fail-closed for the gate).

    Markdown:
      - Always emits a top-level "# Quality Methods Bundle" header.
      - Missing RoB or GRADE payloads render explicit placeholders.
    """
    if receipt_count < 0 or outcome_count < 0:
        raise ValueError(
            f"receipt_count ({receipt_count}) and outcome_count "
            f"({outcome_count}) must be ≥0"
        )

    rob_assessments = (
        tuple(studies_from_json(rob_payload)) if rob_payload else tuple()
    )
    grade_assessments = (
        tuple(grades_from_json(grade_payload)) if grade_payload else tuple()
    )

    rob_coverage = compute_rob_coverage(rob_assessments, receipt_count)
    grade_coverage = compute_grade_coverage(grade_assessments, outcome_count)

    markdown = _combine_markdown(rob_assessments, grade_assessments)

    return QualityMethodsBundle(
        rob_assessments=rob_assessments,
        grade_assessments=grade_assessments,
        rob_coverage=rob_coverage,
        grade_coverage=grade_coverage,
        receipt_count=receipt_count,
        outcome_count=outcome_count,
        markdown=markdown,
    )
