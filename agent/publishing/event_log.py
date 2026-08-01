"""Derived unique-candidate funnel over existing V3 ledgers."""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .io import AtomicJsonState, CorruptJsonState

_STAGES = (
    "discovered", "prepared", "synthesized", "local_gate_pass",
    "submitted", "revise", "accepted",
)
_NON_BLOCKING = {"", "eligible", "published", "submitted_to_researka"}
_DAY_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _rows(value: object) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _candidate_id(row: Mapping[str, Any], fallback: str) -> str:
    nested = row.get("candidate")
    candidate = nested if isinstance(nested, dict) else {}
    topic = str(row.get("topic") or candidate.get("topic") or "")
    raw = str(
        row.get("out_dir")
        or row.get("run")
        or candidate.get("out_dir")
        or candidate.get("run")
        or fallback
    )
    legacy_topic = re.match(r"^synthesis-(.+?)-v\d+(?:-|$)", raw, re.I)
    raw = topic or (legacy_topic.group(1) if legacy_topic else raw)
    return re.sub(r"-R\d+$", "", raw, flags=re.I)


def _record(
    row: Mapping[str, Any],
    fallback: str,
    stages: dict[str, set[str]],
    blockers: dict[str, set[str]],
) -> str:
    candidate_id = _candidate_id(row, fallback)
    status = str(
        row.get("gate_status")
        or row.get("submit_status")
        or row.get("reason")
        or row.get("status")
        or ""
    )
    submitted = int(row.get("submitted") or 0)
    published = int(row.get("published") or 0)
    stages["discovered"].add(candidate_id)
    if status == "eligible" or submitted:
        stages["local_gate_pass"].add(candidate_id)
    if submitted:
        stages["submitted"].add(candidate_id)
    if "revise" in status or row.get("remote_revision_requested"):
        stages["revise"].add(candidate_id)
    if published:
        stages["accepted"].add(candidate_id)
    if status not in _NON_BLOCKING:
        blockers.setdefault(status.split(":", 1)[0], set()).add(candidate_id)
    return candidate_id


def conversion_funnel(ledgers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    stages: dict[str, set[str]] = {stage: set() for stage in _STAGES}
    blockers: dict[str, set[str]] = {}
    for ledger in ledgers:
        ledger_id = str(ledger.get("ledger") or "ledger")
        aggregate = ledger.get("candidate")
        aggregate = aggregate if isinstance(aggregate, dict) else {}
        aggregate_run = str(aggregate.get("run") or "")
        aggregate_topic = str(aggregate.get("topic") or "")
        run_topics = {aggregate_run: aggregate_topic} if aggregate_run and aggregate_topic else {}
        for submission in _rows(ledger.get("submissions")):
            child = submission.get("candidate")
            if not isinstance(child, dict):
                continue
            run = str(child.get("run") or "")
            topic = str(child.get("topic") or "")
            if run and topic:
                run_topics[run] = topic
        for index, row in enumerate(_rows(ledger.get("attempts"))):
            candidate_id = _record(row, f"{ledger_id}:attempt-{index}", stages, blockers)
            receipt = row.get("receipt_preflight")
            preflight = row.get("preflight")
            if (
                isinstance(receipt, dict) and receipt.get("passed") is True
                or isinstance(preflight, dict) and preflight.get("passed") is True
            ):
                stages["prepared"].add(candidate_id)
            if row.get("synthesis_return_code") == 0:
                stages["synthesized"].add(candidate_id)
        for key in ("considered", "submissions"):
            for index, row in enumerate(_rows(ledger.get(key))):
                candidate = row.get("candidate")
                merged = {**(candidate if isinstance(candidate, dict) else {}), **row}
                mapped_topic = run_topics.get(str(merged.get("run") or ""))
                if (
                    key == "considered"
                    and not merged.get("topic")
                    and mapped_topic
                ):
                    merged["topic"] = mapped_topic
                _record(merged, f"{ledger_id}:{key}-{index}", stages, blockers)
        for index, row in enumerate(_rows(ledger.get("ready"))):
            candidate_id = _candidate_id(row, f"{ledger_id}:ready-{index}")
            stages["discovered"].add(candidate_id)
            stages["prepared"].add(candidate_id)
        candidate = aggregate
        if not _rows(ledger.get("submissions")) and (
            isinstance(candidate, dict) and candidate
            or ledger.get("submitted_run")
            or ledger.get("attempted_topic")
            or ledger.get("topic")
        ):
            merged = {**(candidate if isinstance(candidate, dict) else {}), **ledger}
            _record(merged, ledger_id, stages, blockers)
    ranked = sorted(
        ((code, len(candidates)) for code, candidates in blockers.items()),
        key=lambda item: (-item[1], item[0]),
    )[:8]
    return {stage: len(stages[stage]) for stage in _STAGES} | {
        "top_unique_blockers": dict(ranked)
    }


def record_daily_throughput(
    ledger_dir: Path,
    ledger: Mapping[str, Any],
    *,
    filename: str = "_daily_throughput_summary.json",
) -> None:
    """Update the existing derived throughput view idempotently."""
    date = str(ledger.get("date") or "")
    started_at = str(ledger.get("started_at") or "")
    if not _DAY_KEY_RE.fullmatch(date) or not started_at:
        return
    path = ledger_dir / filename
    run_id = f"{ledger.get('mode') or 'mixed'}:{started_at}"
    run_row = {
        "run_id": run_id,
        "mode": ledger.get("mode") or "mixed",
        "status": ledger.get("status") or "unknown",
        "submitted": int(ledger.get("submitted") or 0),
        "published": int(ledger.get("published") or 0),
        "topic": (
            ledger.get("submitted_topic")
            or ledger.get("topic")
            or ledger.get("attempted_topic")
        ),
        "started_at": started_at,
    }

    def update(data: dict[str, Any]) -> None:
        days = data.get("days")
        if days is not None and not isinstance(days, dict):
            raise CorruptJsonState(f"{path}: days is not an object")
        days = days or {}
        day = days.get(date)
        if day is not None and not isinstance(day, dict):
            raise CorruptJsonState(f"{path}: day {date} is not an object")
        day = day or {}
        runs = day.get("runs")
        if runs is not None and not isinstance(runs, list):
            raise CorruptJsonState(f"{path}: day {date} runs is not a list")
        runs = runs or []
        existing = next(
            (run for run in runs if isinstance(run, dict) and run.get("run_id") == run_id),
            None,
        )
        existing.update(run_row) if existing is not None else runs.append(run_row)
        day.update({
            "runs": runs,
            "submitted": sum(int(run.get("submitted") or 0) for run in _rows(runs)),
            "published": sum(int(run.get("published") or 0) for run in _rows(runs)),
            "cycles": len(_rows(runs)),
            "latest_status": max(
                _rows(runs),
                key=lambda run: str(run.get("started_at") or ""),
                default={},
            ).get("status") or "unknown",
            "updated_at": dt.datetime.now(dt.UTC).isoformat(),
        })
        days[date] = day
        data["days"] = days

    AtomicJsonState[dict[str, Any]](path, dict).update(update, missing_factory=dict)
