"""Shared structured revision request and deterministic gate contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def ask_fingerprint(asks: list[str]) -> str:
    return hashlib.sha256(json.dumps(asks, separators=(",", ":")).encode()).hexdigest()


def context_fingerprint(asks: list[str], paper: str, rows: list[dict[str, Any]], payload: dict[str, Any] | None) -> str:
    return hashlib.sha256(json.dumps([asks, paper, rows, payload], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def feedback(request: Any) -> str:
    if not isinstance(request, dict):
        return ""
    required = request.get("required_revisions")
    if isinstance(required, list) and any(str(item).strip() for item in required):
        return "; ".join(str(item).strip() for item in required if str(item).strip())
    return str(request.get("feedback") or "")


def needs_coverage(request: Any) -> bool:
    return bool(feedback(request).strip()) or not isinstance(request, dict) or request.get("retry_unchanged") is not True


def evidence_rows(out_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Review frozen source text and tables without rewriting receipt contracts."""
    from agent.revision_evidence import load_revision_evidence

    raw = manifest.get("receipts")
    rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    if not rows:
        return rows
    snapshot = out_dir / "revision_evidence_snapshot"
    if not snapshot.exists() and not manifest.get("revision_evidence_snapshot"):
        return rows
    lock = load_revision_evidence(out_dir, quant_dir=snapshot / "quant_claims", parsed_dir=snapshot / "parsed")
    if lock.errors:
        raise ValueError("revision_evidence_unverified:" + ",".join(lock.errors))
    if lock.mode != "snapshot":
        return rows
    reviewed = []
    for row in rows:
        record = json.loads((lock.parsed_dir / f"{row['receipt_id']}.paper_sections.json").read_text())
        abstract = record.get("sections", {}).get("abstract")
        reviewed.append({
            **row, "verified_source_sections": record.get("sections", {}),
            "verified_source_tables": record.get("tables", []),
            **({"verified_abstract": abstract} if isinstance(abstract, str) and abstract.strip() else {}),
        })
    return reviewed


def gate_report(out_dir: Path, coverage: Any, *, refreshed_by: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
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
    rows = evidence_rows(out_dir, manifest)
    text = paper.read_text(encoding="utf-8")
    previous = load("revision_coverage_gate.json")
    previous_unmet = previous.get("unmet_asks")
    fingerprint = ask_fingerprint(asks)
    context = context_fingerprint(asks, text, rows, payload)
    if (
        not asks or previous.get("ask_count") != len(asks)
        or not isinstance(previous_unmet, list)
        or previous.get("passed") is not (not previous_unmet)
        or any(ask not in asks for ask in previous_unmet)
        or previous.get("ask_fingerprint") != fingerprint
        or previous.get("context_fingerprint") != context
    ):
        return None
    unmet = coverage.deterministic_unmet_asks(
        text, asks,
        retained_citations=coverage.retained_citation_labels(manifest, load("citation_registry.json")),
        evidence_rows=rows,
        source_identifier_audit=load("source_identifier_verification.json"),
    )
    prior_unmet = {str(ask) for ask in previous_unmet or ()}
    unmet = [ask for ask in asks if ask in unmet or ask in prior_unmet]
    return {
        "passed": not unmet, "ask_count": len(asks), "unmet_asks": unmet,
        "refreshed_by": refreshed_by, "ask_fingerprint": fingerprint, "context_fingerprint": context,
    }
