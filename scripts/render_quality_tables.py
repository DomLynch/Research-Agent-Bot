"""Deterministic markdown renderers for RoB and GRADE tables.

Phase 4 of the WORLDCLASS rapamycin sprint. Stdlib-only.

Provides:
  - render_rob_table(studies)     -> traffic-light per-domain RoB table.
  - render_grade_table(grades)    -> per-outcome GRADE certainty summary.

Symbol legend (text-only, no emojis):
  L = low risk          S = some concerns
  H = high risk         ? = unclear / not assessed

CLI:
  python scripts/render_quality_tables.py --rob rob.json --grade grade.json \\
      [--rob-out rob_table.md] [--grade-out grade_table.md]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.grade_schema import (  # noqa: E402
    DowngradeAdjustment,
    GradeAssessment,
    UpgradeAdjustment,
)
from agent.risk_of_bias_schema import (  # noqa: E402
    DOMAINS_BY_TOOL,
    DomainAssessment,
    StudyAssessment,
    assert_studies_unique,
)

__all__ = [
    "RATING_SYMBOLS",
    "render_rob_table",
    "render_grade_table",
    "studies_from_json",
    "grades_from_json",
]

RATING_SYMBOLS: Mapping[str, str] = {
    "low": "L",
    "some_concerns": "S",
    "high": "H",
    "unclear": "?",
}


def _md_escape(value: str) -> str:
    """Escape `|` and newlines so cell content does not break the table."""
    return value.replace("|", "\\|").replace("\n", " ")


def render_rob_table(studies: Iterable[StudyAssessment]) -> str:
    """Render a Cochrane-style traffic-light RoB table.

    Columns: Study | Tool | <each domain in canonical order> | Overall.
    Studies are grouped by tool; one table block per tool used in the input.
    """
    studies = list(studies)
    assert_studies_unique(studies)
    by_tool: dict[str, list[StudyAssessment]] = {}
    for s in studies:
        by_tool.setdefault(s.tool, []).append(s)

    out: list[str] = []
    out.append("# Risk-of-Bias Summary")
    out.append("")
    out.append("**Symbols:** L = low, S = some concerns, H = high, ? = unclear.")
    out.append("")
    if not studies:
        out.append("_No studies provided._")
        return "\n".join(out) + "\n"

    for tool in sorted(by_tool):
        domains = DOMAINS_BY_TOOL[tool]
        out.append(f"## {tool.upper()}")
        out.append("")
        header = ["Study", "Tool"] + list(domains) + ["Overall"]
        out.append("| " + " | ".join(header) + " |")
        out.append("| " + " | ".join("---" for _ in header) + " |")
        for s in by_tool[tool]:
            domain_map = s.domain_map()
            row: list[str] = [_md_escape(s.study_id), tool]
            for d in domains:
                rating = domain_map[d]
                row.append(RATING_SYMBOLS[rating])
            row.append(RATING_SYMBOLS[s.overall_rating])
            out.append("| " + " | ".join(row) + " |")
        out.append("")
    return "\n".join(out)


def render_grade_table(grades: Iterable[GradeAssessment]) -> str:
    """Render a GRADE summary-of-findings table.

    Columns: Outcome | Starting | Downgrades | Upgrades | Final certainty.
    """
    grades = list(grades)
    out: list[str] = []
    out.append("# GRADE Certainty Summary")
    out.append("")
    if not grades:
        out.append("_No outcomes provided._")
        return "\n".join(out) + "\n"

    out.append("| Outcome | Starting | Downgrades | Upgrades | Final |")
    out.append("| --- | --- | --- | --- | --- |")
    for g in grades:
        downgrade_text = (
            ", ".join(f"{d.reason}(-{d.levels})" for d in g.downgrades) or "—"
        )
        upgrade_text = (
            ", ".join(f"{u.reason}(+{u.levels})" for u in g.upgrades) or "—"
        )
        out.append(
            "| "
            + " | ".join([
                _md_escape(g.outcome),
                g.starting_certainty,
                _md_escape(downgrade_text),
                _md_escape(upgrade_text),
                g.final_certainty,
            ])
            + " |"
        )
    out.append("")
    return "\n".join(out)


def studies_from_json(payload: list[dict]) -> list[StudyAssessment]:
    """Parse a JSON list into StudyAssessment instances. Raises ValueError on
    invalid input via dataclass validators."""
    studies: list[StudyAssessment] = []
    for raw in payload:
        domain_records = raw.get("domains", [])
        domains = tuple(
            DomainAssessment(
                domain=str(d["domain"]),
                rating=d["rating"],
                rationale=str(d.get("rationale", "")),
            )
            for d in domain_records
        )
        studies.append(StudyAssessment(
            study_id=str(raw["study_id"]),
            design=raw["design"],
            tool=raw["tool"],
            domains=domains,
            overall_rating=raw["overall_rating"],
            notes=str(raw.get("notes", "")),
        ))
    return studies


def grades_from_json(payload: list[dict]) -> list[GradeAssessment]:
    """Parse a JSON list into GradeAssessment instances."""
    grades: list[GradeAssessment] = []
    for raw in payload:
        downgrades = tuple(
            DowngradeAdjustment(
                reason=d["reason"],
                levels=int(d["levels"]),
                rationale=str(d.get("rationale", "")),
            )
            for d in raw.get("downgrades", [])
        )
        upgrades = tuple(
            UpgradeAdjustment(
                reason=u["reason"],
                levels=int(u["levels"]),
                rationale=str(u.get("rationale", "")),
            )
            for u in raw.get("upgrades", [])
        )
        grades.append(GradeAssessment(
            outcome=str(raw["outcome"]),
            starting_certainty=raw["starting_certainty"],
            downgrades=downgrades,
            upgrades=upgrades,
            notes=str(raw.get("notes", "")),
        ))
    return grades


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render RoB + GRADE markdown tables.")
    parser.add_argument("--rob", help="JSON file with list of study assessments.")
    parser.add_argument("--grade", help="JSON file with list of GRADE outcomes.")
    parser.add_argument("--rob-out", default=None, help="Output path for RoB table (markdown).")
    parser.add_argument("--grade-out", default=None, help="Output path for GRADE table.")
    args = parser.parse_args(argv)

    if not args.rob and not args.grade:
        parser.error("at least one of --rob or --grade is required")

    if args.rob:
        rob_payload = json.loads(Path(args.rob).read_text(encoding="utf-8"))
        rob_md = render_rob_table(studies_from_json(rob_payload))
        if args.rob_out:
            Path(args.rob_out).write_text(rob_md, encoding="utf-8")
        else:
            sys.stdout.write(rob_md)

    if args.grade:
        grade_payload = json.loads(Path(args.grade).read_text(encoding="utf-8"))
        grade_md = render_grade_table(grades_from_json(grade_payload))
        if args.grade_out:
            Path(args.grade_out).write_text(grade_md, encoding="utf-8")
        else:
            sys.stdout.write(grade_md)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
