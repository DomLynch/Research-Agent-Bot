"""Immutable evidence snapshots for reviewer-driven synthesis revisions."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Collection, Iterable

from agent.evidence_lanes import effective_directness
from agent.synthesis_schemas import ReceiptSummary

SNAPSHOT_DIR = "revision_evidence_snapshot"
_CONTRACT_FIELDS = (
    "topic", "thesis_text", "spar_verdict", "n_claims", "n_failed_traces",
    "population_summary", "canonical_trial_id",
    "evidence_tier", "directness", "source_year", "source_venue",
    "outcome_class", "effect_direction", "p_values", "source_title",
    "source_doi", "source_pmid",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _valid_n_claims(row: dict[str, Any]) -> bool:
    value = row.get("n_claims")
    return "n_claims" not in row or (type(value) is int and value >= 0)


def _valid_claim_count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _contract_rows(
    rows: Iterable[dict[str, Any]], receipt_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    wanted = set(receipt_ids)
    return {
        str(row["receipt_id"]): {
            "receipt_id": str(row["receipt_id"]),
            **{field: row[field] for field in _CONTRACT_FIELDS if field in row},
        }
        for row in rows
        if isinstance(row, dict) and str(row.get("receipt_id") or "") in wanted
    }


@dataclass(frozen=True, slots=True)
class RevisionEvidenceLock:
    source_run: Path | None
    receipt_rows: dict[str, dict[str, Any]]
    quant_dir: Path
    parsed_dir: Path
    citation_registry: Path | None
    mode: str
    errors: tuple[str, ...] = ()

    @property
    def receipt_ids(self) -> frozenset[str]:
        return frozenset(self.receipt_rows)


def load_revision_evidence(
    source_run: Path | None, *, quant_dir: Path, parsed_dir: Path,
    expected_topic: str | None = None,
) -> RevisionEvidenceLock:
    if source_run is None:
        return RevisionEvidenceLock(None, {}, quant_dir, parsed_dir, None, "none")
    source_run = source_run.resolve()
    try:
        manifest = json.loads((source_run / "manifest.json").read_text())
        if not isinstance(manifest, dict):
            raise ValueError("source manifest root is not an object")
        raw_rows = manifest.get("receipts")
        if not isinstance(raw_rows, list) or not raw_rows:
            raise ValueError("source manifest has no receipt list")
        rows: dict[str, dict[str, Any]] = {}
        for row in raw_rows:
            if not isinstance(row, dict) or not row.get("receipt_id"):
                raise ValueError("source manifest has an invalid receipt row")
            if not _valid_n_claims(row):
                raise ValueError("source manifest has invalid n_claims")
            receipt_id = str(row["receipt_id"])
            if receipt_id in rows:
                raise ValueError("source manifest has duplicate receipt IDs")
            rows[receipt_id] = row
    except (OSError, KeyError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return RevisionEvidenceLock(
            source_run, {}, quant_dir, parsed_dir, None, "invalid",
            (f"source_manifest:{type(exc).__name__}",),
        )
    declared_topics = {
        str(value).strip()
        for value in (
            manifest.get("topic"),
            *(row.get("topic") for row in rows.values()),
        )
        if str(value or "").strip()
    }
    source_topic_error = (
        "source_topic_missing"
        if expected_topic is not None and not declared_topics
        else "source_topic_mismatch"
        if expected_topic is not None and declared_topics != {expected_topic.strip()}
        else ""
    )
    snapshot = source_run / SNAPSHOT_DIR
    snapshot_manifest = snapshot / "manifest.json"
    if not snapshot_manifest.is_file():
        snapshot_policy = manifest.get("revision_evidence_snapshot")
        if isinstance(snapshot_policy, dict) and snapshot_policy.get("required") is True:
            return RevisionEvidenceLock(
                source_run, rows, quant_dir, parsed_dir, None, "invalid",
                ("required_snapshot_missing",),
            )
        if source_topic_error:
            return RevisionEvidenceLock(
                source_run, rows, quant_dir, parsed_dir, None, "invalid",
                (source_topic_error,),
            )
        return RevisionEvidenceLock(
            source_run, rows, quant_dir, parsed_dir,
            source_run / "citation_registry.json", "legacy_contract",
        )
    errors: list[str] = []
    if source_topic_error and source_topic_error != "source_topic_missing":
        errors.append(source_topic_error)
    try:
        snapshot_payload = json.loads(snapshot_manifest.read_text())
        records = snapshot_payload.get("receipts", [])
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        snapshot_payload = {}
        records = []
        errors.append(f"snapshot_manifest:{type(exc).__name__}")
    if not isinstance(records, list):
        records = []
        errors.append("snapshot_manifest:invalid_receipts")
    source_contract = snapshot_payload.get("source_contract")
    if (
        not isinstance(source_contract, dict)
        or not isinstance(source_contract.get("topic"), str)
        or not source_contract["topic"].strip()
        or _json_sha256(source_contract) != snapshot_payload.get("source_contract_sha256")
    ):
        errors.append("snapshot_source_contract")
        locked_topic = ""
    else:
        locked_topic = source_contract["topic"].strip()
        manifest_topic = str(manifest.get("topic") or "").strip()
        if manifest_topic and manifest_topic != locked_topic:
            errors.append("source_manifest_topic_drift")
        if expected_topic is not None and expected_topic.strip() != locked_topic:
            errors.append("source_topic_mismatch")
    indexed = {str(row.get("receipt_id") or ""): row for row in records if isinstance(row, dict)}
    if set(indexed) != set(rows):
        errors.append("snapshot_receipt_set_mismatch")
    raw_contracts = snapshot_payload.get("receipt_contracts")
    if (
        not isinstance(raw_contracts, dict)
        or any(not isinstance(row, dict) for row in raw_contracts.values())
    ):
        frozen_rows: dict[str, dict[str, Any]] = {}
        errors.append("snapshot_receipt_contracts")
    else:
        frozen_rows = {str(key): row for key, row in raw_contracts.items()}
        if set(frozen_rows) != set(rows) or any(
            not _valid_n_claims(row) for row in frozen_rows.values()
        ):
            errors.append("snapshot_receipt_contracts")
        if _json_sha256(frozen_rows) != snapshot_payload.get("receipt_contracts_sha256"):
            errors.append("snapshot_receipt_contracts")
        for receipt_id, source_row in rows.items():
            frozen = frozen_rows.get(receipt_id, {})
            source_projection = {
                field: source_row[field] for field in _CONTRACT_FIELDS if field in source_row
            }
            frozen_projection = {
                field: frozen[field] for field in _CONTRACT_FIELDS if field in frozen
            }
            if source_projection != frozen_projection:
                errors.append(f"source_manifest_contract_drift:{receipt_id}")
    for receipt_id in sorted(rows):
        record = indexed.get(receipt_id, {})
        for folder, key in (("quant_claims", "quant_sha256"), ("parsed", "parsed_sha256")):
            suffix = "quant_claims.json" if folder == "quant_claims" else "paper_sections.json"
            path = snapshot / folder / f"{receipt_id}.{suffix}"
            try:
                valid = path.is_file() and _sha256(path) == record.get(key)
            except OSError:
                valid = False
            if not valid:
                errors.append(f"snapshot_{folder}:{receipt_id}")
    citation_registry = snapshot / "citation_registry.json"
    try:
        citation_valid = (
            citation_registry.is_file()
            and _sha256(citation_registry) == snapshot_payload.get("citation_sha256")
        )
    except OSError:
        citation_valid = False
    if not citation_valid:
        errors.append("snapshot_citation_registry")
    return RevisionEvidenceLock(
        source_run, frozen_rows, snapshot / "quant_claims", snapshot / "parsed",
        citation_registry, "snapshot", tuple(errors),
    )


def create_revision_evidence_snapshot(
    out_dir: Path, *, quant_dir: Path, parsed_dir: Path,
    citation_registry: Path, receipt_ids: Iterable[str],
    receipt_contracts: Iterable[dict[str, Any]] | None = None,
    topic: str | None = None,
) -> dict[str, Any]:
    receipt_ids = sorted(set(receipt_ids))
    target = out_dir / SNAPSHOT_DIR
    records: list[dict[str, str]] = []
    errors: list[str] = []
    for receipt_id in receipt_ids:
        quant = quant_dir / f"{receipt_id}.quant_claims.json"
        parsed = parsed_dir / f"{receipt_id}.paper_sections.json"
        if not quant.is_file() or not parsed.is_file():
            errors.append(receipt_id)
            continue
        qdest = target / "quant_claims" / quant.name
        pdest = target / "parsed" / parsed.name
        qdest.parent.mkdir(parents=True, exist_ok=True)
        pdest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(quant, qdest)
        shutil.copy2(parsed, pdest)
        records.append({
            "receipt_id": receipt_id,
            "quant_sha256": _sha256(qdest),
            "parsed_sha256": _sha256(pdest),
        })
    citation_dest = target / "citation_registry.json"
    citation_hash: str | None = None
    if citation_registry.is_file():
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(citation_registry, citation_dest)
        citation_hash = _sha256(citation_dest)
    else:
        errors.append("citation_registry")
    if receipt_contracts is None:
        try:
            source_manifest = json.loads((out_dir / "manifest.json").read_text())
            receipt_contracts = source_manifest.get("receipts", [])
        except (OSError, json.JSONDecodeError, AttributeError):
            receipt_contracts = []
    contracts = _contract_rows(receipt_contracts, receipt_ids)
    if set(contracts) != set(receipt_ids) or any(
        not _valid_n_claims(row) for row in contracts.values()
    ):
        errors.append("receipt_contracts")
    contract_topics = {
        str(row.get("topic") or "").strip()
        for row in contracts.values()
        if str(row.get("topic") or "").strip()
    }
    locked_topic = str(topic or "").strip()
    if not locked_topic and len(contract_topics) == 1:
        locked_topic = next(iter(contract_topics))
    if not locked_topic or contract_topics - {locked_topic}:
        errors.append("source_topic")
    source_contract = {"topic": locked_topic}
    report = {
        "passed": not errors,
        "receipts": records,
        "citation_sha256": citation_hash,
        "receipt_contracts": contracts,
        "receipt_contracts_sha256": _json_sha256(contracts),
        "source_contract": source_contract,
        "source_contract_sha256": _json_sha256(source_contract),
        "missing_files": errors,
    }
    target.mkdir(parents=True, exist_ok=True)
    (target / "manifest.json").write_text(json.dumps(report, indent=2))
    return report


def receipt_contract_mismatches(
    receipts: Iterable[ReceiptSummary], rows: dict[str, dict[str, Any]],
    *, allowed_fields: Collection[str] = (),
) -> list[str]:
    mismatches: list[str] = []
    for receipt in receipts:
        expected = rows.get(receipt.receipt_id)
        if expected is None:
            mismatches.append(f"missing_contract:{receipt.receipt_id}")
            continue
        for field in _CONTRACT_FIELDS:
            if field in allowed_fields:
                continue
            if field not in expected:
                continue
            actual = getattr(receipt, field)
            wanted = expected.get(field)
            if field == "directness":
                actual, wanted = effective_directness(receipt), effective_directness(expected)
            if field == "n_claims" and (
                not _valid_claim_count(wanted) or not _valid_claim_count(actual)
            ):
                mismatches.append(f"{receipt.receipt_id}:{field}")
                continue
            if field == "p_values":
                actual, wanted = list(actual), list(wanted or [])
            if actual != wanted:
                mismatches.append(f"{receipt.receipt_id}:{field}")
    return mismatches
