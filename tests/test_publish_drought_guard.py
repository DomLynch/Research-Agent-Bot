from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import publish_drought_guard as guard  # type: ignore[import-not-found]  # noqa: E402


def _public_row(timestamp: str) -> dict[str, object]:
    return {
        "publishedAt": timestamp,
        "agentId": "agent-v3-full-paper-live",
        "artifactType": "research_paper",
        "decision": "accept",
        "publicVisible": True,
    }


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


def test_evaluate_drought_degrades_recent_publication_when_buffer_is_empty() -> None:
    status = guard.evaluate_drought(
        [{"createdAt": "2026-07-09T08:00:00+00:00"}],
        now=datetime(2026, 7, 9, 20, 0, tzinfo=UTC),
        max_age_hours=24,
        triage={"candidate_buffer": {
            "status": "candidate_buffer_depleted", "ready_count": 0, "target_ready": 3,
        }},
    )

    assert status.passed is True
    assert status.status == "degraded"
    assert status.reason == "candidate_buffer_depleted"
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
        "publications": [_public_row("2026-07-04T10:16:38+04:00")],
    }), encoding="utf-8")

    report = tmp_path / "report.json"

    code = guard.main([
        "--input-json",
        str(feed),
        "--now",
        "2026-07-09T16:16:38+04:00",
        "--max-age-hours",
        "24",
        "--report-path",
        str(report),
        "--enforce-exit-code",
    ])

    assert code == 1
    assert "status=fail" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["reason"] == "publish_drought"


def test_main_reports_drought_without_failing_systemd_by_default(tmp_path: Path) -> None:
    feed = tmp_path / "publications.json"
    report = tmp_path / "report.json"
    feed.write_text(json.dumps({
        "publications": [_public_row("2026-07-04T10:16:38+04:00")],
    }), encoding="utf-8")

    code = guard.main([
        "--input-json",
        str(feed),
        "--now",
        "2026-07-09T16:16:38+04:00",
        "--report-path",
        str(report),
    ])

    assert code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["status"] == "fail"


def test_main_reports_empty_buffer_degraded_without_failing_systemd(tmp_path: Path) -> None:
    feed = tmp_path / "publications.json"
    report = tmp_path / "report.json"
    ledger_dir = tmp_path / "runs" / "_daily_research_paper_cycle_ledger"
    ledger_dir.mkdir(parents=True)
    feed.write_text(json.dumps({
        "publications": [_public_row("2026-07-09T08:00:00+00:00")],
    }), encoding="utf-8")
    (ledger_dir / guard.CANDIDATE_BUFFER).write_text(json.dumps({
        "status": "candidate_buffer_depleted", "ready_count": 0, "target_ready": 3,
    }), encoding="utf-8")

    code = guard.main([
        "--input-json", str(feed), "--now", "2026-07-09T20:00:00+00:00",
        "--runs-root", str(tmp_path / "runs"), "--report-path", str(report),
    ])

    assert code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["status"] == "degraded"
    assert payload["reason"] == "candidate_buffer_depleted"


def test_triage_surfaces_submitted_not_public_ledgers(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "_daily_research_paper_cycle_ledger"
    ledger_dir.mkdir()
    (ledger_dir / "2026-07-09-fresh.json").write_text(json.dumps({
        "mode": "fresh",
        "status": "submitted_to_researka",
        "attempted_topic": "metformin_effects",
        "submitted": 1,
        "published": 0,
        "submission_id": "sub-1",
        "no_submission_reason": "reviewer_revise",
    }), encoding="utf-8")

    triage = guard.build_triage(tmp_path)

    assert triage["submitted_not_public"][0]["topic"] == "metformin_effects"
    assert triage["top_blockers"][0] == {"reason": "reviewer_revise", "count": 1}


def test_triage_surfaces_candidate_buffer_supply(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "_daily_research_paper_cycle_ledger"
    ledger_dir.mkdir()
    (ledger_dir / guard.CANDIDATE_BUFFER).write_text(json.dumps({
        "status": "candidate_buffer_partial",
        "ready_count": 1,
        "target_ready": 3,
        "generated_at": "2026-07-14T18:00:00+00:00",
    }), encoding="utf-8")

    triage = guard.build_triage(tmp_path)

    assert triage["candidate_buffer"] == {
        "status": "candidate_buffer_partial",
        "ready_count": 1,
        "target_ready": 3,
        "generated_at": "2026-07-14T18:00:00+00:00",
    }


def test_triage_includes_unique_candidate_conversion_funnel(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "_daily_research_paper_cycle_ledger"
    ledger_dir.mkdir()
    (ledger_dir / "2026-07-24-fresh.json").write_text(json.dumps({
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "attempts": [{
            "topic": "statins",
            "out_dir": "run-statins",
            "receipt_preflight": {"passed": True},
            "synthesis_return_code": 0,
            "gate_status": "eligible",
            "submitted": 1,
        }],
    }), encoding="utf-8")

    triage = guard.build_triage(tmp_path)

    assert triage["conversion_funnel"]["discovered"] == 1
    assert triage["conversion_funnel"]["prepared"] == 1
    assert triage["conversion_funnel"]["synthesized"] == 1
    assert triage["conversion_funnel"]["submitted"] == 1
    assert "attempts" not in triage["recent_ledgers"][0]


def test_recent_lane_ledgers_ignore_helper_state_files(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "_daily_research_paper_cycle_ledger"
    ledger_dir.mkdir()
    for index in range(15):
        (ledger_dir / f"_helper-{index:02d}.json").write_text(
            json.dumps({"status": "helper"}),
            encoding="utf-8",
        )
    real = ledger_dir / "2026-07-24-fresh.json"
    real.write_text(
        json.dumps({"status": "published", "published": 1}),
        encoding="utf-8",
    )

    ledgers = guard.recent_lane_ledgers(tmp_path, limit=1)

    assert len(ledgers) == 1
    assert ledgers[0]["ledger"] == str(real)


def test_recent_lane_ledgers_sort_across_lanes_by_mtime(tmp_path: Path) -> None:
    cycle_dir = tmp_path / "_daily_research_paper_cycle_ledger"
    submit_dir = tmp_path / "_daily_research_paper_ledger"
    cycle_dir.mkdir()
    submit_dir.mkdir()
    newer = cycle_dir / "2026-07-24-fresh.json"
    older = submit_dir / "2026-07-24.json"
    newer.write_text(json.dumps({"status": "newer"}), encoding="utf-8")
    older.write_text(json.dumps({"status": "older"}), encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    ledgers = guard.recent_lane_ledgers(tmp_path, limit=1)

    assert ledgers[0]["ledger"] == str(newer)


def test_triage_funnel_includes_prepare_only_candidates(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "_daily_research_paper_cycle_ledger"
    ledger_dir.mkdir()
    (ledger_dir / guard.CANDIDATE_BUFFER).write_text(json.dumps({
        "status": "candidate_buffer_partial",
        "ready_count": 1,
        "target_ready": 3,
        "ready": [{"topic": "metformin"}],
        "attempts": [{
            "topic": "metformin",
            "receipt_preflight": {"passed": True},
        }],
    }), encoding="utf-8")

    funnel = guard.build_triage(tmp_path)["conversion_funnel"]

    assert funnel["discovered"] == 1
    assert funnel["prepared"] == 1


def test_deploy_timer_runs_guard_hourly() -> None:
    service = (REPO / "deploy" / "research-agent-paper-drought-guard.service").read_text(encoding="utf-8")
    timer = (REPO / "deploy" / "research-agent-paper-drought-guard.timer").read_text(encoding="utf-8")

    assert "scripts/publish_drought_guard.py --max-age-hours 24" in service
    assert "--report-path /var/log/research-agent-bot/publish_drought_guard.json" in service
    assert "--enforce-exit-code" in service
    assert "OnFailure=research-agent-paper-drought-recovery.service" in service
    assert "OnCalendar=hourly" in timer


def test_guard_filters_other_agents_and_nonpublic_rows() -> None:
    rows = [
        _public_row("2026-07-24T08:00:00+00:00"),
        {**_public_row("2026-07-24T09:00:00+00:00"), "agentId": "agent-v7"},
        {**_public_row("2026-07-24T10:00:00+00:00"), "decision": "revise"},
        {**_public_row("2026-07-24T11:00:00+00:00"), "publicVisible": False},
        {**_public_row("2026-07-24T12:00:00+00:00"), "artifactType": "memo"},
    ]

    assert guard.v3_public_research_rows(rows) == [rows[0]]


def test_guard_accepts_supported_public_field_variants() -> None:
    row = {
        **_public_row("2026-07-24T08:00:00+00:00"),
        "decision": "accepted",
        "publicVisible": False,
        "published": True,
    }

    assert guard.v3_public_research_rows([row]) == [row]
