"""Markdown renderers for methods/evidence scaffold tables.

Pure scaffold/render code: no I/O, no topic hardcoding, no pipeline wiring.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from grade_assessment import assess_grade_batch
from risk_of_bias import SCREENING_LABEL, assess_risk_of_bias_batch

CAVEAT_LINE = (
    "Caveat: derived screening, not a full Cochrane RoB 2 signaling "
    "questionnaire."
)
GRADE_LITE_CAVEAT = (
    "Caveat: conservative GRADE-lite scaffold, not a full GRADE evidence "
    "profile."
)


def group_receipts_by_outcome(
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        grouped[_field(receipt, "outcome", "outcome_class", default="unknown")].append(
            receipt
        )
    return {k: tuple(v) for k, v in sorted(grouped.items())}


def render_rob_screening_table(
    receipts_by_outcome: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    batches = assess_risk_of_bias_batch(receipts_by_outcome)
    lines = [
        "## Risk of Bias Derived Screening",
        "",
        CAVEAT_LINE,
        "",
        _row("Outcome", "Receipt", "Overall", "Basis", "Fail-closed", "Label"),
        _row("---", "---", "---", "---", "---", "---"),
    ]
    for outcome, assessments in batches.items():
        receipts = receipts_by_outcome.get(outcome, ())
        for i, assessment in enumerate(assessments):
            receipt = receipts[i] if i < len(receipts) else {}
            lines.append(_row(
                outcome,
                _receipt_id(receipt, i),
                assessment.overall,
                "; ".join(assessment.basis),
                str(assessment.fail_closed).lower(),
                SCREENING_LABEL,
            ))
    return "\n".join(lines) + "\n"


def render_grade_lite_table(
    receipts_by_outcome: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    grades = assess_grade_batch(receipts_by_outcome)
    lines = [
        "## Conservative GRADE-lite Outcome Certainty",
        "",
        GRADE_LITE_CAVEAT,
        "",
        _row("Outcome", "Certainty", "Start", "Downgrades", "Caps", "Fail-closed"),
        _row("---", "---", "---", "---", "---", "---"),
    ]
    for grade in grades:
        lines.append(_row(
            grade.outcome,
            grade.certainty,
            grade.start_certainty,
            "; ".join(grade.downgrades) or "none",
            "; ".join(grade.caps) or "none",
            str(grade.fail_closed).lower(),
        ))
    return "\n".join(lines) + "\n"


def _receipt_id(receipt: Mapping[str, Any], index: int) -> str:
    return _field(receipt, "receipt_id", "id", "citation", default=f"receipt_{index + 1}")


def _field(receipt: Mapping[str, Any], *keys: str, default: str) -> str:
    for key in keys:
        value = receipt.get(key)
        if value not in (None, ""):
            return str(value)
    metadata = receipt.get("metadata")
    if isinstance(metadata, Mapping):
        for key in keys:
            value = metadata.get(key)
            if value not in (None, ""):
                return str(value)
    return default


def _row(*cells: str) -> str:
    escaped = [
        str(cell)
        .replace("\r", "")
        .replace("\n", " ")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .strip()
        for cell in cells
    ]
    return "| " + " | ".join(escaped) + " |"
