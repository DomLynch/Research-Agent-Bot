from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import audit_v06_paper as audit  # noqa: E402


def test_q8_accepts_current_picked_thesis_marker() -> None:
    paper = (
        "# Research Synthesis\n\n"
        "## Abstract\n\nAbstract prose.\n\n"
        "## What This Synthesis Adds\n\n"
        "**Picked thesis (Tournament selector):** Across the accepted "
        "receipts, the evidence base is mixed.\n"
    )
    ok, msg = audit._check_thesis_present(paper)
    assert ok, msg


def test_q8_accepts_public_section_backstop_thesis_marker() -> None:
    paper = (
        "## Introduction\n\n"
        "The deterministic thesis is: the evidence profile is mixed. "
        "This thesis is treated as an organizing claim.\n"
    )
    ok, msg = audit._check_thesis_present(paper)
    assert ok, msg


def test_q8_accepts_deterministic_thesis_content_without_marker() -> None:
    paper = (
        "## Conclusion\n\n"
        "Positive signals appear in cardiometabolic outcomes. "
        "Negative signals appear in adverse endpoints. "
        "The synthesis surfaces 363 non-orthogonal tensions across "
        "outcome classes, so the anti-aging case remains bounded.\n"
    )
    ok, msg = audit._check_thesis_present(paper)
    assert ok, msg
