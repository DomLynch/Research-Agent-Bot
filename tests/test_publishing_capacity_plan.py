from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import publishing_capacity_plan as planner  # type: ignore[import-not-found]  # noqa: E402
from publishing_capacity_plan import capacity_plan  # type: ignore[import-not-found]  # noqa: E402


def test_capacity_plan_names_calendar_limit_for_one_year_two_hour_cadence() -> None:
    plan = capacity_plan(
        target=5000,
        years=1,
        interval_minutes=120,
        topic_count=285,
        generated_records=331,
        generated_publishable=183,
        cooldown_days=21,
    )

    assert plan["calendar_slots"] == 4380
    assert plan["topic_reuse_capacity"] == 4953
    assert plan["calendar_limited"] is True
    assert plan["topic_limited"] is True
    assert plan["calendar_gap_to_target"] == 620
    assert plan["topic_gap_to_target"] == 47
    assert plan["slot_target_reachable_at_current_interval"] is False
    assert plan["publishable_ratio_limited"] is True
    assert plan["target_reachable_at_current_interval"] is False
    assert plan["required_interval_minutes_at_100pct_success"] == 105.1
    assert plan["mitigation_at_100pct_success"] == {
        "extra_slots_to_target": 620,
        "extra_slots_per_day": 1.7,
        "required_interval_minutes": 105.1,
    }
    assert plan["mitigation_at_current_publishable_ratio"] == {
        "required_slots": 9044,
        "extra_slots_to_target": 4664,
        "extra_slots_per_day": 12.78,
        "required_interval_minutes": 58.1,
    }
    assert plan["operational_strategy"] == {
        "keep_current_interval": False,
        "two_hour_lanes_required_at_100pct_success": 2,
        "two_hour_lanes_required_at_current_publishable_ratio": 3,
        "additional_two_hour_lanes_required_at_current_ratio": 2,
        "recommended_path": "add_parallel_2h_lane_or_raise_success_rate_before_shortening_interval",
    }


def test_capacity_plan_shows_two_year_goal_needs_publishable_ratio_lift() -> None:
    plan = capacity_plan(
        target=5000,
        years=2,
        interval_minutes=120,
        topic_count=285,
        generated_records=331,
        generated_publishable=183,
        cooldown_days=21,
    )

    assert plan["calendar_slots"] == 8760
    assert plan["topic_reuse_capacity"] == 9907
    assert plan["calendar_limited"] is False
    assert plan["topic_limited"] is False
    assert plan["slot_target_reachable_at_current_interval"] is True
    assert plan["publishable_ratio_limited"] is True
    assert plan["target_reachable_at_current_interval"] is False
    assert plan["required_success_rate"] == 0.571
    assert plan["generated_publishable_ratio"] == 0.553
    assert plan["publishable_ratio_gap_to_required_success_rate"] == 0.018
    assert plan["mitigation_at_100pct_success"]["extra_slots_to_target"] == 0
    assert plan["mitigation_at_current_publishable_ratio"]["required_interval_minutes"] == 116.2
    assert plan["operational_strategy"]["additional_two_hour_lanes_required_at_current_ratio"] == 1
    assert plan["operational_strategy"]["recommended_path"] == "add_parallel_2h_lane_or_raise_success_rate_before_shortening_interval"


def test_capacity_plan_two_year_live_ratio_keeps_single_two_hour_lane() -> None:
    plan = capacity_plan(
        target=5000,
        years=2,
        interval_minutes=120,
        topic_count=331,
        generated_records=387,
        generated_publishable=229,
        cooldown_days=21,
    )

    assert plan["target_reachable_at_current_interval"] is True
    assert plan["operational_strategy"] == {
        "keep_current_interval": True,
        "two_hour_lanes_required_at_100pct_success": 1,
        "two_hour_lanes_required_at_current_publishable_ratio": 1,
        "additional_two_hour_lanes_required_at_current_ratio": 0,
        "recommended_path": "keep_current_2h_lane",
    }


def test_capacity_plan_includes_unique_topic_expansion_path() -> None:
    plan = capacity_plan(
        target=5000,
        years=2,
        interval_minutes=120,
        topic_count=331,
        generated_records=387,
        generated_publishable=229,
        cooldown_days=21,
        known_unique_topics=489,
        submitted_unique_topics=35,
        expansion_candidates=[{"topic": "PCSK9", "slug": "pcsk9", "candidate_count": 90}],
    )

    assert plan["unique_topic_expansion"] == {
        "known_unique_topics": 489,
        "submitted_unique_topics": 35,
        "remaining_known_unique_topics": 454,
        "publishable_topic_shortfall_vs_target": 4669,
        "known_unique_topic_shortfall_vs_target": 4511,
        "new_unique_topics_needed_per_day": 6.18,
        "fact_materializer_rows_needed": 4511,
        "materializer_projection_command": "python scripts/materialize_fact_topic_packs.py --limit 4511",
        "materializer_persist_rule": "persist only if projection.created > 0",
        "capacity_warning": "run materializer projection against live fact rows; current grouped fact topics may be exhausted",
        "next_generated_candidates": [{"topic": "PCSK9", "slug": "pcsk9", "candidate_count": 90}],
    }


def test_live_plan_counts_submitted_topics_and_expansion_candidates(tmp_path: Path, monkeypatch) -> None:
    topic_packs = tmp_path / "topic_packs"
    topic_db = tmp_path / "topic_packs_db"
    runs = tmp_path / "runs"
    topic_packs.mkdir()
    (topic_packs / "curcumin.toml").write_text("aliases = ['curcumin']\n", encoding="utf-8")
    (topic_db / "senescence_biomarker_effects").mkdir(parents=True)
    (topic_db / "pcsk9_inhibitors_longevity").mkdir(parents=True)
    for slug, topic, count in [
        ("senescence_biomarker_effects", "senescence biomarker effects", 12),
        ("pcsk9_inhibitors_longevity", "PCSK9 inhibitors longevity", 80),
    ]:
        (topic_db / slug / "latest.json").write_text(
            '{"candidate_count": %d, "pack_data": {"topic": "%s", "aliases": ["%s"], "retrieval": {"topic_terms": ["%s"]}}}'
            % (count, topic, topic, topic),
            encoding="utf-8",
        )
    submitted = runs / "_daily_research_paper_ledger"
    submitted.mkdir(parents=True)
    (submitted / "_submitted_fingerprints.json").write_text(
        '[{"topic": "curcumin"}, {"topic": "pcsk9_inhibitors_longevity"}]',
        encoding="utf-8",
    )

    monkeypatch.setattr(planner.cycle, "TOPIC_PACKS", topic_packs)
    monkeypatch.setattr(planner.cycle, "TOPIC_PACKS_DB", topic_db)
    monkeypatch.setattr(planner.cycle, "RUNS", runs)

    plan = planner.live_plan(target=5000, years=2, interval_minutes=120)

    assert plan["unique_topic_expansion"]["known_unique_topics"] == 3
    assert plan["unique_topic_expansion"]["submitted_unique_topics"] == 2
    assert plan["unique_topic_expansion"]["next_generated_candidates"][0]["slug"] == "pcsk9_inhibitors_longevity"
