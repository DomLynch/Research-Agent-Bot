from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import domain_discrimination as dd  # type: ignore[import-not-found]  # noqa: E402
import journal_finalizer  # type: ignore[import-not-found]  # noqa: E402
import v3_paper_ir as ir  # type: ignore[import-not-found]  # noqa: E402


def _receipts() -> list[dict[str, object]]:
    return [
        {
            "receipt_id": "Smith 2024",
            "title": "Zone 2 aerobic training and cognition trial",
            "study_design": "randomized trial",
            "population": "older adults",
            "intervention": "zone 2 aerobic training",
            "comparator": "guideline-concordant activity",
            "outcome_class": "cognition",
            "follow_up": "24 weeks",
            "effect": "memory endpoint p=0.88",
            "effect_direction": "positive",
            "directness": "direct",
            "risk_of_bias": "some concerns",
        },
        {
            "receipt_id": "Jones 2023",
            "title": "Systematic review and meta-analysis of exercise cognition evidence",
            "study_design": "systematic review",
            "outcome_class": "dosing and pharmacokinetics",
            "effect_direction": "unclear",
            "directness": "direct",
        },
    ]


def test_domain_schema_selects_topic_specific_axes_and_flags_bad_labels() -> None:
    payload = dd.build_domain_discrimination("zone2_training cognition", _receipts())

    assert payload["domain_schema"]["key"] == "exercise_cognition"
    assert "Comparator" in payload["domain_schema"]["axes"]
    assert "cognitive-domain selection" in payload["thesis"]
    issues = payload["classification_sanity"]["issues"]
    assert {issue["field"] for issue in issues} == {"direction", "directness", "outcome"}


def test_domain_surface_inserts_public_extraction_table_before_discussion() -> None:
    paper = "# T\n\n## Results\n\nInitial map.\n\n## Discussion\n\nOld generic discussion.\n"

    fixed, payload, changed = dd.apply_domain_surface(paper, "zone2_training", _receipts())

    assert changed is True
    assert fixed.index("## Domain Interpretation Framework") < fixed.index("## Discussion")
    assert "### Public Study Extraction Table" in fixed
    assert "| Source | Design | Population | Intervention/exposure |" in fixed
    assert payload["classification_sanity"]["status"] == "review"
    assert dd.apply_domain_surface(fixed, "zone2_training", _receipts())[2] is False


def test_v3_paper_ir_writes_domain_discrimination_export(tmp_path: Path) -> None:
    run = tmp_path / "synthesis-zone2_training-v06"
    run.mkdir()
    (run / "full_paper.md").write_text(
        "# T\n\n## Abstract\n\nA bounded map.\n\n## Methods\n\nM.\n\n"
        "## Results\n\nR.\n\n## Discussion\n\nD.\n\n## Conclusion\n\nC.\n",
        encoding="utf-8",
    )
    (run / "manifest.json").write_text(
        json.dumps({"topic": "zone2_training", "receipts": _receipts()}),
        encoding="utf-8",
    )
    (run / "claim_graph.json").write_text("{}", encoding="utf-8")
    (run / "paper_audit.json").write_text("{}", encoding="utf-8")

    result = ir.compile_run(run)

    assert result["paper_ir"]["thesis"]["framework_name"] == "Exercise-Cognition Comparator Framework"
    assert "novel_contribution" in result["paper_ir"]["thesis"]
    assert (run / "domain_discrimination.json").is_file()
    assert result["export_manifest"]["files"]["domain_discrimination"]["exists"] is True


def test_journal_finalizer_surfaces_domain_discrimination_in_public_paper(tmp_path: Path) -> None:
    paper = "# T\n\n## Results\n\nInitial map.\n\n## Discussion\n\nOld generic discussion.\n"
    (tmp_path / "manifest.json").write_text(
        json.dumps({"topic": "zone2_training", "receipts": _receipts()}),
        encoding="utf-8",
    )

    fixed, logs = journal_finalizer._phase_d_domain_discrimination_surface(paper, tmp_path)

    assert "## Domain Interpretation Framework" in fixed
    assert "### Classification Sanity Check" in fixed
    assert "Smith 2024" in fixed
    assert (tmp_path / "domain_discrimination.json").is_file()
    assert logs[0].rule == "insert_domain_schema_and_extraction_table"
