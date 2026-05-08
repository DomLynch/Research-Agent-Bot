from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import osf_live_readiness as readiness  # noqa: E402


def _run(root: Path, topic: str, suffix: str) -> Path:
    run_dir = root / f"synthesis-{topic}-v06-{suffix}"
    run_dir.mkdir()
    (run_dir / "paper.md").write_text("paper", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps({"topic": topic}),
        encoding="utf-8",
    )
    (run_dir / "osf_publish_result.json").write_text("{}", encoding="utf-8")
    return run_dir


def test_latest_run_uses_aliases_and_latest_name(tmp_path: Path) -> None:
    _run(tmp_path, "caloric_restriction", "A")
    latest = _run(tmp_path, "caloric_restriction", "Z")
    assert readiness.latest_run(tmp_path, "cr") == latest


def test_build_report_is_dry_and_stable(tmp_path: Path) -> None:
    for topic in ("omega3", "statins", "caloric_restriction", "metformin", "rapamycin"):
        _run(tmp_path, topic, "Z")
    for idx in range(6):
        _run(tmp_path, "omega3", f"RICH{idx}")

    report = readiness.build_report(runs_dir=tmp_path)

    assert report["live_ready"] is True
    assert report["ready_for_first_live_smoke"] is True
    assert report["live_proven"] is False
    assert report["dry_run_only"] is True
    assert len(report["topics"]) == 5
    assert len(report["rich_runs"]) == 6
    for row in report["all_checks"]:
        assert row["ok"] is True
        assert row["generated_excluded"] is True
        assert row["reader_generated_excluded"] is True
        assert row["osf_keys_match"] is True
        assert row["dw_keys_match"] is True
        assert all(row["inner_idempotency_stable"].values())
        assert row["secret_scan"]["passed"] is True
        assert row["live_gate"] == {"cli_flag": "--live", "env_var": "OSF_PUBLISH_LIVE"}


def test_write_outputs_renders_matrix(tmp_path: Path) -> None:
    _run(tmp_path, "omega3", "Z")
    report = readiness.build_report(runs_dir=tmp_path, topics=("omega3",))
    paths = readiness.write_outputs(report, tmp_path / "out")

    assert paths["json"].exists()
    md = paths["markdown"].read_text(encoding="utf-8")
    assert "OSF/DW Provenance Drill" in md
    assert "First Live Smoke" in md
    assert "Rate Limit / Retry Risk" in md
    assert "osf-publisher publish" in md


def test_render_markdown_reports_not_live_proven(tmp_path: Path) -> None:
    _run(tmp_path, "omega3", "RICH")
    report = readiness.build_report(runs_dir=tmp_path, topics=("omega3",))
    md = readiness.render_markdown(report)
    assert "Ready for first live smoke: yes" in md
    assert "Live proven: no" in md


def test_source_does_not_read_token_env() -> None:
    source = (REPO / "scripts" / "osf_live_readiness.py").read_text(encoding="utf-8")
    assert "\nimport os\n" not in source
    assert "os.environ" not in source
