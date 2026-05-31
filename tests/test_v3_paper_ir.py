from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import v3_paper_ir as ir  # type: ignore[import-not-found]  # noqa: E402
import export_public_bundle as bundle  # type: ignore[import-not-found]  # noqa: E402


def _run(tmp_path: Path, *, topic: str = "akkermansia_muciniphila") -> Path:
    run = tmp_path / f"synthesis-{topic}-v06"
    (run / "audit").mkdir(parents=True)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Akkermansia Muciniphila\n\n"
        "## Abstract\n\nAkkermansia evidence remains bounded.\n\n"
        "## Methods\n\nSources were admitted through deterministic gates.\n\n"
        "## Results\n\nThe main result is contextual.\n\n"
        "| Study | Tier |\n|---|---|\n| Depommier 2019 | A1 |\n\n"
        "## Discussion\n\nThis corpus supports a context-specific thesis.\n\n"
        "## Limitations\n\nEvidence is incomplete.\n\n"
        "## Conclusion\n\nFuture work should run a registered trial.\n\n"
        "## References\n\n- Depommier et al. 2019. Akkermansia trial.\n",
        encoding="utf-8",
    )
    (run / "structured_evidence_tables.md").write_text(
        "## Table 1\n\n| Study | Tier |\n|---|---|\n| Depommier 2019 | A1 |\n",
        encoding="utf-8",
    )
    (run / "manifest.json").write_text(
        json.dumps({
            "topic": topic,
            "receipts": [
                {
                    "receipt_id": "Depommier 2019",
                    "evidence_tier": "A1",
                    "directness": "direct",
                    "outcome_class": "metabolic_health",
                    "effect_direction": "positive",
                    "n_claims": 8,
                },
            ],
        }),
        encoding="utf-8",
    )
    (run / "polish_tensions_appendix.json").write_text(
        json.dumps({"selected": [{"tension_id": "T1", "severity": 5}]}),
        encoding="utf-8",
    )
    (run / "claim_graph.json").write_text(json.dumps({"claims": []}), encoding="utf-8")
    (run / "paper_audit.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    return run


def test_compile_run_writes_paper_ir_exports_and_quality_score(tmp_path: Path) -> None:
    run = _run(tmp_path)
    result = ir.compile_run(run)
    paper_ir = result["paper_ir"]
    assert paper_ir["schema"] == "researka.paper_ir.v1"
    assert paper_ir["thesis"]["framework_name"] == "Microbiome Context Framework"
    assert paper_ir["thesis"]["axes"] == ["Outcome", "Host state", "Preparation", "Dose", "Strain", "Model"]
    for name in (
        "paper_ir.json",
        "paper_quality_score.json",
        "public_export_manifest.json",
        "evidence_table.csv",
        "references.bib",
        "contradiction_map.json",
        "full_paper.docx",
    ):
        assert (run / name).is_file()
    assert "Depommier 2019" in (run / "evidence_table.csv").read_text(encoding="utf-8")
    assert "@misc" in (run / "references.bib").read_text(encoding="utf-8")
    manifest = json.loads((run / "public_export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["paper_ir"]["exists"] is True
    assert manifest["files"]["paper_quality_score"]["exists"] is True
    with zipfile.ZipFile(run / "full_paper.docx") as zf:
        assert "word/document.xml" in zf.namelist()
        document = zf.read("word/document.xml").decode()
    assert "<w:b/>" in document
    assert "<w:tbl>" in document
    assert "Depommier 2019" in document


def test_domain_framework_falls_back_to_endpoint_sensitivity() -> None:
    framework = ir.select_domain_framework("retinal_age_ai", "imaging_clock", [])
    assert framework.name == "Endpoint-Sensitivity Framework"


def test_topic_pack_framework_overrides_keyword_registry(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    packs = repo / "topic_packs"
    packs.mkdir(parents=True)
    (packs / "precision_topic.toml").write_text(
        'topic = "precision_topic"\n'
        '[paper_framework]\n'
        'name = "Precision Evidence Framework"\n'
        'axes = ["Signal", "Population", "Comparator"]\n'
        'falsifier = "a direct trial where the signal disappears across comparators"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ir, "REPO", repo)
    run = _run(tmp_path, topic="precision_topic")
    result = ir.compile_run(run)
    thesis = result["paper_ir"]["thesis"]
    assert thesis["framework_name"] == "Precision Evidence Framework"
    assert thesis["axes"] == ["Signal", "Population", "Comparator"]


def test_public_bundle_copies_v3_export_sidecars_when_present(tmp_path: Path) -> None:
    run = _run(tmp_path)
    ir.compile_run(run)
    for name in (
        "full_paper.audit.json",
        "full_paper.audit.md",
        "full_paper.consistency.json",
        "full_paper.consistency.md",
        "full_paper.final_verdict.json",
        "full_paper.final_verdict.md",
        "full_paper.review_patches.json",
        "full_paper.review_patch_log.json",
        "full_paper.fixed_log.json",
        "citation_registry.json",
        "no_regression_report.json",
        "no_regression_report.md",
        "run_mode_contract.json",
    ):
        (run / name).write_text("{}", encoding="utf-8")
    out = tmp_path / "bundle"
    result = bundle.export_bundle(run, out)
    assert result["missing_required"] == []
    assert (out / "paper_ir.json").is_file()
    assert (out / "paper.docx").is_file()
    assert (out / "evidence_table.csv").is_file()
