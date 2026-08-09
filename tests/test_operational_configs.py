from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SERVICES = (
    "prepare", "fresh", "revise", "daily-cycle", "daily-submit", "reconcile",
)


def test_long_paper_lanes_wait_for_the_prepare_lock() -> None:
    for name in SERVICES:
        text = (REPO / "deploy" / f"research-agent-paper-{name}.service").read_text()
        assert "research-agent-paper-lane.lock" not in text, name
    prepare = (REPO / "deploy" / "research-agent-paper-prepare.service").read_text()
    assert "flock --conflict-exit-code 75 --exclusive --wait 900 /run/research-agent-paper-prepare.lock" in prepare
    for name in ("fresh", "revise", "daily-cycle"):
        text = (REPO / "deploy" / f"research-agent-paper-{name}.service").read_text()
        assert "flock --conflict-exit-code 75 --shared --wait 900 /run/research-agent-paper-prepare.lock" in text
    daily_submit = (REPO / "deploy" / "research-agent-paper-daily-submit.service").read_text()
    assert "TimeoutStartSec=900" in daily_submit


def test_no_work_exit_is_success_for_publication_lanes() -> None:
    for name in ("prepare", "fresh", "revise", "daily-cycle", "daily-submit"):
        text = (REPO / "deploy" / f"research-agent-paper-{name}.service").read_text()
        assert "SuccessExitStatus=3" in text, name
        assert "SuccessExitStatus=3 75" not in text, name


def test_prepare_runs_between_long_paper_windows_and_timers_catch_up() -> None:
    prepare = (REPO / "deploy" / "research-agent-paper-prepare.timer").read_text()
    assert "OnCalendar=*-*-* 02/8:00:00" in prepare
    for name in ("prepare", "fresh", "revise", "daily-cycle"):
        text = (REPO / "deploy" / f"research-agent-paper-{name}.timer").read_text()
        assert "Persistent=true" in text, name


def test_weekly_workflow_runs_existing_report_and_never_commits() -> None:
    text = (REPO / ".github/workflows/weekly-reports.yml").read_text()
    assert "scripts/weekly_report.py" not in text
    assert "git-auto-commit-action" not in text
    assert "path: docs/weekly/" in text
