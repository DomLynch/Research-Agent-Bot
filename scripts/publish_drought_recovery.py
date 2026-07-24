#!/usr/bin/env python3
"""Run one bounded V3 recovery after a confirmed publication drought."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_REPORT_PATH = Path("/var/log/research-agent-bot/publish_drought_guard.json")
DEFAULT_STATE_PATH = Path("/var/lib/research-agent-bot/publish_drought_recovery.json")
ACTIVE_LANES = (
    "research-agent-paper-daily-cycle.service",
    "research-agent-paper-fresh.service",
    "research-agent-paper-revise.service",
    "research-agent-paper-daily-submit.service",
    "research-agent-paper-prepare.service",
)

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(runner: Runner, *args: str) -> subprocess.CompletedProcess[str]:
    return runner(args, capture_output=True, text=True, check=False)


def _unit_running(runner: Runner, unit: str) -> bool:
    result = _run(runner, "systemctl", "is-active", unit)
    state = result.stdout.strip()
    return state in {"active", "activating", "reloading", "deactivating"} or not state and result.returncode == 0


def recover(
    *,
    report_path: Path,
    state_path: Path,
    cooldown_hours: float,
    now: dt.datetime,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    report = _read_json(report_path)
    if report.get("passed") is not False:
        return {"status": "not_required", "reason": "guard_not_failed"}
    try:
        report_age = now.timestamp() - report_path.stat().st_mtime
    except OSError:
        return {"status": "not_required", "reason": "guard_report_missing"}
    if report_age > 300:
        return {"status": "not_required", "reason": "guard_report_stale"}

    state = _read_json(state_path)
    last_raw = state.get("attempted_at")
    try:
        last = dt.datetime.fromisoformat(str(last_raw).replace("Z", "+00:00"))
    except ValueError:
        last = None
    if last and now - last.astimezone(dt.UTC) < dt.timedelta(hours=cooldown_hours):
        return {"status": "cooldown", "attempted_at": last.isoformat()}

    active = [
        unit for unit in ACTIVE_LANES
        if _unit_running(runner, unit)
    ]
    if active:
        return {"status": "busy", "active_units": active}

    result: dict[str, Any] = {
        "status": "attempted",
        "attempted_at": now.isoformat(),
        "guard_reason": report.get("reason"),
    }
    _write_json(state_path, result)
    prepare = _run(runner, "systemctl", "start", "research-agent-paper-prepare.service")
    result["prepare_return_code"] = prepare.returncode
    status = _run(
        runner,
        "systemctl", "show", "--property=ExecMainStatus", "--value",
        "research-agent-paper-prepare.service",
    )
    try:
        prepare_status = int(status.stdout.strip())
    except ValueError:
        prepare_status = prepare.returncode
    result["prepare_exec_status"] = prepare_status
    if prepare_status not in {0, 3}:
        result["status"] = "recovery_prepare_failed"
        _write_json(state_path, result)
        return result
    publishing_active = [
        unit for unit in ACTIVE_LANES if unit != "research-agent-paper-prepare.service"
        if _unit_running(runner, unit)
    ]
    if publishing_active:
        result.update({"status": "prepared_lane_busy", "active_units": publishing_active})
    else:
        fresh = _run(
            runner, "systemctl", "start", "--no-block",
            "research-agent-paper-fresh.service",
        )
        result["fresh_return_code"] = fresh.returncode
        result["status"] = "recovery_started" if fresh.returncode == 0 else "recovery_start_failed"
    _write_json(state_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--cooldown-hours", type=float, default=6.0)
    args = parser.parse_args(argv)
    result = recover(
        report_path=args.report_path,
        state_path=args.state_path,
        cooldown_hours=max(0.0, args.cooldown_hours),
        now=dt.datetime.now(dt.UTC),
    )
    print(json.dumps(result, sort_keys=True))
    return 2 if result["status"] in {"recovery_start_failed", "recovery_prepare_failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
