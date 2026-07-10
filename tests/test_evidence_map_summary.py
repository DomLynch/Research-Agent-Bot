from __future__ import annotations

from scripts.evidence_map_summary import source_context_map


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
