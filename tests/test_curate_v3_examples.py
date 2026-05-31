from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import curate_v3_examples as curate  # type: ignore[import-not-found]  # noqa: E402


def _run(root: Path, name: str, score: float) -> Path:
    run = root / f"synthesis-{name}-v06"
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(
        "# Paper\n\n## Results\n\nClean.\n\n| Outcome | Finding |\n|---|---|\n| glucose | lower |\n\n## Structured Evidence Tables\n\n| A | B |\n|---|---|\n| x | y |\n\n## Conclusion\n\nDone.\n",
        encoding="utf-8",
    )
    (run / "paper_ir.json").write_text("{}", encoding="utf-8")
    (run / "public_export_manifest.json").write_text(
        json.dumps({"files": {"markdown": {"path": "full_paper.md", "exists": True}}}),
        encoding="utf-8",
    )
    (run / "paper_quality_score.json").write_text(
        json.dumps({"score_out_of_100": score}),
        encoding="utf-8",
    )
    (run / "evidence_table.csv").write_text("receipt_id,tier\nA,A1\n", encoding="utf-8")
    return run


def test_curate_examples_copies_only_scored_export_runs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    out = tmp_path / "examples"
    _run(runs, "alpha_topic", 96)
    _run(runs, "beta_topic", 50)
    (runs / "synthesis-missing-v06").mkdir()

    written = curate.curate_examples(runs, out, limit=3, min_score=80)

    assert [p.name for p in written] == ["alpha-topic"]
    assert (out / "alpha-topic" / "full_paper.md").is_file()
    manuscript = (out / "alpha-topic" / "full_paper.md").read_text(encoding="utf-8")
    assert "Structured Evidence Tables" not in manuscript
    assert "|---|" not in manuscript
    assert "## Conclusion" in manuscript
    assert (out / "alpha-topic" / "paper_ir.json").is_file()
    assert (out / "alpha-topic" / "evidence_table.csv").is_file()
    assert not (out / "beta-topic").exists()
