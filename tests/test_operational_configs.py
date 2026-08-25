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
    for name in ("fresh", "daily-cycle", "daily-submit"):
        text = (REPO / "deploy" / f"research-agent-paper-{name}.service").read_text()
        assert "flock --conflict-exit-code 75 --shared --wait 900 /run/research-agent-paper-prepare.lock" in text
    revise = (REPO / "deploy" / "research-agent-paper-revise.service").read_text()
    assert "flock --conflict-exit-code 75 --shared --wait 4200 /run/research-agent-paper-prepare.lock" in revise
    assert "--max-revise-attempts 1 --cycle-budget-sec 10800" in revise
    assert "TimeoutStartSec=16200" in revise
    daily_submit = (REPO / "deploy" / "research-agent-paper-daily-submit.service").read_text()
    assert "TimeoutStartSec=1800" in daily_submit


def test_no_work_exit_is_success_for_publication_lanes() -> None:
    # Exit 3 is a bounded no-work result; the drought guard owns SLO recovery.
    for name in ("prepare", "fresh", "revise", "daily-cycle", "daily-submit"):
        text = (REPO / "deploy" / f"research-agent-paper-{name}.service").read_text()
        assert "SuccessExitStatus=3" in text, name
        assert "SuccessExitStatus=3 75" not in text, name


def test_manual_runs_cannot_suppress_the_next_scheduled_long_lane() -> None:
    for name in ("prepare", "fresh", "revise"):
        text = (REPO / "deploy" / f"research-agent-paper-{name}.service").read_text()
        assert "StartLimitIntervalSec=21600" in text, name
        assert "StartLimitBurst=4" in text, name


def test_prepare_runs_between_long_paper_windows_and_timers_catch_up() -> None:
    prepare = (REPO / "deploy" / "research-agent-paper-prepare.timer").read_text()
    assert "OnCalendar=*-*-* 03/8:30:00" in prepare
    prepare_service = (REPO / "deploy" / "research-agent-paper-prepare.service").read_text()
    assert "research-agent-paper-daily-submit.service" in prepare_service
    for name in ("prepare", "fresh", "revise", "daily-cycle", "daily-submit"):
        text = (REPO / "deploy" / f"research-agent-paper-{name}.timer").read_text()
        assert "Persistent=true" in text, name


def test_weekly_workflow_runs_existing_report_and_never_commits() -> None:
    text = (REPO / ".github/workflows/weekly-reports.yml").read_text()
    assert "scripts/weekly_report.py" not in text
    assert "git-auto-commit-action" not in text
    assert "path: docs/weekly/" in text
