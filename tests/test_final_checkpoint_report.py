from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import final_checkpoint_report as report  # noqa: E402


def _status(**local_overrides: object) -> dict:
    local = {
        "head": "abc1234",
        "origin_main": "abc1234",
        "dirty_count": 0,
        "ahead": 0,
        "behind": 0,
        "state": "synced",
    }
    local.update(local_overrides)
    return {"local": local, "vps": []}


def test_parse_test_summary_pytest_and_ruff() -> None:
    assert report.parse_test_summary("23 passed in 0.05s")["ok"] is True
    assert report.parse_test_summary("1 failed, 2 passed")["ok"] is False
    assert report.parse_test_summary("2 errors, 1 passed")["errors"] == 2
    assert report.parse_test_summary("All checks passed!\n1 failed")["ok"] is False
    assert report.parse_test_summary("All checks passed!")["ruff_clean"] is True


def test_clean_checkpoint_passes() -> None:
    result = report.build_report(
        {
            **_status(),
            "vps": [
                {
                    "path": "/opt/research-agent-bot",
                    "head": "abc1234",
                    "dirty_count": 0,
                    "service": "active",
                    "http": "503",
                }
            ],
        },
        "ruff All checks passed!\n23 passed",
    )
    assert result["ready"] is True
    assert "Verdict:** PASS" in report.render_markdown(result)


def test_dirty_checkpoint_blocks() -> None:
    result = report.build_report(_status(dirty_count=3, state="dirty"), "23 passed")
    assert result["ready"] is False
    assert result["local"]["dirty_category"] == "light_dirty"


def test_stringified_counts_are_supported() -> None:
    result = report.build_report(_status(dirty_count="0", ahead="0", behind="0"), "23 passed")
    assert result["ready"] is True


def test_ahead_behind_and_diverged_block() -> None:
    assert report.build_report(_status(ahead=1, state="ahead"), "23 passed")["ready"] is False
    assert report.build_report(_status(behind=1, state="behind"), "23 passed")["ready"] is False
    assert report.build_report(_status(ahead=1, behind=1, state="diverged"), "23 passed")["ready"] is False


def test_vps_mismatch_blocks() -> None:
    result = report.build_report(
        {
            **_status(),
            "vps": [{"path": "/opt/research-agent-bot", "head": "def5678", "dirty_count": 0}],
        },
        "23 passed",
    )
    assert result["ready"] is False
    assert result["vps"][0]["state"] == "sha_mismatch"


def test_cli_writes_markdown_without_network(tmp_path: Path) -> None:
    status = tmp_path / "tri.json"
    status.write_text(json.dumps(_status()), encoding="utf-8")
    tests = tmp_path / "tests.txt"
    tests.write_text("23 passed", encoding="utf-8")
    out = tmp_path / "report.md"

    assert report.main(["--tri-sync-json", str(status), "--test-output", str(tests), "--out", str(out)]) == 0
    assert "# Final Checkpoint Report" in out.read_text(encoding="utf-8")
