"""Capacity math for v3 paper publishing.

Read-only planner: separates calendar slots, topic reuse, and required success
rate so scaling decisions are explicit before changing timers.
"""
from __future__ import annotations

import argparse
import json
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
    required_interval_minutes = (days * 24 * 60) / target if target else 0.0
    return {
        "target": target,
        "years": years,
        "days": days,
        "interval_minutes": interval_minutes,
        "calendar_slots": calendar_slots,
        "topic_count": topic_count,
        "generated_records": generated_records,
        "generated_publishable": generated_publishable,
        "generated_publishable_ratio": round(generated_publishable / generated_records, 3) if generated_records else 0.0,
        "cooldown_days": cooldown_days,
        "topic_reuse_capacity": topic_reuse_capacity,
        "capacity_limited_by": capacity_limited_by,
        "calendar_limited": calendar_slots < target,
        "topic_limited": topic_reuse_capacity < target,
        "required_success_rate": round(required_success_rate, 3),
        "required_interval_minutes_at_100pct_success": round(required_interval_minutes, 1),
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
