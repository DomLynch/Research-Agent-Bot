from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import release_watchdog_report as watch  # noqa: E402


def _tri() -> dict:
    return {
        "local": {"head": "abc12345", "origin_main": "abc12345", "ahead": 0, "behind": 0},
        "vps": [
            {"path": "/opt/research-agent-bot", "head": "abc12345", "dirty_count": 0, "service": "active", "http": "200"},
            {"path": "/root/Research-Agent-Bot", "head": "abc12345", "dirty_count": 0, "service": "active", "http": "200"},
        ],
    }


def test_classify_dirty_by_lane() -> None:
    rows = watch.parse_dirty(" M scripts/tri_sync_status.py\n?? reports/release_watchdog/a.md\n?? docs/reader_static_v1.md\n")
    assert [row["lane"] for row in rows] == ["tri_sync_status", "release_watchdog", "reader"]


def test_clean_release_passes() -> None:
    report = watch.build_report(
        tri_sync=_tri(),
        sha_text="local_full=a\norigin_full=a\n",
        dirty_text="",
        test_text="All checks passed!\n13 passed",
    )
    assert report["verdict"] == "PASS"


def test_dirty_release_blocks() -> None:
    report = watch.build_report(
        tri_sync=_tri(),
        sha_text="local_full=a\norigin_full=a\n",
        dirty_text="?? reports/release_watchdog/a.md\n",
        test_text="13 passed",
    )
    assert report["verdict"] == "BLOCKED"
    assert report["dirty_by_lane"] == {"release_watchdog": 1}


def test_sha_mismatch_blocks() -> None:
    report = watch.build_report(
        tri_sync=_tri(),
        sha_text="local_full=a\norigin_full=b\n",
        dirty_text="",
        test_text="13 passed",
    )
    assert "local/origin full SHA mismatch or missing full SHA data" in report["blockers"]


def test_cli_writes_markdown(tmp_path: Path) -> None:
    tri = tmp_path / "tri.json"
    tri.write_text(json.dumps(_tri()), encoding="utf-8")
    sha = tmp_path / "sha.txt"
    sha.write_text("local_full=a\norigin_full=a\n", encoding="utf-8")
    dirty = tmp_path / "dirty.txt"
    dirty.write_text("", encoding="utf-8")
    tests = tmp_path / "tests.txt"
    tests.write_text("13 passed", encoding="utf-8")
    out = tmp_path / "report.md"

    assert watch.main(["--tri-sync-json", str(tri), "--sha", str(sha), "--dirty", str(dirty), "--tests", str(tests), "--out", str(out)]) == 0
    assert "# Release Watchdog Report" in out.read_text(encoding="utf-8")
