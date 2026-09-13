"""Shared structured revision request and deterministic gate contract."""
from __future__ import annotations

import csv
import re
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
    from importlib import import_module

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
            "source_result_excerpts": import_module("scripts.quant_claim_extract").source_result_excerpts(record, require_numeric=False, complete_context=True),
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


def final_source_integrity(paper: str, rows: list[dict[str, Any]]) -> bool:
    """Validate final source accounting independently of reviewer ask wording."""
    from agent.revision_quality import _ordered_rows, _findings_map_is_exact, _findings_map, _table_source_row, manifest_row_finding
    rows = _ordered_rows(rows)
    ids = [row.get("receipt_id") for row in rows]
    valid = all(row.get("effect_direction") in {"positive", "negative", "mixed", "null", "unclear"}
                and row.get("directness") in {"direct", "indirect", "review", "mechanistic", "protocol"}
                and row.get("evidence_tier") in {"A1", "A2", "B1", "B2", "B", "C1", "C2", "C", "D1", "mixed"}
                and re.fullmatch(r"[a-z][a-z0-9_]*", str(row.get("outcome_class") or "")) for row in rows)
    table = [line for line in _findings_map(paper).splitlines() if (cells := _table_cells(line)) and len(cells) == 7 and cells[2].startswith("direction=")]
    for line in table:
        row = _table_source_row(line, rows)
        if row is None or row.get("directness") == "protocol" and _table_cells(line)[6] != f"finding={manifest_row_finding(row)}":
            return False
    return bool(rows) and all(ids) and len(set(ids)) == len(ids) and valid and _findings_map_is_exact(paper, rows)



def _table_cells(line: str) -> list[str]:
    cells = [cell.strip() for cell in next(csv.reader([line.strip()], delimiter="|", escapechar="\\", quoting=csv.QUOTE_NONE))] if line.lstrip().startswith("|") else []
    cells = cells[1:-1] if cells and not cells[-1] else cells[1:]
    return [] if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells) else cells
