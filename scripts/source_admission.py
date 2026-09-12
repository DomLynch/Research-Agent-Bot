"""Contemporaneous, source-level admission decisions; never reconstructed history."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

RULE = "role-aware-source-admission-v1"
RULE_TEXT = (
    "Admit sources in the active or classified candidate set with high-confidence bound claims, "
    "or partial bound claims from the retained/classified set. Require topic-specific source identity "
    "and an active-topic mention; exclude known retractions. Direct evidence additionally requires "
    "topic-specific bibliographic identity. Non-randomized partial-only evidence is review-tier context. "
    "Apply the recorded human-population coherence rule, deduplicate sources and check DOI retractions. "
    "Protocols remain planned research, without completed outcome evidence."
)


def start(topic: str, retained: frozenset[str]) -> dict[str, Any]:
    return {"rule_version": RULE, "rule": RULE_TEXT, "assessed_at": datetime.now(timezone.utc).isoformat(),
            "topic": topic, "scope": "retained-source reassessment" if retained else "candidate admission",
            "historical_screening_reconstructed": False, "decisions": {}}


def record(log: dict[str, Any] | None, source_id: str, reason: str, *, included: bool = False) -> None:
    if log is not None:
        log["decisions"][source_id] = {"source_id": source_id, "included": included, "reason": reason}


def retain(log: dict[str, Any] | None, receipts: Any, reason: str) -> None:
    if log is not None:
        ids = {r.receipt_id for r in receipts}
        for source_id, row in log["decisions"].items():
            if row["included"] and source_id not in ids:
                record(log, source_id, reason)


def validate(log: Any, rows: list[dict[str, Any]]) -> bool:
    if not isinstance(log, dict) or not all(log.get(key) for key in ("rule_version", "rule", "assessed_at", "scope", "decisions")):
        return False
    decisions = log["decisions"]
    if not isinstance(decisions, dict) or any(not isinstance(r, dict) or r.get("source_id") != key
            or type(r.get("included")) is not bool or not r.get("reason") for key, r in decisions.items()):
        return False
    return {key for key, row in decisions.items() if row["included"]} == {row.get("receipt_id") for row in rows}


def render(log: dict[str, Any]) -> str:
    decisions = log["decisions"]
    included = sum(row["included"] for row in decisions.values())
    excluded = Counter(row["reason"] for row in decisions.values() if not row["included"])
    reasons = "; ".join(f"{reason.replace('_', ' ')}: {count}" for reason, count in sorted(excluded.items())) or "none"
    return (f"Selection assessment ({log['scope']}) dated {log['assessed_at']}, rule {log['rule_version']}: "
            f"{log['rule']} Assessed {len(decisions)} candidate sources; included {included}; "
            f"excluded {len(decisions) - included}. Exclusion reasons: {reasons}. "
            "The source-by-source decisions and identifiers are in source_admission.json. "
            "This assessment records the stated candidate scope on this date; it does not reconstruct "
            "unrecorded historical screening or equate retrieval totals with assessed candidates.")
