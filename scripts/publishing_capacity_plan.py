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
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import daily_research_paper_cycle as cycle  # noqa: E402
from source_topic_specificity import generated_pack_publishable  # noqa: E402

RECOMMENDED_SUCCESS_BUFFER = 0.60


def _generated_records(db: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(db.glob("*/latest.json")):
        record = cycle._read_json(path)
        if record:
            record = dict(record)
            record["_slug"] = path.parent.name
            out.append(record)
    return out


def _submitted_topics() -> set[str]:
    try:
        rows = json.loads((cycle.RUNS / "_daily_research_paper_ledger" / "_submitted_fingerprints.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rows = []
    if isinstance(rows, list):
        return {str(row.get("topic") or "") for row in rows if isinstance(row, dict) and row.get("topic")}
    return set()


def _expansion_candidates(records: Sequence[dict[str, Any]], topics: set[str], *, limit: int = 12) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for record in records:
        slug = str(record.get("_slug") or "")
        if slug not in topics or not generated_pack_publishable(record, peer_records=records):
            continue
        pack = record.get("pack_data") if isinstance(record.get("pack_data"), dict) else {}
        candidates.append({
            "topic": str(pack.get("topic") or slug.replace("_", " ")) if isinstance(pack, dict) else slug.replace("_", " "),
            "slug": slug,
            "candidate_count": int(record.get("candidate_count") or 0),
        })
    return sorted(candidates, key=lambda item: (-item["candidate_count"], item["slug"]))[:limit]


def capacity_plan(
    *,
    target: int,
    years: float,
    interval_minutes: int,
    topic_count: int,
    generated_records: int,
    generated_publishable: int,
    cooldown_days: int,
    known_unique_topics: int | None = None,
    submitted_unique_topics: int = 0,
    expansion_candidates: Sequence[dict[str, Any]] = (),
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
    buffer_gap = max(0.0, RECOMMENDED_SUCCESS_BUFFER - generated_publishable_ratio)
    ratio_margin = generated_publishable_ratio - required_success_rate
    slots_at_current_ratio = math.ceil(target / generated_publishable_ratio) if generated_publishable_ratio else 0
    interval_at_current_ratio = (days * 24 * 60) / slots_at_current_ratio if slots_at_current_ratio else 0.0
    lanes_at_current_ratio = math.ceil(slots_at_current_ratio / calendar_slots) if calendar_slots and slots_at_current_ratio else 0
    lanes_at_perfect_success = math.ceil(target / calendar_slots) if calendar_slots and target else 0
    target_reachable = capacity_limited_by >= target and required_success_rate <= 1.0 and publishable_ratio_gap == 0
    unique_topics = topic_count if known_unique_topics is None else known_unique_topics
    unique_gap = max(0, target - unique_topics)
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
        "publishable_ratio_buffer": {
            "minimum_recommended": RECOMMENDED_SUCCESS_BUFFER,
            "margin_to_required_success_rate": round(ratio_margin, 3),
            "meets_recommended_buffer": buffer_gap == 0,
            "buffer_gap_to_minimum_recommended": round(buffer_gap, 3),
            "warning": (
                "thin_margin"
                if ratio_margin >= 0 and buffer_gap > 0
                else "below_required_success_rate" if ratio_margin < 0 else "ok"
            ),
        },
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
        "unique_topic_expansion": {
            "known_unique_topics": unique_topics,
            "submitted_unique_topics": submitted_unique_topics,
            "remaining_known_unique_topics": max(0, unique_topics - submitted_unique_topics),
            "publishable_topic_shortfall_vs_target": max(0, target - topic_count),
            "known_unique_topic_shortfall_vs_target": unique_gap,
            "new_unique_topics_needed_per_day": round(unique_gap / days, 2) if days else 0.0,
            "fact_materializer_rows_needed": unique_gap,
            "materializer_projection_command": (
                f"python scripts/materialize_fact_topic_packs.py --limit {unique_gap}"
                if unique_gap else "none"
            ),
            "field_cross_projection_command": (
                f"python scripts/materialize_fact_topic_packs.py --strategy fact-field-cross --limit {unique_gap}"
                if unique_gap else "none"
            ),
            "materializer_persist_rule": "persist only if projection.created > 0",
            "capacity_warning": (
                "run materializer projection against live fact rows; current grouped fact topics may be exhausted"
                if unique_gap else "none"
            ),
            "next_strategy": (
                "if grouped projection creates 0, run fact-field-cross projection; persist only specific packs that pass peer specificity"
                if unique_gap else "none"
            ),
            "next_generated_candidates": list(expansion_candidates),
        },
    }


def live_plan(*, target: int, years: float, interval_minutes: int) -> dict[str, Any]:
    records = _generated_records(cycle.TOPIC_PACKS_DB)
    publishable = sum(1 for record in records if generated_pack_publishable(record, peer_records=records))
    topics = cycle.discover_topics()
    static_topics = {path.stem for path in cycle.TOPIC_PACKS.glob("*.toml") if not path.stem.startswith("_")}
    generated_topics = {str(record.get("_slug") or "") for record in records if record.get("_slug")}
    topic_set = set(topics)
    return capacity_plan(
        target=target,
        years=years,
        interval_minutes=interval_minutes,
        topic_count=len(topics),
        generated_records=len(records),
        generated_publishable=publishable,
        cooldown_days=cycle.PUBLISHED_TOPIC_COOLDOWN_DAYS,
        known_unique_topics=len(static_topics | generated_topics),
        submitted_unique_topics=len(_submitted_topics()),
        expansion_candidates=_expansion_candidates(records, topic_set),
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
