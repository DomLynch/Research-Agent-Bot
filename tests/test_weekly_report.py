"""Tests for scripts/weekly_report.py"""

import json
import subprocess
import sys
from pathlib import Path


def test_weekly_report_no_runs(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/weekly_report.py", "--runs-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "No runs" in result.stdout


def test_weekly_report_with_data(tmp_path: Path) -> None:
    for i in range(3):
        run = {
            "started_at": "2026-04-20T12:00:00+00:00",
            "topic": f"topic {i}",
            "domain_slug": "longevity",
            "estimated_cost_usd": 0.05,
            "evidence_selected": 12,
        }
        (tmp_path / f"run{i}.json").write_text(json.dumps(run), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/weekly_report.py", "--runs-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "3 runs" in result.stdout
    assert "$0.1500" in result.stdout
    assert "longevity" in result.stdout


def test_weekly_report_skips_raw_json(tmp_path: Path) -> None:
    run = {
        "started_at": "2026-04-20T12:00:00+00:00",
        "topic": "test",
        "domain_slug": "longevity",
        "estimated_cost_usd": 1.0,
    }
    (tmp_path / "foo.raw.json").write_text(json.dumps(run), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/weekly_report.py", "--runs-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "No runs" in result.stdout


def test_weekly_report_errors_listed(tmp_path: Path) -> None:
    run = {
        "started_at": "2026-04-20T12:00:00+00:00",
        "topic": "broken topic",
        "domain_slug": "longevity",
        "error": "Daily cost cap reached",
    }
    (tmp_path / "run0.json").write_text(json.dumps(run), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/weekly_report.py", "--runs-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Errors: 1/1" in result.stdout
    assert "Daily cost cap reached" in result.stdout


def test_weekly_report_custom_days(tmp_path: Path) -> None:
    run = {
        "started_at": "2025-01-01T12:00:00+00:00",
        "topic": "old",
        "domain_slug": "longevity",
        "estimated_cost_usd": 1.0,
    }
    (tmp_path / "old.json").write_text(json.dumps(run), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/weekly_report.py", "--runs-dir", str(tmp_path), "--days", "10000"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "old" in result.stdout
