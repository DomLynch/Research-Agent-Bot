from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import tri_sync_status as tri  # noqa: E402


def test_count_dirty_counts_porcelain_lines() -> None:
    assert tri.count_dirty("") == 0
    assert tri.count_dirty(" M a.py\n?? b.py\n\n") == 2


def test_parse_ahead_behind_accepts_tab_or_space() -> None:
    assert tri.parse_ahead_behind("0\t0") == (0, 0)
    assert tri.parse_ahead_behind("2 3") == (2, 3)
    assert tri.parse_ahead_behind("bad") == (None, None)


def test_classify_clean_dirty_and_diverged_states() -> None:
    assert tri.classify_sync(dirty_count=0, ahead=0, behind=0, head="a", origin="a") == "synced"
    assert tri.classify_sync(dirty_count=2, ahead=0, behind=0) == "dirty"
    assert tri.classify_sync(dirty_count=0, ahead=2, behind=0) == "ahead"
    assert tri.classify_sync(dirty_count=0, ahead=0, behind=2) == "behind"
    assert tri.classify_sync(dirty_count=0, ahead=1, behind=1) == "diverged"


def test_parse_key_values_for_vps_probe() -> None:
    data = tri.parse_key_values(
        "path=/opt/research-agent-bot\n"
        "head=abc1234\n"
        "dirty=0\n"
        "service=active\n"
        "http=503\n"
    )
    assert data == {
        "path": "/opt/research-agent-bot",
        "head": "abc1234",
        "dirty": "0",
        "service": "active",
        "http": "503",
    }


def test_render_text_without_vps() -> None:
    text = tri.render_text(
        {
            "local": {
                "head": "abc1234",
                "origin_main": "abc1234",
                "dirty_count": 0,
                "ahead": 0,
                "behind": 0,
                "state": "synced",
            },
            "vps": [],
        }
    )
    assert "local_state: synced" in text
    assert "dirty_count: 0" in text


def test_remote_probe_command_is_read_only() -> None:
    command = tri._remote_probe_command("/opt/research-agent-bot")
    forbidden = ("pull", "fetch", "reset", "checkout", "restart", "systemctl restart")
    assert all(word not in command for word in forbidden)
    assert "git rev-parse --short=8 HEAD" in command
    assert "git status --porcelain" in command
