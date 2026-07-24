from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import publish_drought_recovery as recovery  # type: ignore[import-not-found]  # noqa: E402


def _completed(
    args: tuple[str, ...],
    returncode: int,
    stdout: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout, "")


def test_recovery_prepares_then_starts_one_fresh_attempt(tmp_path: Path) -> None:
    report = tmp_path / "guard.json"
    state = tmp_path / "state.json"
    report.write_text(json.dumps({"passed": False, "reason": "publish_drought"}))
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ("systemctl", "is-active"):
            return _completed(args, 1)
        if args[-1] == "research-agent-paper-prepare.service":
            return _completed(args, 3)
        return _completed(args, 0)

    result = recovery.recover(
        report_path=report,
        state_path=state,
        cooldown_hours=6,
        now=datetime.now(UTC),
        runner=runner,
    )

    assert result["status"] == "recovery_started"
    assert result["prepare_return_code"] == 3
    assert result["prepare_exec_status"] == 3
    assert result["fresh_return_code"] == 0
    assert (
        "systemctl", "start", "--no-block", "research-agent-paper-fresh.service",
    ) in calls
    assert json.loads(state.read_text())["status"] == "recovery_started"


def test_recovery_does_not_overlap_an_active_lane(tmp_path: Path) -> None:
    report = tmp_path / "guard.json"
    report.write_text(json.dumps({"passed": False, "reason": "publish_drought"}))

    def runner(args: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        active = args[-1] == "research-agent-paper-fresh.service"
        return _completed(args, 0 if active else 1, "active\n" if active else "inactive\n")

    result = recovery.recover(
        report_path=report,
        state_path=tmp_path / "state.json",
        cooldown_hours=6,
        now=datetime.now(UTC),
        runner=runner,
    )

    assert result == {
        "status": "busy",
        "active_units": ["research-agent-paper-fresh.service"],
    }


def test_recovery_does_not_overlap_daily_cycle(tmp_path: Path) -> None:
    report = tmp_path / "guard.json"
    report.write_text(json.dumps({"passed": False, "reason": "publish_drought"}))

    def runner(args: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        active = args[-1] == "research-agent-paper-daily-cycle.service"
        return _completed(args, 0 if active else 1, "active\n" if active else "inactive\n")

    result = recovery.recover(
        report_path=report,
        state_path=tmp_path / "state.json",
        cooldown_hours=6,
        now=datetime.now(UTC),
        runner=runner,
    )

    assert result == {
        "status": "busy",
        "active_units": ["research-agent-paper-daily-cycle.service"],
    }


def test_recovery_stops_after_prepare_hard_failure(tmp_path: Path) -> None:
    report = tmp_path / "guard.json"
    state = tmp_path / "state.json"
    report.write_text(json.dumps({"passed": False, "reason": "publish_drought"}))
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ("systemctl", "is-active"):
            return _completed(args, 1)
        if args[:3] == ("systemctl", "show", "--property=ExecMainStatus"):
            return _completed(args, 0, "2\n")
        return _completed(args, 0)

    result = recovery.recover(
        report_path=report,
        state_path=state,
        cooldown_hours=6,
        now=datetime.now(UTC),
        runner=runner,
    )

    assert result["status"] == "recovery_prepare_failed"
    assert result["prepare_return_code"] == 0
    assert result["prepare_exec_status"] == 2
    assert (
        "systemctl", "start", "--no-block", "research-agent-paper-fresh.service",
    ) not in calls
    assert json.loads(state.read_text())["status"] == "recovery_prepare_failed"


def test_recovery_treats_activating_oneshot_as_busy(tmp_path: Path) -> None:
    report = tmp_path / "guard.json"
    report.write_text(json.dumps({"passed": False, "reason": "publish_drought"}))

    def runner(args: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        activating = args[-1] == "research-agent-paper-daily-cycle.service"
        return _completed(
            args,
            3 if activating else 1,
            "activating\n" if activating else "inactive\n",
        )

    result = recovery.recover(
        report_path=report,
        state_path=tmp_path / "state.json",
        cooldown_hours=6,
        now=datetime.now(UTC),
        runner=runner,
    )

    assert result == {
        "status": "busy",
        "active_units": ["research-agent-paper-daily-cycle.service"],
    }


def test_recovery_service_is_bounded_and_v3_only() -> None:
    service = (
        REPO / "deploy" / "research-agent-paper-drought-recovery.service"
    ).read_text(encoding="utf-8")

    assert "scripts/publish_drought_recovery.py" in service
    assert "--cooldown-hours 6" in service
    assert "research-agent-paper-fresh.service" not in service
    assert "v5" not in service.lower()
    assert "v7" not in service.lower()
