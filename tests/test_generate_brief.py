"""BRIEFS-V1 Phase 5 CLI/bundle tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import generate_brief  # noqa: E402


def _run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "runs" / "synthesis-metformin-v06-TEST"
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text("# paper\n")
    (run / "manifest.json").write_text(json.dumps({
        "topic": "metformin",
        "n_receipts": 2,
        "receipts": [
            {
                "receipt_id": "metformin_cognition_t2d_older",
                "citation_token": "Smith 2024",
                "outcome_class": "cognitive",
                "evidence_tier": "A1",
                "directness": "direct",
                "effect_direction": "positive",
                "n_claims": 9,
            },
            {
                "receipt_id": "metformin_mortality",
                "citation_token": "Jones 2023",
                "outcome_class": "longevity",
                "evidence_tier": "B2",
                "directness": "indirect",
                "effect_direction": "mixed",
                "n_claims": 4,
            },
        ],
    }))
    return run


def test_generate_brief_bundle_writes_five_files(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    out = tmp_path / "brief-out"
    paths = generate_brief.generate_brief_bundle(
        question="metformin for cognition in T2D patients 65+",
        source_paper=run / "full_paper.md",
        output_dir=out,
    )
    assert set(paths) == {
        "brief", "audit", "citations", "provenance", "numeric_quarantine",
    }
    assert all(path.exists() for path in paths.values())
    assert "Smith 2024" in paths["brief"].read_text()
    assert "Jones 2023" not in paths["brief"].read_text()


def test_generate_brief_bundle_audit_and_provenance(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    paths = generate_brief.generate_brief_bundle(
        question="metformin for cognition in T2D patients 65+",
        source_paper=run,
        output_dir=tmp_path / "brief-out",
    )
    audit = json.loads(paths["audit"].read_text())
    provenance = json.loads(paths["provenance"].read_text())
    citations = json.loads(paths["citations"].read_text())
    assert audit["passed"] is True
    assert audit["filtered_receipts"] == 1
    assert provenance["source_run"] == run.name
    assert citations[0]["citation_token"] == "Smith 2024"
    assert json.loads(paths["numeric_quarantine"].read_text()) == []


def test_generate_brief_cli_returns_zero(tmp_path: Path, capsys) -> None:
    run = _run_dir(tmp_path)
    out = tmp_path / "brief-out"
    rc = generate_brief.main([
        "--question", "metformin for cognition",
        "--source-paper", str(run / "full_paper.md"),
        "--output-dir", str(out),
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert str(out / "brief.md") in captured.out
