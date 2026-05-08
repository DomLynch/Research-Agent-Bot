from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import osf_publish  # noqa: E402
import osf_publish_cron as cron  # noqa: E402


def test_cron_skips_already_published(tmp_path: Path) -> None:
    eligible = tmp_path / "run-a"
    published = tmp_path / "run-b"
    eligible.mkdir()
    published.mkdir()
    (published / osf_publish.RESULT_NAME).write_text("{}", encoding="utf-8")

    assert cron.iter_eligible_runs(tmp_path) == [eligible]
    assert cron.iter_eligible_runs(tmp_path, force=True) == [eligible, published]


def test_cron_dry_run_creates_snapshot_and_plan_for_eligible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    run_dir = tmp_path / "run-a"
    run_dir.mkdir()
    (run_dir / "paper.md").write_text("public", encoding="utf-8")

    outcomes = cron.publish_eligible(tmp_path, dry_run=True)

    assert [item["run_dir"] for item in outcomes] == [run_dir]
    assert (run_dir / "bundle_snapshot.json").exists()
    assert (run_dir / osf_publish.PLAN_NAME).exists()
    assert not (run_dir / osf_publish.RESULT_NAME).exists()
    plan = json.loads((run_dir / osf_publish.PLAN_NAME).read_text())
    assert plan["run_id"] == "run-a"
    assert "OSF_PAT" not in json.dumps(plan)


def test_cron_force_replans_published_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    run_dir = tmp_path / "run-a"
    run_dir.mkdir()
    (run_dir / "paper.md").write_text("public", encoding="utf-8")
    (run_dir / osf_publish.RESULT_NAME).write_text("{}", encoding="utf-8")

    outcomes = cron.publish_eligible(tmp_path, dry_run=True, force=True)

    assert [item["run_dir"] for item in outcomes] == [run_dir]
    assert (run_dir / osf_publish.PLAN_NAME).exists()


def test_cron_live_missing_pat_fails_closed_via_delegated_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    run_dir = tmp_path / "run-a"
    run_dir.mkdir()
    (run_dir / "paper.md").write_text("public", encoding="utf-8")

    with pytest.raises(RuntimeError, match="OSF_PAT"):
        cron.publish_eligible(tmp_path, dry_run=False)


def test_cron_main_live_missing_pat_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    run_dir = tmp_path / "run-a"
    run_dir.mkdir()
    (run_dir / "paper.md").write_text("public", encoding="utf-8")

    assert cron.main(["--runs-dir", str(tmp_path), "--live"]) == 2
