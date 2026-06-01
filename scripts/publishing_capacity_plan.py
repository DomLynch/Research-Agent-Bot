"""Capacity math for v3 paper publishing.

Read-only planner: separates calendar slots, topic reuse, and required success
rate so scaling decisions are explicit before changing timers.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import daily_research_paper_cycle as cycle  # noqa: E402
from source_topic_specificity import generated_pack_publishable  # noqa: E402


def _generated_records(db: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(db.glob("*/latest.json")):
        record = cycle._read_json(path)
        if record:
            out.append(record)
    return out


def capacity_plan(
    *,
    target: int,
    years: float,
    interval_minutes: int,
    topic_count: int,
    generated_records: int,
    generated_publishable: int,
    cooldown_days: int,
) -> dict[str, Any]:
    days = int(round(years * 365))
    calendar_slots = int((days * 24 * 60) // interval_minutes)
    topic_reuse_capacity = int(topic_count * days // max(1, cooldown_days))
    capacity_limited_by = min(calendar_slots, topic_reuse_capacity)
    required_success_rate = target / calendar_slots if calendar_slots else 1.0
    generated_publishable_ratio = generated_publishable / generated_records if generated_records else 0.0
    required_interval_minutes = (days * 24 * 60) / target if target else 0.0
    calendar_gap = max(0, target - calendar_slots)
    topic_gap = max(0, target - topic_reuse_capacity)
    publishable_ratio_gap = max(0.0, required_success_rate - generated_publishable_ratio)
    slots_at_current_ratio = math.ceil(target / generated_publishable_ratio) if generated_publishable_ratio else 0
    interval_at_current_ratio = (days * 24 * 60) / slots_at_current_ratio if slots_at_current_ratio else 0.0
    lanes_at_current_ratio = math.ceil(slots_at_current_ratio / calendar_slots) if calendar_slots and slots_at_current_ratio else 0
    lanes_at_perfect_success = math.ceil(target / calendar_slots) if calendar_slots and target else 0
    target_reachable = capacity_limited_by >= target and required_success_rate <= 1.0 and publishable_ratio_gap == 0
    return {
        "target": target,
        "years": years,
        "days": days,
        "interval_minutes": interval_minutes,
        "calendar_slots": calendar_slots,
        "topic_count": topic_count,
        "generated_records": generated_records,
        "generated_publishable": generated_publishable,
        "generated_publishable_ratio": round(generated_publishable_ratio, 3),
        "cooldown_days": cooldown_days,
        "topic_reuse_capacity": topic_reuse_capacity,
        "capacity_limited_by": capacity_limited_by,
        "calendar_limited": calendar_slots < target,
        "calendar_gap_to_target": calendar_gap,
        "topic_limited": topic_reuse_capacity < target,
        "topic_gap_to_target": topic_gap,
        "slot_target_reachable_at_current_interval": capacity_limited_by >= target and required_success_rate <= 1.0,
        "publishable_ratio_limited": publishable_ratio_gap > 0,
        "publishable_ratio_gap_to_required_success_rate": round(publishable_ratio_gap, 3),
        "target_reachable_at_current_interval": target_reachable,
        "required_success_rate": round(required_success_rate, 3),
        "required_interval_minutes_at_100pct_success": round(required_interval_minutes, 1),
        "mitigation_at_100pct_success": {
            "extra_slots_to_target": calendar_gap,
            "extra_slots_per_day": round(calendar_gap / days, 2) if days else 0.0,
            "required_interval_minutes": round(required_interval_minutes, 1),
        },
        "mitigation_at_current_publishable_ratio": {
            "required_slots": slots_at_current_ratio,
            "extra_slots_to_target": max(0, slots_at_current_ratio - calendar_slots),
            "extra_slots_per_day": round(max(0, slots_at_current_ratio - calendar_slots) / days, 2) if days else 0.0,
            "required_interval_minutes": round(interval_at_current_ratio, 1),
        },
        "operational_strategy": {
            "keep_current_interval": target_reachable,
            "two_hour_lanes_required_at_100pct_success": lanes_at_perfect_success,
            "two_hour_lanes_required_at_current_publishable_ratio": lanes_at_current_ratio,
            "additional_two_hour_lanes_required_at_current_ratio": max(0, lanes_at_current_ratio - 1),
            "recommended_path": (
                "keep_current_2h_lane"
                if target_reachable
                else "add_parallel_2h_lane_or_raise_success_rate_before_shortening_interval"
            ),
        },
    }


def live_plan(*, target: int, years: float, interval_minutes: int) -> dict[str, Any]:
    records = _generated_records(cycle.TOPIC_PACKS_DB)
    publishable = sum(1 for record in records if generated_pack_publishable(record, peer_records=records))
    topics = cycle.discover_topics()
    return capacity_plan(
        target=target,
        years=years,
        interval_minutes=interval_minutes,
        topic_count=len(topics),
        generated_records=len(records),
        generated_publishable=publishable,
        cooldown_days=cycle.PUBLISHED_TOPIC_COOLDOWN_DAYS,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=5000)
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--interval-minutes", type=int, default=120)
    args = parser.parse_args(argv)
    print(json.dumps(live_plan(target=args.target, years=args.years, interval_minutes=args.interval_minutes), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
