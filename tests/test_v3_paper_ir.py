from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import v3_paper_ir as ir  # type: ignore[import-not-found]  # noqa: E402


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
        source_hash = zf.read("researka/source.sha256").decode()
    assert source_hash == hashlib.sha256((run / "full_paper.md").read_bytes()).hexdigest()
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


def test_malformed_topic_pack_framework_falls_back_cleanly(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    packs = repo / "topic_packs"
    packs.mkdir(parents=True)
    (packs / "precision_topic.toml").write_text(
        'topic = "precision_topic"\n'
        'class_ = "microbiome_intervention"\n'
        '[paper_framework]\n'
        'name = "Incomplete Framework"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ir, "REPO", repo)
    result = ir.compile_run(_run(tmp_path, topic="precision_topic"))
    assert result["paper_ir"]["thesis"]["framework_name"] == "Microbiome Context Framework"


def test_docx_handles_ragged_pipe_table_as_plain_text(tmp_path: Path) -> None:
    run = _run(tmp_path)
    paper = (run / "full_paper.md").read_text(encoding="utf-8")
    (run / "full_paper.md").write_text(
        paper.replace("| Depommier 2019 | A1 |", "| Depommier 2019 |"),
        encoding="utf-8",
    )
    ir.compile_run(run)
    with zipfile.ZipFile(run / "full_paper.docx") as zf:
        document = zf.read("word/document.xml").decode()
    assert "<w:tbl>" not in document
    assert "Depommier 2019" in document


def test_docx_export_does_not_truncate_long_manuscript(tmp_path: Path) -> None:
    from agent.artifact_consistency import verify_run_artifacts

    paper = "# Long paper\n\n" + "\n\n".join(
        f"Source paragraph {index} remains visible." for index in range(705)
    )
    (tmp_path / "full_paper.md").write_text(paper, encoding="utf-8")
    ir._write_docx(tmp_path / "full_paper.docx", paper)

    with zipfile.ZipFile(tmp_path / "full_paper.docx") as archive:
        document = archive.read("word/document.xml").decode()
    assert "Source paragraph 704 remains visible." in document
    assert verify_run_artifacts(tmp_path).passed is True


def test_reresolve_export_manifest_repoints_sidecar_moved_to_audit(tmp_path) -> None:
    """A sidecar relocated into audit/ after the manifest was written must be
    re-pointed (path -> audit/..., exists True) so the public bundle ships the
    populated file rather than a stale top-level path."""
    (tmp_path / "public_export_manifest.json").write_text(json.dumps({
        "schema": "researka.public_exports.v1",
        "files": {
            "risk_of_bias": {"path": "risk_of_bias.json", "exists": True},  # stale
            "paper_ir": {"path": "paper_ir.json", "exists": True},
        },
    }), encoding="utf-8")
    (tmp_path / "paper_ir.json").write_text("{}", encoding="utf-8")
    (tmp_path / "audit").mkdir()
    (tmp_path / "audit" / "risk_of_bias.json").write_text("[]", encoding="utf-8")

    assert ir.reresolve_export_manifest(tmp_path) is True
    files = json.loads((tmp_path / "public_export_manifest.json").read_text())["files"]
    assert files["risk_of_bias"] == {"path": "audit/risk_of_bias.json", "exists": True}
    assert files["paper_ir"]["path"] == "paper_ir.json"  # unchanged
    assert ir.reresolve_export_manifest(tmp_path) is False  # idempotent
