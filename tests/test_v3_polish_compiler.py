from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import v3_polish_compiler as polish  # type: ignore[import-not-found]  # noqa: E402


def _run_dir(tmp_path: Path, *, table: bool = False) -> Path:
    run = tmp_path / "run"
    (run / "audit").mkdir(parents=True)
    body = (
        "# Research Synthesis\n\n"
        "## Abstract\n\n"
        "This paper is bounded.\n\n"
        "## Results\n\n"
        + (
            "| Study | Result |\n|---|---|\n| A | B |\n\n"
            if table else
            "The result is described in prose.\n\n"
        )
        + "## Conclusion\n\n"
        "Future work should run a registered trial as the next study.\n"
    )
    (run / "full_paper.md").write_text(body, encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps({"topic": "demo_topic"}), encoding="utf-8")
    tensions = {
        "plans": [
            {
                "tension_id": f"T{i:03d}",
                "paper_a": f"A{i}",
                "paper_b": f"B{i}",
                "conflict_type": "disagreement" if i % 2 else "cross_domain",
                "outcome_class": f"outcome_{i % 5}",
                "severity": 5 - (i % 3),
            }
            for i in range(12)
        ],
    }
    (run / "audit" / "tension_elaboration_plans.json").write_text(
        json.dumps(tensions),
        encoding="utf-8",
    )
    return run


def test_compile_run_writes_sidecars_with_optional_tools_skipped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(polish, "_embedding_vectors", lambda _texts: None)
    monkeypatch.setattr(polish, "_run_typst", lambda _typ, _pdf: {"status": "skipped"})
    monkeypatch.setattr(polish, "_run_sciwrite", lambda _paper: {"status": "skipped"})
    report = polish.compile_run(_run_dir(tmp_path))
    assert report["passed"] is True
    assert report["tensions"] == {"selected": 8, "total": 12}
    assert (tmp_path / "run" / "full_paper.typ").exists()
    assert (tmp_path / "run" / "polish_compiler.json").exists()
    assert (tmp_path / "run" / "polish_tensions_appendix.json").exists()
    assert (tmp_path / "run" / "paper_ir.json").exists()
    assert (tmp_path / "run" / "public_export_manifest.json").exists()
    assert report["paper_ir"]["paper_ir"]["schema"] == "researka.paper_ir.v1"


def test_canonical_pipe_table_is_advisory_and_rendered_to_typst(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(polish, "_embedding_vectors", lambda _texts: None)
    monkeypatch.setattr(polish, "_run_typst", lambda _typ, _pdf: {"status": "skipped"})
    monkeypatch.setattr(polish, "_run_sciwrite", lambda _paper: {"status": "skipped"})
    run = _run_dir(tmp_path, table=True)
    report = polish.compile_run(run)
    typ = (run / "full_paper.typ").read_text(encoding="utf-8")
    assert report["passed"] is True
    assert report["gates"]["raw_pipe_tables"]["status"] == "advisory"
    assert "| Study | Result |" not in typ
    assert "#table(" in typ
    assert "[*Study*]" in typ
    assert "[B]" in typ


def test_malformed_pipe_table_still_blocks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(polish, "_embedding_vectors", lambda _texts: None)
    monkeypatch.setattr(polish, "_run_typst", lambda _typ, _pdf: {"status": "skipped"})
    monkeypatch.setattr(polish, "_run_sciwrite", lambda _paper: {"status": "skipped"})
    run = _run_dir(tmp_path)
    paper = (run / "full_paper.md").read_text(encoding="utf-8")
    (run / "full_paper.md").write_text(
        paper.replace("The result is described in prose.", "| A | B |\n|---|---|\n| only-one-cell |"),
        encoding="utf-8",
    )
    report = polish.compile_run(run)
    assert report["passed"] is False
    assert report["gates"]["raw_pipe_tables"]["status"] == "failed"


def test_compile_run_writes_optional_adapter_sidecars(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(polish, "_embedding_vectors", lambda _texts: None)
    monkeypatch.setattr(polish, "_run_typst", lambda _typ, _pdf: {"status": "skipped"})
    monkeypatch.setattr(polish, "_run_sciwrite", lambda _paper: {"status": "skipped"})
    run = _run_dir(tmp_path)
    report = polish.compile_run(run)
    assert report["docling_fallback"]["status"] == "skipped"
    assert report["structured_output"]["status"] == "passed"
    assert (run / "biomed_normalization.json").exists()
    assert (run / "docling_fallback.json").exists()
    assert (run / "offline_eval_harness.json").exists()
    assert (run / "structured_output_contract.json").exists()
    assert (run / "paper_quality_score.json").exists()


def test_compile_run_failsofts_paper_ir_sidecar(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(polish, "_embedding_vectors", lambda _texts: None)
    monkeypatch.setattr(polish, "_run_typst", lambda _typ, _pdf: {"status": "skipped"})
    monkeypatch.setattr(polish, "_run_sciwrite", lambda _paper: {"status": "skipped"})

    def boom(_run_dir: Path) -> dict:
        raise OSError("readonly export dir")

    monkeypatch.setattr(polish._paper_ir, "compile_run", boom)
    report = polish.compile_run(_run_dir(tmp_path))
    assert report["passed"] is True
    assert report["paper_ir"]["status"] == "failed"
    assert "readonly export dir" in report["paper_ir"]["error"]
