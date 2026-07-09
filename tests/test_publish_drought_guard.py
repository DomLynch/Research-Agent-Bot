from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import publish_drought_guard as guard  # type: ignore[import-not-found]  # noqa: E402


def test_publication_rows_accepts_publications_wrapper() -> None:
    payload = {"publications": [{"id": "paper-1"}, "bad", {"id": "paper-2"}]}

    assert guard.publication_rows(payload) == [{"id": "paper-1"}, {"id": "paper-2"}]


def test_evaluate_drought_passes_recent_public_publication() -> None:
    status = guard.evaluate_drought(
        [{"createdAt": "2026-07-09T08:00:00+00:00"}],
        now=datetime(2026, 7, 9, 20, 0, tzinfo=UTC),
        max_age_hours=24,
    )

    assert status.passed is True
    assert status.reason == "recent_publication"
    assert status.age_hours == 12


def test_evaluate_drought_fails_after_threshold() -> None:
    status = guard.evaluate_drought(
        [{"publishedAt": "2026-07-04T06:16:38Z"}],
        now=datetime(2026, 7, 9, 12, 16, 38, tzinfo=UTC),
        max_age_hours=24,
    )

    assert status.passed is False
    assert status.reason == "publish_drought"
    assert status.age_hours == 126


def test_main_exits_nonzero_for_stale_public_feed(tmp_path: Path, capsys) -> None:
    feed = tmp_path / "publications.json"
    feed.write_text(json.dumps({
        "publications": [{"createdAt": "2026-07-04T10:16:38+04:00"}],
    }), encoding="utf-8")

    code = guard.main([
        "--input-json",
        str(feed),
        "--now",
        "2026-07-09T16:16:38+04:00",
        "--max-age-hours",
        "24",
    ])

    assert code == 1
    assert "status=fail" in capsys.readouterr().out


def test_deploy_timer_runs_guard_hourly() -> None:
    service = (REPO / "deploy" / "research-agent-paper-drought-guard.service").read_text(encoding="utf-8")
    timer = (REPO / "deploy" / "research-agent-paper-drought-guard.timer").read_text(encoding="utf-8")

    assert "scripts/publish_drought_guard.py --max-age-hours 24" in service
    assert "OnCalendar=hourly" in timer
