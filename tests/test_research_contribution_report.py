from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import research_contribution_report as report  # noqa: E402


def _manifest() -> dict:
    return {
        "receipts": [
            {
                "outcome_class": "mobility",
                "directness": "direct",
                "effect_direction": "positive",
            },
            {
                "outcome_class": "mobility",
                "directness": "indirect",
                "effect_direction": "null",
            },
            {
                "outcome_class": "immune",
                "directness": "mechanistic",
                "effect_direction": "positive",
            },
        ],
    }


def test_report_renders_boundary_gap_recommendation_and_framework() -> None:
    md = report.render_research_contribution_report(
        _manifest(),
        claims=(
            {
                "outcome_class": "immune",
                "directness": "review",
                "effect_direction": "mixed",
            },
            {
                "outcome_class": "immune",
                "directness": "indirect",
                "effect_direction": "null",
            },
        ),
        tensions=({"outcome_class": "immune", "severity": 5},),
    )

    assert "### Boundary-Condition Matrix" in md
    assert "| immune | 0 | 1 | 1 | 1 |" in md
    assert "### Gap Priority" in md
    assert "| 1 | immune |" in md
    assert "### Trial-Design Recommendation" in md
    assert "pre-registered immune endpoint class" in md
    assert "### Novel Framework Proposal" in md
    assert "validated_scaffold" in md


def test_report_fails_closed_when_no_structured_evidence() -> None:
    md = report.render_research_contribution_report({})

    assert "insufficient_structured_evidence" in md
    assert "Fail closed: `True`" in md
    assert "expand structured evidence before proposing a study" in md


def test_report_does_not_generate_scientific_numeric_units() -> None:
    md = report.render_research_contribution_report(_manifest())

    forbidden_numeric_units = (
        r"\b\d+(?:\.\d+)?\s*%",
        r"\b\d+(?:\.\d+)?\s*mg\b",
        r"\bp\s*[<=>]\s*0?\.\d+",
        r"\bhr\s*[=:]\s*\d",
        r"\brr\s*[=:]\s*\d",
        r"\bor\s*[=:]\s*\d",
    )
    assert not any(
        re.search(pattern, md.lower()) for pattern in forbidden_numeric_units
    )


def test_report_has_no_topic_specific_python() -> None:
    source = inspect.getsource(report).lower()
    forbidden = (
        "metformin",
        "rapamycin",
        "glp1",
        "statins",
        "omega3",
        "creatine",
        "if topic",
    )

    assert not any(needle in source for needle in forbidden)
