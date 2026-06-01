from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

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
