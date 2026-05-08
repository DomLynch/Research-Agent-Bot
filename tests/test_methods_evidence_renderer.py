from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from methods_evidence_renderer import (  # noqa: E402
    CAVEAT_LINE,
    GRADE_LITE_CAVEAT,
    group_receipts_by_outcome,
    render_grade_lite_table,
    render_rob_screening_table,
)


def test_group_receipts_by_outcome_uses_generic_fields_only() -> None:
    grouped = group_receipts_by_outcome([
        {"receipt_id": "r2", "outcome_class": "frailty"},
        {"receipt_id": "r1", "outcome": "mortality"},
    ])

    assert tuple(grouped) == ("frailty", "mortality")


def test_renderers_handle_mixed_directness_and_tiers() -> None:
    grouped = {
        "muscle": (
            {
                "receipt_id": "direct-rct",
                "tier": "A1",
                "directness": "direct",
                "risk_of_bias": "low",
            },
            {
                "receipt_id": "mechanism",
                "tier": "C1",
                "directness": "mechanistic",
                "risk_of_bias": "high",
            },
        )
    }

    rob = render_rob_screening_table(grouped)
    grade = render_grade_lite_table(grouped)

    assert CAVEAT_LINE in rob
    assert GRADE_LITE_CAVEAT in grade
    assert "direct-rct" in rob and "mechanism" in rob
    assert "| muscle | very_low | high | risk_of_bias:serious |" in grade


def test_invalid_receipts_fail_closed_but_render_cleanly() -> None:
    grouped = {"mortality": ({"receipt_id": "bad|id", "directness": "direct"},)}

    rob = render_rob_screening_table(grouped)
    grade = render_grade_lite_table(grouped)

    assert "true" in rob
    assert "bad\\|id" in rob
    assert "| mortality | very_low | very_low | missing_or_invalid_required_fields |" in grade
    assert "\n|" in rob and "\n|" in grade


def test_markdown_table_escapes_untrusted_cells() -> None:
    grouped = {
        "bad|outcome": ({
            "receipt_id": "x|y\n`z`",
            "tier": "A1",
            "directness": "direct",
        },)
    }

    md = render_rob_screening_table(grouped)

    assert "bad\\|outcome" in md
    assert "x\\|y \\`z\\`" in md
