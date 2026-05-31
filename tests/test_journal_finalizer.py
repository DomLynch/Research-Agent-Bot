from __future__ import annotations

import json
from pathlib import Path

from agent import journal_finalizer


def test_phase_f_fills_existing_empty_results_outcome_heading(tmp_path: Path) -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Cardiometabolic | n=2; claims=9 | mixed | 2 indirect | limited |\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "## References\n\n- Smith 2024.\n"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"outcome_class": "cardiometabolic", "n_claims": 4, "effect_direction": "mixed", "directness": "indirect"},
        {"outcome_class": "cardiometabolic", "n_claims": 5, "effect_direction": "null", "directness": "indirect"},
    ]}), encoding="utf-8")
    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)
    assert logs
    assert "### Cardiometabolic Outcomes\n\nCardiometabolic remains a separate Results slice" in fixed


def test_phase_f_does_not_render_extraction_null_as_outcome_null(tmp_path: Path) -> None:
    paper = "## Results\n\n## References\n\n- Smith 2024.\n"
    (tmp_path / "manifest.json").write_text(json.dumps({"receipts": [
        {"outcome_class": "skeletal_fracture_bone", "n_claims": 142, "effect_direction": "null", "directness": "review"},
        {"outcome_class": "skeletal_fracture_bone", "n_claims": 0, "effect_direction": "null", "directness": "review"},
    ]}), encoding="utf-8")
    fixed, logs = journal_finalizer._phase_f_reconcile_results_table(paper, tmp_path)
    assert logs
    assert "no extracted directional signal in 2/2 sources" in fixed
    assert "null signal in 2/2 sources" not in fixed
