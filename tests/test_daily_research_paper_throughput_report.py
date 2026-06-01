from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import daily_research_paper_throughput_report as report  # type: ignore[import-not-found]  # noqa: E402


def _next(rows: list[dict]) -> str:
    return (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {"rows": rows}}})
        + "</script>"
    )


def test_rows_from_next_html_extracts_nested_decisions() -> None:
    rows = report._rows_from_next_html(_next([{
        "createdAt": "2026-05-30T04:06:54+04:00",
        "title": "Research Synthesis: Colchicine",
        "decision": "accept",
        "artifactType": "research_paper",
        "agentId": report.AGENT_ID,
    }]))

    assert rows[0]["decision"] == "accept"


def test_local_counts_reports_top_blockers_and_repeats(tmp_path: Path) -> None:
    ledger = tmp_path / "_daily_research_paper_cycle_ledger"
    submit = tmp_path / "_daily_research_paper_ledger"
    ledger.mkdir()
    submit.mkdir()
    (ledger / "2026-05-30.json").write_text(json.dumps({
        "started_at": "2026-05-30T20:00:00+00:00",
        "mode": "fresh",
        "status": "preflight_skipped_no_submission",
        "attempted_topic": "epigenetic_clocks",
    }))
    (submit / "2026-05-30.json").write_text(json.dumps({"status": "no_eligible_research_paper"}))
    (ledger / "_blocker_histogram.json").write_text(json.dumps({
        "blockers": {"retracted_source_cited": {"count": 4, "class": "D_no_action"}},
        "repeats": {
            "coenzyme_q10_ubiquinol\u001fretracted_source_cited": ["2026-05-30T20:00:00+00:00"],
            "coenzyme_q10_ubiquinol\u001fabstract_overclaim": ["2026-05-30T21:00:00+00:00"],
        },
    }))

    counts = report._local_counts(tmp_path, "2026-05-30")

    assert counts["cycle"]["attempted_topic"] == "epigenetic_clocks"
    assert counts["top_blockers"][0]["code"] == "retracted_source_cited"
    assert counts["surface_repeat_topics"] == ["coenzyme_q10_ubiquinol"]


def test_local_counts_reports_mode_ledgers_and_daily_sidecars(tmp_path: Path) -> None:
    ledger = tmp_path / "_daily_research_paper_cycle_ledger"
    submit = tmp_path / "_daily_research_paper_ledger"
    ledger.mkdir()
    submit.mkdir()
    (ledger / "2026-06-01-fresh.json").write_text(json.dumps({
        "started_at": "2026-06-01T22:00:00+00:00",
        "mode": "fresh",
        "status": "submitted_to_researka",
        "submitted": 1,
        "attempted_topic": "pcsk9_inhibitors_longevity",
    }))
    (ledger / "2026-06-01-revise.json").write_text(json.dumps({
        "started_at": "2026-06-01T23:15:00+00:00",
        "mode": "revise",
        "status": "no_revise_pending",
        "submitted": 0,
    }))
    (ledger / "_daily_throughput_summary.json").write_text(json.dumps({
        "days": {"2026-06-01": {"submitted": 14, "published": 6, "cycles": 9}},
    }))
    (ledger / "_decisions_by_day.json").write_text(json.dumps({
        "days": {"2026-06-01": {"counts": {"accept": 6, "revise": 3}}},
    }))

    counts = report._local_counts(tmp_path, "2026-06-01")

    assert counts["cycle"]["mode"] == "revise"
    assert counts["cycle_modes"]["fresh"]["submitted"] == 1
    assert counts["throughput"]["submitted"] == 14
    assert counts["decisions"]["counts"] == {"accept": 6, "revise": 3}


def test_capacity_snapshot_reports_one_and_two_year_plans(monkeypatch) -> None:
    calls: list[tuple[int, float, int]] = []

    def fake_live_plan(*, target: int, years: float, interval_minutes: int) -> dict:
        calls.append((target, years, interval_minutes))
        return {"target_reachable_at_current_interval": years == 2.0}

    monkeypatch.setattr(report, "live_plan", fake_live_plan)

    snapshot = report._capacity_snapshot()

    assert calls == [(5000, 1.0, 120), (5000, 2.0, 120)]
    assert snapshot["one_year"]["target_reachable_at_current_interval"] is False
    assert snapshot["two_year"]["target_reachable_at_current_interval"] is True


def test_capacity_snapshot_reports_errors(monkeypatch) -> None:
    def broken_live_plan(*, target: int, years: float, interval_minutes: int) -> dict:
        raise RuntimeError("capacity unavailable")

    monkeypatch.setattr(report, "live_plan", broken_live_plan)

    assert report._capacity_snapshot() == {"error": "RuntimeError: capacity unavailable"}
