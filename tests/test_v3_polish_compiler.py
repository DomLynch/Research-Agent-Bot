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


def test_raw_pipe_table_fails_gate_and_is_removed_from_typst(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(polish, "_embedding_vectors", lambda _texts: None)
    monkeypatch.setattr(polish, "_run_typst", lambda _typ, _pdf: {"status": "skipped"})
    monkeypatch.setattr(polish, "_run_sciwrite", lambda _paper: {"status": "skipped"})
    run = _run_dir(tmp_path, table=True)
    report = polish.compile_run(run)
    typ = (run / "full_paper.typ").read_text(encoding="utf-8")
    assert report["passed"] is False
    assert report["gates"]["raw_pipe_tables"]["status"] == "failed"
    assert "| Study | Result |" not in typ
    assert "Structured table omitted from PDF main text" in typ
