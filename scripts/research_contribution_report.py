"""Markdown renderer for deterministic research-contribution scaffolds."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from novel_framework import (
    build_boundary_condition_matrix,
    build_trial_design_recommendation,
    propose_novel_framework,
    rank_gap_priorities,
)


def render_research_contribution_report(
    manifest: Mapping[str, Any],
    *,
    claims: Iterable[Mapping[str, Any]] = (),
    tensions: Iterable[Any] = (),
) -> str:
    matrix = build_boundary_condition_matrix(
        manifest,
        claims=claims,
        tensions=tensions,
    )
    gaps = rank_gap_priorities(matrix)
    proposal = propose_novel_framework(matrix, gaps)
    lines = [
        "## Research Contribution Scaffold",
        "",
        "This scaffold is deterministic and uses only structured evidence fields.",
        "",
        "### Boundary-Condition Matrix",
        "",
        "| Outcome class | Direct | Indirect | Mechanistic | Review | Directions | Conflict | Boundary |",
        "|---|---:|---:|---:|---:|---|---:|---|",
    ]
    if matrix:
        for row in matrix:
            lines.append(
                f"| {row.outcome_class} | {row.direct_receipts} | "
                f"{row.indirect_receipts} | {row.mechanistic_receipts} | "
                f"{row.review_receipts} | {', '.join(row.effect_directions)} | "
                f"{row.max_conflict_severity} | {row.boundary} |"
            )
    else:
        lines.append(
            "| insufficient_structured_evidence | 0 | 0 | 0 | 0 | unclear | 0 | coverage gap |"
        )
    lines += [
        "",
        "### Gap Priority",
        "",
        "| Rank | Outcome class | Score | Gap | Rationale |",
        "|---:|---|---:|---|---|",
    ]
    if gaps:
        for idx, gap in enumerate(gaps, 1):
            lines.append(
                f"| {idx} | {gap.outcome_class} | {gap.score} | "
                f"{gap.gap_type} | {gap.rationale} |"
            )
    else:
        lines.append(
            "| 1 | insufficient_structured_evidence | 0 | coverage gap | expand structured evidence before ranking gaps |"
        )
    lines += ["", "### Trial-Design Recommendation", ""]
    if gaps:
        recommendation = build_trial_design_recommendation(gaps[0], matrix)
        lines.append(f"- Outcome class: `{recommendation.outcome_class}`")
        lines.append(f"- Endpoint class: `{recommendation.endpoint_class}`")
        lines.append(f"- Fail closed: `{recommendation.fail_closed}`")
        lines.append(f"- Recommendation: {recommendation.recommendation}")
    else:
        lines.append("- Fail closed: `True`")
        lines.append(
            "- Recommendation: expand structured evidence before proposing a study."
        )
    lines += [
        "",
        "### Novel Framework Proposal",
        "",
        f"- Title: {proposal.title}",
        f"- Validation: `{proposal.validation_status}`",
        f"- Axes: {', '.join(proposal.axes) if proposal.axes else 'none'}",
        f"- Premise: {proposal.premise}",
        "",
    ]
    return "\n".join(lines)


__all__ = ["render_research_contribution_report"]
