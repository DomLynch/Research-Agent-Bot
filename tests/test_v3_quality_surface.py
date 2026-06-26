from __future__ import annotations

import json
from pathlib import Path

from scripts.v3_quality_surface import (
    apply_quality_surface_markdown,
    apply_quality_surface_sections,
    apply_quality_surface_to_run,
)


class FakeStudy:
    study_id = "Study 1"
    tool = "rob2"
    overall_rating = "some_concerns"


class FakeGrade:
    outcome = "immune"
    final_certainty = "moderate"
    downgrade_reasons = ("rob", "imprecision")


class FakeBundle:
    rob_assessments = (FakeStudy(),)
    grade_assessments = (FakeGrade(),)


def _paper() -> str:
    return (
        "# Test paper\n\n"
        "## Abstract\n\nShort abstract.\n\n"
        "## Results\n\nResult text.\n\n"
        "## Discussion\n\nDiscussion text.\n\n"
        "## References\n\nReference text.\n"
    )


def _meta_result() -> dict:
    return {"pools": [], "skipped": [], "candidate_groups": 0}


def _tension_payload() -> dict:
    return {
        "plans": [
            {
                "tension_id": "T001",
                "outcome_class": "immune",
                "paper_a": "Study 1",
                "paper_b": "Study 2",
                "conflict_type": "null_vs_positive",
                "severity": 3,
                "numeric_anchors": ["p=0.04"],
                "hypotheses": ["endpoint mismatch"],
                "corpus_weight_winner": "Study 1",
            }
        ],
        "candidate_tensions": 1,
    }


def test_apply_quality_surface_sections_inserts_before_discussion() -> None:
    out, log = apply_quality_surface_sections(
        _paper(),
        quality_bundle=FakeBundle(),
        meta_analysis=_meta_result(),
        tension_payload=_tension_payload(),
    )

    assert [row["section"] for row in log] == [
        "risk_of_bias_and_grade",
        "meta_analysis_results",
        "cross_paper_tensions",
    ]
    assert "## Risk of Bias and GRADE" in out
    assert "## Meta-Analysis Results" in out
    assert "## Cross-Paper Tensions" in out
    assert "No quantitative pool was run" in out
    assert "T001: immune" in out
    assert (
        out.index("## Results")
        < out.index("## Risk of Bias and GRADE")
        < out.index("## Meta-Analysis Results")
        < out.index("## Cross-Paper Tensions")
        < out.index("## Discussion")
        < out.index("## References")
    )


def test_apply_quality_surface_markdown_normalizes_sidecar_headings_and_is_idempotent() -> None:
    quality_md = (
        "# Quality Methods Bundle\n\n"
        "# Risk-of-Bias Summary\n\n"
        "| Study | Tool | Overall |\n| --- | --- | --- |\n| Study 1 | rob2 | S |\n"
    )
    meta_md = (
        "## Meta-Analysis Results\n\n"
        "No quantitative pool was run because no outcome class met the pre-specified requirement."
    )
    tension_md = "## Cross-Paper Tension Plans\n\nNo non-orthogonal cross-paper tension met the planning threshold."

    once, first_log = apply_quality_surface_markdown(
        _paper(), quality_md=quality_md, meta_md=meta_md, tension_md=tension_md,
    )
    twice, second_log = apply_quality_surface_markdown(
        once, quality_md=quality_md, meta_md=meta_md, tension_md=tension_md,
    )

    assert first_log
    assert second_log == []
    assert twice.count("## Risk of Bias and GRADE") == 1
    assert twice.count("## Meta-Analysis Results") == 1
    assert twice.count("## Cross-Paper Tensions") == 1
    assert "## Cross-Paper Tension Plans" not in twice
    assert "### Risk-of-Bias Summary" in twice
    assert "\n# Risk-of-Bias Summary" not in twice


def test_apply_quality_surface_to_run_patches_existing_folder(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    readable = run_dir / "readable"
    readable.mkdir(parents=True)
    (run_dir / "full_paper.md").write_text(_paper(), encoding="utf-8")
    (readable / "quality_methods.md").write_text(
        "# Quality Methods Bundle\n\n# Risk-of-Bias Summary\n\nRoB table.",
        encoding="utf-8",
    )
    (readable / "meta_analysis_results.md").write_text(
        "## Meta-Analysis Results\n\nNo quantitative pool was run because no outcome class met the pre-specified requirement.",
        encoding="utf-8",
    )
    (readable / "tension_elaboration_plans.md").write_text(
        "## Cross-Paper Tension Plans\n\nNo non-orthogonal cross-paper tension met the planning threshold.",
        encoding="utf-8",
    )

    payload = apply_quality_surface_to_run(run_dir)
    patched = (run_dir / "full_paper.md").read_text(encoding="utf-8")
    log = json.loads((run_dir / "quality_surface_log.json").read_text(encoding="utf-8"))

    assert payload["changed"] is True
    assert log["changed"] is True
    assert log["source_artifacts"] == {
        "quality_methods": True,
        "meta_analysis_results": True,
        "tension_elaboration_plans": True,
    }
    assert "## Risk of Bias and GRADE" in patched
    assert "## Cross-Paper Tensions" in patched
    assert "### Risk-of-Bias Summary" in patched
    assert patched.index("## Risk of Bias and GRADE") < patched.index("## Discussion")


def test_apply_quality_surface_to_run_records_noop_when_artifacts_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "full_paper.md").write_text(_paper(), encoding="utf-8")

    payload = apply_quality_surface_to_run(run_dir)

    assert payload["changed"] is False
    assert payload["insertions"] == []
    assert (run_dir / "quality_surface_log.json").exists()
