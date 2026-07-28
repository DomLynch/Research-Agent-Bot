from __future__ import annotations

from typing import Any

from scripts.evidence_map_summary import direction_profile_cell, source_context_map


def test_source_context_map_accepts_generators() -> None:
    rows = (
        row
        for row in (
            {
                "source_title": "Everolimus metastatic cancer trial",
                "effect_direction": "null",
                "p_values": ["p < 0.05"],
            },
            {
                "source_title": "Everolimus bone muscle protocol",
                "effect_direction": "null",
                "p_values": [],
            },
        )
    )

    out = source_context_map(rows)

    assert "Oncology and cancer context: 1 sources" in out
    assert "Skeletal and muscle context: 1 sources" in out


def test_direction_profile_cell_uses_one_complete_direction_accounting() -> None:
    rows: list[dict[str, Any]] = [
        {"effect_direction": "positive"},
        {"effect_direction": "mixed"},
        {"effect_direction": "unclear"},
    ]

    assert direction_profile_cell(rows) == (
        "positive=1, negative=0, null=0, mixed=1, unclear=1 (n=3)"
    )


def test_source_context_map_uses_resolved_direction() -> None:
    rows: list[dict[str, Any]] = [
        {
            "source_title": "Higher inflammation risk in cancer",
            "thesis_text": "Higher inflammation risk, p = 0.01.",
            "effect_direction": "null",
            "p_values": ["p = 0.01"],
        },
        {"source_title": "Bone muscle protocol", "effect_direction": "unclear"},
    ]

    assert "negative signal in 1/1 sources" in source_context_map(rows)
