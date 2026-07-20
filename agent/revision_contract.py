"""Shared structured revision request and deterministic gate contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def feedback(request: Any) -> str:
    if not isinstance(request, dict):
        return ""
    required = request.get("required_revisions")
    if isinstance(required, list) and any(str(item).strip() for item in required):
        return "; ".join(str(item).strip() for item in required if str(item).strip())
    return str(request.get("feedback") or "")


def needs_coverage(request: Any) -> bool:
    return bool(feedback(request).strip()) or not isinstance(request, dict) or request.get("retry_unchanged") is not True


def gate_report(out_dir: Path, coverage: Any, *, refreshed_by: str) -> dict[str, Any] | None:
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
    if not asks or len(coverage.deterministic_known_asks(asks)) != len(asks):
        return None
    manifest = load("manifest.json")
    rows_raw = manifest.get("receipts")
    rows = [row for row in rows_raw if isinstance(row, dict)] if isinstance(rows_raw, list) else []
    unmet = coverage.deterministic_unmet_asks(
        paper.read_text(encoding="utf-8"), asks,
        retained_citations=coverage.retained_citation_labels(manifest, load("citation_registry.json")),
        evidence_rows=rows,
        source_identifier_audit=load("source_identifier_verification.json"),
    )
    return {"passed": not unmet, "ask_count": len(asks), "unmet_asks": unmet, "refreshed_by": refreshed_by}
