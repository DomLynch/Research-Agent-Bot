"""Shared structured revision request and deterministic gate contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable


def ask_fingerprint(asks: list[str]) -> str:
    return hashlib.sha256(json.dumps(asks, separators=(",", ":")).encode()).hexdigest()


def feedback(request: Any) -> str:
    if not isinstance(request, dict):
        return ""
    required = request.get("required_revisions")
    if isinstance(required, list) and any(str(item).strip() for item in required):
        return "; ".join(str(item).strip() for item in required if str(item).strip())
    return str(request.get("feedback") or "")


def needs_coverage(request: Any) -> bool:
    return bool(feedback(request).strip()) or not isinstance(request, dict) or request.get("retry_unchanged") is not True


def gate_report(out_dir: Path, coverage: Any, *, refreshed_by: str, payload_satisfied: Callable[[str], bool] | None = None) -> dict[str, Any] | None:
    def load(name: str) -> dict[str, Any]:
        try:
            value = json.loads((out_dir / name).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    request = load("researka_revision_request.json")
    paper = out_dir / "full_paper.md"
    revision_feedback = feedback(request).strip()
    if not revision_feedback or not paper.is_file():
        return None
    required = request.get("required_revisions")
    asks = coverage.revision_asks(revision_feedback, required if isinstance(required, list) else None)
    manifest = load("manifest.json")
    rows_raw = manifest.get("receipts")
    rows = [row for row in rows_raw if isinstance(row, dict)] if isinstance(rows_raw, list) else []
    known = coverage.deterministic_known_asks(asks, evidence_rows=rows)
    known_set = set(known) | {ask for ask in asks if payload_satisfied and payload_satisfied(ask)}
    if not asks or not known_set:
        return None
    unknown = [ask for ask in asks if ask not in known_set]
    previous = load("revision_coverage_gate.json")
    previous_unmet = previous.get("unmet_asks")
    fingerprint = ask_fingerprint(asks)
    request_path = out_dir / "researka_revision_request.json"
    gate_path = out_dir / "revision_coverage_gate.json"
    legacy_current = (
        not previous.get("ask_fingerprint")
        and gate_path.is_file()
        and gate_path.stat().st_mtime_ns >= request_path.stat().st_mtime_ns
    )
    if unknown and (
        previous.get("ask_count") != len(asks)
        or not isinstance(previous_unmet, list)
        or (previous.get("ask_fingerprint") != fingerprint and not legacy_current)
    ):
        return None
    unmet = coverage.deterministic_unmet_asks(
        paper.read_text(encoding="utf-8"), known,
        retained_citations=coverage.retained_citation_labels(manifest, load("citation_registry.json")),
        evidence_rows=rows,
        source_identifier_audit=load("source_identifier_verification.json"),
    )
    prior_unmet = {str(ask) for ask in previous_unmet or ()}
    unmet.extend(ask for ask in unknown if ask in prior_unmet)
    report = {
        "passed": not unmet, "ask_count": len(asks), "unmet_asks": unmet,
        "refreshed_by": refreshed_by,
    }
    if unknown:
        report["ask_fingerprint"] = fingerprint
    return report
