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
    assert "Errors (draft): 1/1" in result.stdout
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


def test_weekly_report_gate_blocked(tmp_path: Path) -> None:
    run = {
        "started_at": "2026-04-20T12:00:00+00:00",
        "topic": "blocked topic",
        "domain_slug": "longevity",
        "estimated_cost_usd": 0.05,
        "evidence_selected": 12,
        "submission": {"gate_blocked": True, "reason": "bundle_too_small:11"},
    }
    (tmp_path / "run0.json").write_text(json.dumps(run), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/weekly_report.py", "--runs-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Quality-gate blocked: 1/1" in result.stdout
    assert "bundle_too_small:11" in result.stdout


def test_weekly_report_submission_breakdown(tmp_path: Path) -> None:
    """Runs with submissions get broken into posted / duplicates / gate-blocked."""
    runs = [
        {
            "started_at": "2026-04-20T12:00:00+00:00",
            "topic": "ok",
            "domain_slug": "longevity",
            "submission_id": "sub-1",
            "submission": {"submission": {"id": "sub-1"}},
            "evidence_selected": 15,
        },
        {
            "started_at": "2026-04-20T12:01:00+00:00",
            "topic": "dup",
            "domain_slug": "longevity",
            "submission": {"duplicate": True, "previous_submission_id": "sub-1"},
            "evidence_selected": 14,
        },
        {
            "started_at": "2026-04-20T12:02:00+00:00",
            "topic": "blocked",
            "domain_slug": "longevity",
            "submission": {"gate_blocked": True, "reason": "low_topic_precision:0.25"},
            "evidence_selected": 10,
        },
        {
            "started_at": "2026-04-20T12:03:00+00:00",
            "topic": "no sub",
            "domain_slug": "general",
            "evidence_selected": 5,
        },
    ]
    for i, run in enumerate(runs):
        (tmp_path / f"run{i}.json").write_text(json.dumps(run), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/weekly_report.py", "--runs-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "4 runs" in result.stdout
    assert "Submissions posted: 1/4" in result.stdout
    assert "Duplicates skipped: 1/4" in result.stdout
    assert "Quality-gate blocked: 1/4" in result.stdout
    assert "Submission success rate: 50% (1/2 intended)" in result.stdout
