"""Contemporaneous, source-level admission decisions; never reconstructed history."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

RULE = "role-aware-source-admission-v1"
RULE_TEXT = (
    "Admit sources in the active or classified candidate set with high-confidence bound claims, "
    "or partial bound claims from the retained/classified set. Require topic-specific source identity "
    "and an active-topic mention; exclude known retractions. Direct evidence additionally requires "
    "topic-specific bibliographic identity. Non-randomized partial-only evidence is review-tier context. "
    "For at least 12 sources, prune non-interventional animal context only when at least three core "
    "sources are human and humans outnumber animals, provided at least 12 sources remain. "
    "Deduplicate sources and check DOI retractions. "
    "Protocols remain planned research, without completed outcome evidence."
)


def start(topic: str, retained: frozenset[str]) -> dict[str, Any]:
    rule = ("Reassess the frozen included sources for admissible bound claims and known retractions; "
            "preserve source identities and only explicitly authorized classification changes. "
            "Original selection is documented by the accompanying candidate assessment. "
            "Protocols provide planned-study context only.") if retained else RULE_TEXT
    return {"rule_version": RULE, "rule": rule, "assessed_at": datetime.now(timezone.utc).isoformat(),
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


def check(run: Path, paper: str) -> str:
    from agent.revision_contract import evidence_rows
    from agent.revision_contract import final_source_integrity
    from agent.selection_flow import render_admission
    try:
        manifest = json.loads((run / "manifest.json").read_text())
        log = json.loads((run / "source_admission.json").read_text())
        rows = evidence_rows(run, manifest)
        if not validate(log, rows) or log != manifest.get("receipt_funnel", {}).get("source_admission"):
            return "source_admission_unverified"
        if log.get("scope") == "retained-source reassessment" and not validate(log.get("selection_assessment"), rows):
            return "source_selection_assessment_missing"
        if render_admission(log) not in paper:
            return "source_admission_methods_mismatch"
        return "eligible" if final_source_integrity(paper, rows) else "final_source_accounting_invalid"
    except (OSError, ValueError, TypeError, KeyError):
        return "source_admission_missing_or_invalid"


def deduplicate(receipts: Any, log: dict[str, Any], continuity: dict[str, Any]) -> Any:
    from agent.synthesis import dedupe_receipts
    selected = list(dedupe_receipts(receipts))
    retain(log, selected, "duplicate_source")
    continuity["duplicate_receipts_removed"] = len(receipts) - len(selected)
    return selected


def finish(log: dict[str, Any], receipts: Any, funnel: dict[str, Any], out_dir: Path) -> None:
    retain(log, receipts, "doi_retraction_exclusion")
    if log["scope"] == "retained-source reassessment":
        log["selection_assessment"] = json.loads((out_dir / "source_selection_assessment.json").read_text())
    funnel["source_admission"] = log
    (out_dir / "source_admission.json").write_text(json.dumps(log, indent=2))


def prepare_reassessment(topic: str, lock: Any, out_dir: Path, assess: Any) -> None:
    """Assess saved candidates before switching the runner to the frozen subset."""
    if lock.errors or not lock.source_run:
        return
    prior_path = lock.source_run / "source_admission.json"
    if prior_path.is_file():
        prior = json.loads(prior_path.read_text())
        log = prior.get("selection_assessment", prior)
    else:
        log = start(topic, frozenset())
        deduplicate(assess(topic, admission_log=log), log, {})
        log["scope"] = "new assessment of saved candidate corpus"
    if not validate(log, [{"receipt_id": rid} for rid in lock.receipt_ids]):
        raise ValueError("selection_reassessment_changes_included_set: scientific review required")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source_selection_assessment.json").write_text(json.dumps(log, indent=2))
