"""Contemporaneous, source-level admission decisions; never reconstructed history."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
from typing import Any
from agent.publishing.io import atomic_write_json

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
    while isinstance(log, dict) and all(log.get(key) for key in ("rule_version", "rule", "assessed_at", "scope", "decisions")):
        decisions = log["decisions"]
        if not isinstance(decisions, dict) or any(not isinstance(r, dict) or r.get("source_id") != key
                or type(r.get("included")) is not bool or not r.get("reason") for key, r in decisions.items()):
            return False
        if {key for key, row in decisions.items() if row["included"]} != {row.get("receipt_id") for row in rows}:
            return False
        if log["scope"] != "retained-source reassessment":
            return True
        excluded = log.get("reviewer_excluded_source_ids", [])
        if not isinstance(excluded, list) or any(not isinstance(rid, str) or not rid for rid in excluded):
            return False
        if len(set(excluded)) != len(excluded) or set(excluded) & {row["receipt_id"] for row in rows}:
            return False
        rows = rows + [{"receipt_id": rid} for rid in excluded]
        log = log.get("selection_assessment")
    return False


def check(run: Path, paper: str) -> str:
    from agent.revision_contract import evidence_rows, final_source_integrity
    from agent.selection_flow import render_admission
    try:
        manifest = json.loads((run / "manifest.json").read_text())
        log = json.loads((run / "source_admission.json").read_text())
        rows = evidence_rows(run, manifest)
        if not validate(log, rows) or log != manifest.get("receipt_funnel", {}).get("source_admission"):
            return "source_admission_unverified"
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


def _saved_candidate_links(records: dict[str, Any], source_ids: Any, corpus_root: Path) -> dict[str, dict[str, str]]:
    def normalized(value: Any) -> str:
        return " ".join(str(value or "").casefold().split())
    index: dict[tuple[str, str], set[str]] = {}
    for key, row in records.items():
        for field in ("doi", "title"):
            if value := normalized(row.get(field)):
                index.setdefault((field, value), set()).add(key)
    links = {}
    for source_id in source_ids:
        path = corpus_root / "parsed" / f"{source_id}.paper_sections.json"
        doc = json.loads(path.read_text()) if path.is_file() else {}
        for field in ("doi", "title"):
            candidates = index.get((field, normalized(doc.get(field))), set())
            if len(candidates) == 1 and (field != "title" or not normalized(doc.get("doi")) or normalized(records[next(iter(candidates))].get("doi")) in {"", normalized(doc.get("doi"))}):
                links[source_id] = {"metadata_id": next(iter(candidates)), "matched_by": field}
                break
    return links


def reconcile_saved_candidates(log: dict[str, Any], corpus_root: Path) -> None:
    """Date an identifier crosswalk; never infer unrecorded historical screening."""
    while log.get("selection_assessment"):
        log = log["selection_assessment"]
    path = corpus_root / "corpus_manifest.json"
    if log.get("selection_provenance") or not path.is_file():
        return
    raw = path.read_bytes()
    entries = json.loads(raw).get("entries", [])
    if not entries:
        return
    records = {row["paper_id"]: row for row in entries}
    if len(records) != len(entries) or any(type(row.get("keep_for_extraction")) is not bool for row in entries):
        raise ValueError("selection_metadata_identity_or_decision_invalid")
    links = _saved_candidate_links(records, log["decisions"], corpus_root)
    linked = {row["metadata_id"] for row in links.values()}
    kept = {key for key, row in records.items() if row["keep_for_extraction"]}
    unlinked = sorted(set(log["decisions"]) - links.keys())
    assessed = datetime.now(timezone.utc).isoformat()
    log["selection_provenance_records"] = {"assessed_at": assessed, "metadata_sha256": hashlib.sha256(raw).hexdigest(),
        "metadata_records": len(records), "metadata_kept": len(kept), "candidate_links": links, "unlinked_candidate_ids": unlinked}
    log["selection_provenance"] = (
        f"Saved-record reconciliation dated {assessed}: exact DOI, otherwise a unique exact title after case/whitespace normalization, linked saved candidate files to retrieval metadata. "
        f"Of {len(records)} metadata records, {len(records)-len(kept)} were excluded by the recorded metadata rules and {len(kept)} were kept. "
        f"Among the kept records, {len(kept & linked)} link to saved candidates and {len(kept-linked)} have no linked candidate file in this assessment. "
        f"A further {len(linked-kept)} linked metadata records were marked excluded. The {len(linked)} distinct linked metadata records correspond to {len(links)} saved candidate files; "
        f"adding {len(unlinked)} candidate files without a unique recorded match gives the {len(log['decisions'])} candidates assessed below. "
        "Unmatched files are not claimed to originate in this retrieval. This is a dated crosswalk of saved datasets, not reconstructed historical screening. "
        "Extraction-report counts describe a processing batch, not the cumulative saved candidate set. Candidate-level admission and exclusion reasons follow below; the decision log records every match and unmatched identifier."
    )


def finish(log: dict[str, Any], receipts: Any, funnel: dict[str, Any], out_dir: Path, *, excluded_receipt_ids: frozenset[str] = frozenset(), corpus_root: Path | None = None) -> None:
    retain(log, receipts, "doi_retraction_exclusion")
    if log["scope"] == "retained-source reassessment":
        log["selection_assessment"] = json.loads((out_dir / "source_selection_assessment.json").read_text())
        log["reviewer_excluded_source_ids"] = sorted(excluded_receipt_ids)
    if corpus_root is not None:
        reconcile_saved_candidates(log, corpus_root)
    funnel["source_admission"] = log
    atomic_write_json(out_dir / "source_admission.json", log)


def prepare_reassessment(topic: str, lock: Any, out_dir: Path, assess: Any, *, excluded_receipt_ids: frozenset[str] = frozenset()) -> None:
    """Assess saved candidates before switching the runner to the frozen subset."""
    if lock.errors or not lock.source_run:
        return
    prior_path = lock.source_run / "source_admission.json"
    if prior_path.is_file():
        log = json.loads(prior_path.read_text())
    else:
        log = start(topic, frozenset())
        deduplicate(assess(topic, admission_log=log), log, {})
        log["scope"] = "new assessment of saved candidate corpus"
    if lock.receipt_ids & excluded_receipt_ids or not validate(log, [{"receipt_id": rid} for rid in lock.receipt_ids | excluded_receipt_ids]):
        raise ValueError("selection_reassessment_changes_included_set: scientific review required")
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "source_selection_assessment.json", log)
