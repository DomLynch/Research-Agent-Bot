"""Pure candidate-buffer validation shared by prepare and fresh selection."""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from typing import Any

from .io import parse_time
from .policy import (
    CandidateEvidence,
    CandidateThresholds,
    decide_candidate,
)

def precision_was_valid(
    status: str,
    quant_claims: int,
    *,
    minimum_quant_claims: int,
    precision_floor: float,
) -> bool:
    pattern = (
        rf"source_topic_precision_(?:ok:(\d+)/(\d+)|scoped_floor:(\d+)>=(\d+)"
        rf"\(ratio=(\d+)/(\d+)<{re.escape(f'{precision_floor:.2f}')}\))"
    )
    match = re.fullmatch(pattern, status)
    if not match:
        return False
    if match.group(1):
        hits, total = map(int, match.groups()[:2])
        return (
            0 < total == quant_claims
            and hits <= total
            and hits / total >= precision_floor
        )
    retained, minimum, hits, total = map(int, match.groups()[2:])
    return (
        0 < total == quant_claims
        and hits <= total
        and retained <= total
        and retained >= minimum >= minimum_quant_claims
        and hits / total < precision_floor
    )


def prepared_candidate_rows(
    report: Mapping[str, Any],
    *,
    thresholds: CandidateThresholds,
    now: dt.datetime,
    max_age_hours: int,
    precision_floor: float,
) -> dict[str, dict[str, Any]]:
    if report.get("thresholds") != thresholds.as_dict():
        return {}
    cutoff = now - dt.timedelta(hours=max_age_hours)
    prepared: dict[str, dict[str, Any]] = {}
    rows = report.get("ready")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        validated_at = parse_time(str(row.get("validated_at") or ""))
        topic = str(row.get("topic") or "")
        if topic and validated_at and validated_at >= cutoff:
            prepared[topic] = row

    attempts = report.get("attempts")
    for row in attempts if isinstance(attempts, list) else []:
        if not isinstance(row, dict):
            continue
        preflight = row.get("receipt_preflight")
        if not isinstance(preflight, dict) or preflight.get("passed") is not True:
            continue
        try:
            quant_claims = int(row.get("quant_claims") or 0)
            evidence = CandidateEvidence(
                n_quant_claims=quant_claims,
                n_receipts=int(preflight.get("n_receipts") or 0),
                n_primary_tier=int(preflight.get("n_primary_tier") or 0),
                n_direct_receipts=int(preflight.get("n_direct_receipts") or 0),
                source_precision_ok=precision_was_valid(
                    str(row.get("source_topic_precision_after") or ""),
                    quant_claims,
                    minimum_quant_claims=thresholds.min_quant_claims,
                    precision_floor=precision_floor,
                ),
            )
        except (TypeError, ValueError):
            continue
        topic = str(row.get("topic") or "")
        attempted_at = parse_time(str(row.get("attempted_at") or ""))
        decision = decide_candidate(
            topic,
            review_type=None,
            evidence=evidence,
            thresholds=thresholds,
        )
        if (
            not topic
            or not attempted_at
            or attempted_at < cutoff
            or not decision.ready_for_synthesis
        ):
            continue
        prepared[topic] = {
            "topic": topic,
            "validated_at": attempted_at.isoformat(),
            "n_quant_claims": quant_claims,
            "n_receipts": evidence.n_receipts,
            "n_primary_tier": evidence.n_primary_tier,
            "n_direct_receipts": evidence.n_direct_receipts,
            "source_topic_precision": row.get("source_topic_precision_after"),
        }
    return prepared


def recent_attempts(
    report: Mapping[str, Any],
    *,
    now: dt.datetime,
    max_age_hours: int,
) -> list[dict[str, Any]]:
    cutoff = now - dt.timedelta(hours=max_age_hours)
    fallback = parse_time(str(report.get("generated_at") or ""))
    rows = report.get("attempts")
    recent: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        attempted_at = parse_time(str(row.get("attempted_at") or "")) or fallback
        if attempted_at and attempted_at >= cutoff:
            recent.append({**row, "attempted_at": attempted_at.isoformat()})
    return recent


def buffer_status(ready_count: int, target_ready: int) -> str:
    if ready_count >= target_ready:
        return "candidate_buffer_ready"
    return "candidate_buffer_partial" if ready_count else "candidate_buffer_depleted"
