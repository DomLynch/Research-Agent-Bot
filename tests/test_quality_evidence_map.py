"""Tests for scripts.quality_evidence_map — unified evidence-map renderer."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent.risk_of_bias_schema import ROB2_DOMAINS
from scripts.quality_evidence_map import (
    render_corpus_summary,
    render_quality_evidence_map,
    render_top_tensions_section,
    tensions_from_json,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "quality_evidence_map.py"


def _sample_manifest() -> dict:
    return {
        "topic": "rapamycin",
        "thesis": "Context-dependent effects across 3 receipts.",
        "n_receipts": 2,
        "receipts": [
            {"receipt_id": "Moel 2025", "outcome_class": "cardiometabolic",
             "effect_direction": "null", "evidence_tier": "A1", "directness": "direct"},
            {"receipt_id": "Kell 2026", "outcome_class": "immune",
             "effect_direction": "supports", "evidence_tier": "B2", "directness": "indirect"},
        ],
    }


def _sample_rob() -> list[dict]:
    return [{
        "study_id": "Moel 2025", "design": "rct", "tool": "rob2",
        "overall_rating": "some_concerns",
        "domains": [{"domain": d, "rating": "low"} for d in ROB2_DOMAINS],
    }]


def _sample_grade() -> list[dict]:
    return [{
        "outcome": "Cardiometabolic", "starting_certainty": "high",
        "downgrades": [{"reason": "inconsistency", "levels": 2}],
        "upgrades": [],
    }]


def _sample_tensions() -> list[dict]:
    return [{
        "tension_id": "T1", "paper_a": "A", "paper_b": "B",
        "conflict_type": "null_vs_positive", "outcome_class": "x",
        "severity": 5,
        "numeric_anchors_a": ["p=0.05"], "numeric_anchors_b": ["n=80"],
    }]


# ---- render_corpus_summary -------------------------------------------------


def test_corpus_summary_includes_topic_and_receipts() -> None:
    md = render_corpus_summary(_sample_manifest())
    assert "Receipts" in md
    assert "Moel 2025" in md
    assert "Kell 2026" in md
    assert "thesis" in md.lower()


def test_corpus_summary_handles_none_manifest() -> None:
    assert "_No manifest provided._" in render_corpus_summary(None)


def test_corpus_summary_handles_empty_receipts() -> None:
    md = render_corpus_summary({"n_receipts": 0, "receipts": []})
    assert "_No receipts in manifest._" in md


# ---- tensions_from_json + render_top_tensions_section ---------------------


def test_tensions_from_json_roundtrips() -> None:
    records = tensions_from_json(_sample_tensions())
    assert len(records) == 1
    assert records[0].tension_id == "T1"


def test_top_tensions_section_renders_severity_sorted() -> None:
    payload = [
        {"tension_id": f"T{i}", "paper_a": f"A{i}", "paper_b": f"B{i}",
         "conflict_type": "disagreement", "outcome_class": "x",
         "severity": 5 - (i % 5)} for i in range(7)
    ]
    records = tensions_from_json(payload)
    md = render_top_tensions_section(records, top_n=3)
    # Top 3 by severity DESC, tension_id tiebreak
    assert md.count("###") == 3
    # Highest severity items appear before lower
    assert md.index("T0") < md.index("T1")


def test_top_tensions_section_empty() -> None:
    assert "_No tension records provided._" in render_top_tensions_section([])


def test_top_tensions_section_includes_hypotheses() -> None:
    md = render_top_tensions_section(tensions_from_json(_sample_tensions()))
    assert "Plausible hypotheses" in md
    # Two numbered hypotheses
    assert "1." in md and "2." in md


# ---- render_quality_evidence_map (full integration) ------------------------


def test_full_render_combines_all_sections() -> None:
    md = render_quality_evidence_map(
        manifest=_sample_manifest(),
        rob_payload=_sample_rob(),
        grade_payload=_sample_grade(),
        tension_payload=_sample_tensions(),
    )
    assert "# Quality Evidence Map — rapamycin" in md
    assert "Corpus Summary" in md
    assert "Risk-of-Bias Summary" in md
    assert "GRADE Certainty Summary" in md
    assert "Top Tensions" in md
    assert "Moel 2025" in md
    # GRADE high - 2 = low
    assert "low" in md


def test_full_render_with_no_inputs_emits_all_placeholders() -> None:
    md = render_quality_evidence_map()
    assert "_No manifest provided._" in md
    assert "_No RoB data provided._" in md
    assert "_No GRADE data provided._" in md
    assert "_No tension records provided._" in md


def test_partial_render_manifest_only() -> None:
    md = render_quality_evidence_map(manifest=_sample_manifest())
    assert "rapamycin" in md
    assert "Moel 2025" in md
    assert "_No RoB data provided._" in md


def test_default_top_n_is_five() -> None:
    payload = [
        {"tension_id": f"T{i}", "paper_a": f"A{i}", "paper_b": f"B{i}",
         "conflict_type": "disagreement", "outcome_class": "x", "severity": 4}
        for i in range(8)
    ]
    md = render_quality_evidence_map(tension_payload=payload)
    assert md.count("###") == 5


def test_custom_top_n_clamps_section_count() -> None:
    payload = [
        {"tension_id": f"T{i}", "paper_a": f"A{i}", "paper_b": f"B{i}",
         "conflict_type": "disagreement", "outcome_class": "x", "severity": 4}
        for i in range(8)
    ]
    md = render_quality_evidence_map(tension_payload=payload, top_n=2)
    assert md.count("###") == 2


def test_pipe_in_field_is_escaped() -> None:
    """Pipes in cell content must not break the markdown table."""
    manifest = {
        "topic": "x", "n_receipts": 1, "receipts": [
            {"receipt_id": "study|with|pipe", "outcome_class": "c",
             "effect_direction": "null", "evidence_tier": "A1", "directness": "direct"},
        ],
    }
    md = render_corpus_summary(manifest)
    assert "study\\|with\\|pipe" in md


# ---- CLI integration -------------------------------------------------------


def test_cli_writes_output(tmp_path: Path) -> None:
    manifest_path = tmp_path / "m.json"
    rob_path = tmp_path / "r.json"
    grade_path = tmp_path / "g.json"
    tension_path = tmp_path / "t.json"
    out_path = tmp_path / "out.md"
    manifest_path.write_text(json.dumps(_sample_manifest()))
    rob_path.write_text(json.dumps(_sample_rob()))
    grade_path.write_text(json.dumps(_sample_grade()))
    tension_path.write_text(json.dumps(_sample_tensions()))
    proc = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--manifest", str(manifest_path),
         "--rob", str(rob_path),
         "--grade", str(grade_path),
         "--tensions", str(tension_path),
         "--out", str(out_path)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    text = out_path.read_text()
    assert "rapamycin" in text
    assert "Moel 2025" in text


def test_cli_works_with_no_inputs(tmp_path: Path) -> None:
    out_path = tmp_path / "out.md"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out_path)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    text = out_path.read_text()
    assert "_No manifest provided._" in text
