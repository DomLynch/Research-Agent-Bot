"""Post-render journal surface gate.

Analytical certification proves traceability; this gate proves the
rendered manuscript does not expose obvious machine residue. It is
deterministic and topic-agnostic: endpoint text is mapped to broad
semantic classes, unit text to broad unit classes, then compatibility
is checked generically.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class SurfaceIssue:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    passed: bool
    issues: tuple[SurfaceIssue, ...]


_DASHES = {"", "-", "—", "–", "none", "n/a", "na"}
_BAD_ENDPOINTS = {"unknown", "background", "effect", "n/a", "none", "?"}
_PLACEHOLDER_PATTERNS = (
    "this paper evaluates the topic through accepted receipts",
    "the background is limited to corpus-supported context",
    "this synthesis aims to contribute to the field by",
    "the evidence base is limited to accepted receipts",
)


def evaluate_journal_surface(paper_md: str) -> SurfaceReport:
    """Return pass/fail for publication-surface sanity."""
    issues: list[SurfaceIssue] = []
    low = paper_md.lower()
    for pat in _PLACEHOLDER_PATTERNS:
        if pat in low:
            issues.append(SurfaceIssue("placeholder_prose", pat))
    for row in _extract_qei_rows(paper_md):
        for msg in qei_row_issue_messages(row):
            issues.append(SurfaceIssue("qei_surface", msg))
    return SurfaceReport(passed=not issues, issues=tuple(issues))


def is_publishable_qei_row(row: Any) -> bool:
    """Duck-typed check for EvidenceRow-like objects."""
    return not qei_row_issue_messages(_row_to_dict(row))


def qei_row_issue_messages(row: dict[str, str]) -> tuple[str, ...]:
    endpoint = _norm(row.get("endpoint", ""))
    value = _norm(row.get("value", ""))
    unit = _norm(row.get("unit_or_type", row.get("type", "")))
    stat = _norm(row.get("statistic", ""))
    study = row.get("study_label", row.get("study", "")).strip()
    issues: list[str] = []
    if endpoint in _BAD_ENDPOINTS:
        issues.append(f"unpublishable endpoint: {endpoint or 'blank'}")
    if value in _DASHES and unit in _DASHES and stat in _DASHES:
        issues.append(f"empty QEI row: {study or 'unknown study'}")
    if _malformed_study_id(study):
        issues.append(f"malformed study id: {study}")
    unit_class = _unit_class(unit, value)
    endpoint_class = _endpoint_class(endpoint)
    if endpoint_class and unit_class:
        allowed = _ALLOWED_UNIT_CLASSES[endpoint_class]
        if unit_class not in allowed:
            issues.append(
                f"endpoint/unit mismatch: {endpoint} cannot use {unit}",
            )
    return tuple(issues)


def _extract_qei_rows(paper_md: str) -> Iterable[dict[str, str]]:
    m = re.search(
        r"^## Quantitative Evidence Index\b.*?\n(.*?)(?=^## |\Z)",
        paper_md,
        flags=re.M | re.S,
    )
    if not m:
        return ()
    rows: list[dict[str, str]] = []
    for line in m.group(1).splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[:6] == ["Study", "Endpoint", "Arm", "Value", "Type", "Statistic"]:
            continue
        if len(cells) >= 6:
            rows.append({
                "study_label": cells[0], "endpoint": cells[1],
                "arm": cells[2], "value": cells[3],
                "unit_or_type": cells[4], "statistic": cells[5],
            })
    return tuple(rows)


def _row_to_dict(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        return {str(k): str(v) for k, v in row.items()}
    return {
        "study_label": str(getattr(row, "study_label", "")),
        "endpoint": str(getattr(row, "endpoint", "")),
        "arm": str(getattr(row, "arm", "")),
        "value": str(getattr(row, "value", "")),
        "unit_or_type": str(getattr(row, "unit_or_type", "")),
        "statistic": str(getattr(row, "statistic", "")),
    }


def _malformed_study_id(study: str) -> bool:
    if "_" not in study:
        return False
    return bool(re.search(r"(?:_\w{1,5}|_+)$", study))


def _endpoint_class(endpoint: str) -> str:
    checks = (
        ("event", ("mortality", "survival", "death", "incident")),
        ("pressure", ("blood pressure", "systolic", "diastolic")),
        ("bmi", ("body mass index", "bmi")),
        ("biomarker", (
            "glucose", "hba1c", "cholesterol", "ldl", "hdl",
            "triglyceride", "insulin", "crp", "biomarker",
        )),
        ("speed", ("walk speed", "gait speed", "walking speed")),
        ("mass", ("body weight", "lean mass", "fat mass", "muscle mass")),
        ("strength", ("strength", "grip", "force")),
        ("scale", ("frailty", "score", "index", "cognition")),
    )
    for cls, needles in checks:
        if any(n in endpoint for n in needles):
            return cls
    return ""


def _unit_class(unit: str, value: str) -> str:
    hay = f"{unit} {value}".lower()
    if unit in _DASHES:
        return ""
    if "sample size" in hay or re.search(r"\bn\s*=", hay):
        return "count"
    if "p value" in hay or re.search(r"\bp\s*[<=>]", hay):
        return "p_value"
    if "95%ci" in hay or "confidence interval" in hay:
        return "ci"
    if "hazard ratio" in hay or "odds ratio" in hay or "risk ratio" in hay:
        return "ratio"
    if "%" in hay or "percentage" in hay:
        return "percentage"
    if "kg/m2" in hay or "kg/m²" in hay:
        return "bmi_unit"
    if "mg/dl" in hay or "mmol/l" in hay or "ng/ml" in hay:
        return "concentration"
    if "mmhg" in hay:
        return "pressure"
    if "m/s" in hay:
        return "speed"
    if re.search(r"\b(years?|months?|weeks?|days?|hours?)\b", hay):
        return "duration"
    if re.search(r"\bcm\b", hay):
        return "length"
    if re.search(r"\bkg\b", hay):
        return "mass"
    if "mean sd" in hay:
        return "summary_stat"
    return ""


def _norm(s: str) -> str:
    return str(s or "").strip().lower().replace(" ", " ")


_COMMON = {"count", "p_value", "ci", "ratio", "percentage", "summary_stat"}
_ALLOWED_UNIT_CLASSES = {
    "event": _COMMON,
    "pressure": _COMMON | {"pressure"},
    "bmi": _COMMON | {"bmi_unit"},
    "biomarker": _COMMON | {"concentration"},
    "speed": _COMMON | {"speed"},
    "mass": _COMMON | {"mass"},
    "strength": _COMMON | {"mass"},
    "scale": _COMMON,
}


__all__ = [
    "SurfaceIssue",
    "SurfaceReport",
    "evaluate_journal_surface",
    "is_publishable_qei_row",
    "qei_row_issue_messages",
]
