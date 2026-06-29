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


def test_public_counts_includes_live_agent_public_accepts(monkeypatch) -> None:
    monkeypatch.setattr(report, "_fetch_rows", lambda url: [{
        "createdAt": "2026-06-02T08:42:45.882266+04:00",
        "title": "Research Synthesis: Sleep Architecture Deep Sleep",
        "decision": "accept",
        "artifactType": "research_paper",
        "agentId": "agent-v3-full-paper-live",
    }] if "papers" in url else [])

    counts = report._public_counts("2026-06-02", papers_url="https://researka.org/papers", reviews_url="https://researka.org/reviews")

    assert counts["decisions"] == {"accept": 1}
    assert counts["examples"][0]["title"] == "Research Synthesis: Sleep Architecture Deep Sleep"


def test_local_counts_reports_top_blockers_and_repeats(tmp_path: Path) -> None:
    ledger = tmp_path / "_daily_research_paper_cycle_ledger"
    submit = tmp_path / "_daily_research_paper_ledger"
    ledger.mkdir()
    submit.mkdir()
    (ledger / "2026-05-30.json").write_text(json.dumps({
        "started_at": "2026-05-30T12:00:00+00:00",
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
        "started_at": "2026-06-01T12:00:00+00:00",
        "mode": "fresh",
        "status": "submitted_to_researka",
        "submitted": 1,
        "attempted_topic": "pcsk9_inhibitors_longevity",
    }))
    (ledger / "2026-06-01-revise.json").write_text(json.dumps({
        "started_at": "2026-06-01T13:15:00+00:00",
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
    assert "daily-submit" not in counts["cycle_modes"]
    assert counts["throughput"]["submitted"] == 14
    assert counts["decisions"]["counts"] == {"accept": 6, "revise": 3}


def test_local_counts_reports_daily_submit_cycle_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "_daily_research_paper_cycle_ledger"
    ledger.mkdir()
    (ledger / "2026-06-29-daily-submit.json").write_text(json.dumps({
        "updated_at": "2026-06-29T14:15:00+00:00",
        "mode": "daily-submit",
        "status": "published",
        "submitted": 2,
        "published": 1,
        "run_id": "daily-submit:2026-06-29T14:15:00+00:00",
    }))

    counts = report._local_counts(tmp_path, "2026-06-29")

    assert counts["cycle_modes"]["daily-submit"] == {
        "started_at": None,
        "updated_at": "2026-06-29T14:15:00+00:00",
        "completed_at": None,
        "mode": "daily-submit",
        "status": "published",
        "submitted": 2,
        "published": 1,
        "attempted_topic": None,
        "topic": None,
        "run_id": "daily-submit:2026-06-29T14:15:00+00:00",
    }


def test_local_counts_maps_late_utc_runs_to_dubai_report_day(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_AGENT_REPORT_TZ", "Asia/Dubai")
    ledger = tmp_path / "_daily_research_paper_cycle_ledger"
    submit = tmp_path / "_daily_research_paper_ledger"
    ledger.mkdir()
    submit.mkdir()
    (ledger / "2026-06-23-fresh.json").write_text(json.dumps({
        "started_at": "2026-06-23T22:38:06.233172+00:00",
        "mode": "fresh",
        "status": "published",
        "submitted": 1,
        "published": 1,
        "attempted_topic": "spermidine",
    }))
    (ledger / "_daily_throughput_summary.json").write_text(json.dumps({
        "days": {"2026-06-23": {"runs": [{
            "started_at": "2026-06-23T22:38:06.233172+00:00",
            "mode": "fresh",
            "status": "published",
            "submitted": 1,
            "published": 1,
            "topic": "spermidine",
        }]}}
    }))
    (submit / "2026-06-23.json").write_text(json.dumps({
        "date": "2026-06-23",
        "status": "published",
        "submitted": 2,
        "published": 1,
        "candidate": {"run": "synthesis-spermidine-v06-DAILY-2026-06-23T23-09-55Z-R2"},
    }))

    counts = report._local_counts(tmp_path, "2026-06-24")

    assert counts["cycle_modes"]["fresh"]["attempted_topic"] == "spermidine"
    assert counts["throughput"]["submitted"] == 1
    assert counts["throughput"]["published"] == 1
    assert counts["submit"]["submitted"] == 2
    assert counts["submit"]["published"] == 1


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


def test_pace_snapshot_reports_daily_target_and_observed_gap() -> None:
    local = {"throughput": {"submitted": 3, "published": 1}}
    public = {"decisions": {"accept": 2, "revise": 1}}
    capacity = {
        "one_year": {"target": 5000, "days": 365},
        "two_year": {"target": 5000, "days": 730},
    }

    pace = report._pace_snapshot(local, public, capacity)

    assert pace["required_daily_average"] == {"one_year": 13.7, "two_year": 6.85}
    assert pace["today_observed"] == {
        "local_submitted": 3,
        "local_published": 1,
        "public_accepts": 2,
        "observed_published": 2,
    }
    assert pace["today_gap_to_two_year_daily_average"] == {
        "by_local_submissions": 3.85,
        "by_local_published": 5.85,
        "by_public_accepts": 4.85,
        "by_observed_published": 4.85,
    }


def test_rolling_pace_snapshot_reports_window_gap(tmp_path: Path) -> None:
    ledger = tmp_path / "_daily_research_paper_cycle_ledger"
    ledger.mkdir()
    (ledger / "_daily_throughput_summary.json").write_text(json.dumps({
        "days": {
            "2026-06-01": {"submitted": 14, "published": 6, "cycles": 9},
            "2026-06-02": {"submitted": 8, "published": 3, "cycles": 4},
        },
    }))
    capacity = {
        "one_year": {"target": 5000, "days": 365},
        "two_year": {"target": 5000, "days": 730},
    }

    pace = report._rolling_pace_snapshot(tmp_path, capacity)

    assert pace["observed_days"] == 2
    assert pace["local_submitted"] == 22
    assert pace["required_for_observed_window"] == {"one_year": 27.4, "two_year": 13.7}
    assert pace["gap_to_required_for_observed_window"]["two_year_by_local_submissions"] == 0.0


def test_rolling_pace_snapshot_ignores_probe_day_keys(tmp_path: Path) -> None:
    ledger = tmp_path / "_daily_research_paper_cycle_ledger"
    ledger.mkdir()
    (ledger / "_daily_throughput_summary.json").write_text(json.dumps({
        "days": {
            "2026-06-01": {"submitted": 2, "published": 1, "cycles": 1},
            "2026-06-01-revise-probe": {"submitted": 99, "published": 99, "cycles": 99},
        },
    }))

    pace = report._rolling_pace_snapshot(tmp_path, {"two_year": {"target": 5000, "days": 730}})

    assert pace["dates"] == ["2026-06-01"]
    assert pace["local_submitted"] == 2
    assert pace["local_published"] == 1


def test_rolling_pace_snapshot_reports_missing_source(tmp_path: Path) -> None:
    pace = report._rolling_pace_snapshot(tmp_path, {"two_year": {"target": 5000, "days": 730}})

    assert pace == {
        "window_days": 7,
        "observed_days": 0,
        "source": "_daily_throughput_summary.json",
        "status": "missing_throughput_summary",
    }


def test_summarize_includes_pace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(report, "_capacity_snapshot", lambda: {
        "one_year": {"target": 5000, "days": 365},
        "two_year": {"target": 5000, "days": 730},
    })
    monkeypatch.setattr(report, "_public_counts", lambda *_args, **_kwargs: {"decisions": {"accept": 7}})
    ledger = tmp_path / "_daily_research_paper_cycle_ledger"
    ledger.mkdir()
    (ledger / "_daily_throughput_summary.json").write_text(json.dumps({
        "days": {"2026-06-02": {"submitted": 8, "published": 6}},
    }))

    summary = report.summarize("2026-06-02", runs_root=tmp_path)

    assert summary["pace"]["today_observed"] == {
        "local_submitted": 8,
        "local_published": 6,
        "public_accepts": 7,
        "observed_published": 7,
    }
    assert summary["pace"]["today_gap_to_two_year_daily_average"]["by_public_accepts"] == 0.0
    assert summary["pace"]["today_gap_to_two_year_daily_average"]["by_observed_published"] == 0.0
    assert summary["pace"]["rolling"]["local_submitted"] == 8


def test_consistency_gate_requires_fresh_revise_submit_and_new_public_receipt() -> None:
    local = {
        "cycle_modes": {
            "fresh": {
                "started_at": "2026-06-29T12:00:00+00:00",
                "mode": "fresh",
                "status": "published",
                "submitted": 1,
                "published": 1,
            },
            "revise": {
                "started_at": "2026-06-29T12:15:00+00:00",
                "mode": "revise",
                "status": "published",
                "submitted": 1,
                "published": 1,
            },
            "daily-submit": {
                "started_at": "2026-06-29T14:15:00+00:00",
                "mode": "daily-submit",
                "status": "published",
                "submitted": 1,
                "published": 1,
            },
        },
    }
    public = {
        "decisions": {"accept": 4},
        "examples": [{
            "time": "2026-06-29T14:20:00+00:00",
            "decision": "accept",
            "title": "Accepted paper",
            "url": "https://researka.org/papers/example",
            "doi": "10.17605/OSF.IO/EXAMPLE",
        }],
    }

    gate = report._consistency_gate(
        local,
        public,
        public_accept_baseline=3,
        min_started_at="2026-06-29T11:19:00+00:00",
    )

    assert gate["pass"] is True
    assert gate["blockers"] == []
    assert gate["public_accepts_after_min_started_at"] == 1


def test_consistency_gate_reports_stale_lane_and_public_baseline_blocker() -> None:
    local = {
        "cycle_modes": {
            "fresh": {
                "started_at": "2026-06-29T08:00:00+00:00",
                "mode": "fresh",
                "status": "published",
                "submitted": 1,
                "published": 1,
            },
            "revise": {
                "started_at": "2026-06-29T12:15:00+00:00",
                "mode": "revise",
                "status": "submitted_to_researka",
                "submitted": 1,
                "published": 0,
            },
        },
    }
    public = {"decisions": {"accept": 3}, "examples": []}

    gate = report._consistency_gate(
        local,
        public,
        public_accept_baseline=3,
        min_started_at="2026-06-29T11:19:00+00:00",
    )

    assert gate["pass"] is False
    assert gate["blockers"] == [
        "fresh:stale_before_min_started_at",
        "revise:not_published",
        "daily-submit:missing_ledger",
        "public:accept_count_not_above_baseline",
        "public:no_accept_after_min_started_at",
    ]


def test_main_accepts_date_flag(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        report,
        "summarize",
        lambda date, **kwargs: {"date": date, "runs_root": str(kwargs["runs_root"])},
    )

    assert report.main(["--date", "2026-06-24", "--runs-root", str(tmp_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"date": "2026-06-24", "runs_root": str(tmp_path)}


def test_emit_json_treats_closed_pipe_as_clean_exit() -> None:
    class ClosedPipe:
        def write(self, _text: str) -> int:
            raise BrokenPipeError

    assert report._emit_json({"ok": True}, stream=ClosedPipe()) == 0  # type: ignore[arg-type]
