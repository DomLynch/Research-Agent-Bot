"""Verify that all rendered and sidecar artifacts describe one run."""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from html import unescape
from pathlib import Path

_TRUST_INPUT_FILES = ("full_paper.md", "manifest.json", "citation_registry.json",
                      "full_paper.review_patches.json")
_OPTIONAL_TRUST_INPUT_FILES = ("debug/full_paper.review_patch_log.json",)
_REQUIRED_CHECKS = {"paper_present", "manifest_receipt_count", "citation_registry_coverage",
                    "manifest_registry_identity", "reviewer_evidence", "source_proof_integrity"}
_SOURCE_ID_FIELDS = ("source_doi", "source_pmid", "source_pmcid", "source_openalex_id", "registry_id")


@dataclass(frozen=True, slots=True)
class ConsistencyCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ArtifactConsistencyReport:
    passed: bool
    checks: tuple[ConsistencyCheck, ...]
    paper_sha256: str = ""
    inputs_sha256: str = ""

    def to_json(self) -> dict[str, object]:
        return {"passed": self.passed, "paper_sha256": self.paper_sha256,
                "inputs_sha256": self.inputs_sha256, "checks": [asdict(c) for c in self.checks]}


def _canonicalize(text: str) -> str:
    """Remove formatting noise before comparing rendered artifacts."""
    # Collapse whitespace
    out = re.sub(r"\s+", " ", text)
    # Strip bullet markers + leading hyphens
    out = re.sub(r"(?:^|\s)[-*]\s+", " ", out)
    # Strip bold/italic markers
    out = out.replace("**", "").replace("__", "")
    return out.strip().lower()


def _rendered_content_hash(text: str) -> str:
    return hashlib.sha256(_canonicalize(text).encode("utf-8")).hexdigest()


def paper_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def trust_inputs_hash(run_dir: Path) -> str:
    """Bind the exact manuscript, evidence, and reviewer snapshot."""
    digest = hashlib.sha256()
    try:
        for name in _TRUST_INPUT_FILES:
            path = run_dir / name
            if not path.is_file():
                return ""
            digest.update(name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
        for name in _OPTIONAL_TRUST_INPUT_FILES:
            path = run_dir / name
            if path.is_file():
                digest.update(name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    except OSError:
        return ""
    return digest.hexdigest()


def consistency_receipt_matches(run_dir: Path, stored: object) -> bool:
    """Require the stored receipt to equal a fresh authoritative report."""
    return isinstance(stored, dict) and stored == verify_run_artifacts(run_dir).to_json()


def consistency_checks_pass(checks: object) -> bool:
    return isinstance(checks, list) and _REQUIRED_CHECKS <= {
        str(row.get("name") or "") for row in checks
        if isinstance(row, dict) and row.get("passed") is True
    } and all(isinstance(row, dict) and row.get("passed") is True for row in checks)


def _source_identity(row: object) -> tuple[str, ...]:
    if not isinstance(row, dict):
        return ()
    return tuple(str(row.get(field) or "").strip().casefold() for field in _SOURCE_ID_FIELDS) + (str(row.get("source_title") or row.get("title") or "").strip().casefold(),)


def _manifest_source_matches_registry(manifest_row: object, registry_row: object) -> bool:
    manifest_identity = _source_identity(manifest_row)
    registry_identity = _source_identity(registry_row)
    return all(not value or not registry_identity[index] or value == registry_identity[index]
               for index, value in enumerate(manifest_identity))


def _snapshot_registry_matches(run_dir: Path, registry: dict[str, object]) -> bool:
    path = run_dir / "revision_evidence_snapshot" / "citation_registry.json"
    if not path.is_file():
        return True
    try:
        snapshot = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(snapshot, dict) and set(snapshot) == set(registry) and all(
        isinstance(registry[key], dict) and isinstance(snapshot[key], dict)
        and _source_identity(registry[key]) == _source_identity(snapshot[key])
        for key in registry
    )


def verify_run_artifacts(run_dir: Path) -> ArtifactConsistencyReport:
    """Verify all artifacts in a run dir tell the same story.
    Universal — required trust artifacts fail closed when absent."""
    checks: list[ConsistencyCheck] = []

    paper_path = run_dir / "full_paper.md"
    if not paper_path.is_file():
        return ArtifactConsistencyReport(
            passed=False,
            checks=(ConsistencyCheck(
                name="paper_present", passed=False,
                detail="full_paper.md missing in run dir",
            ),),
        )
    paper_text = paper_path.read_text()
    paper_hash = _rendered_content_hash(paper_text)
    paper_sha256 = paper_content_hash(paper_text)
    checks.append(ConsistencyCheck(
        name="paper_present", passed=True,
        detail=f"full_paper.md canonical-sha256: {paper_hash[:12]}",
    ))

    # PDF / DOCX exports (if present) — extract plaintext and hash
    # against the markdown. A present export that cannot be inspected fails.
    for ext, exporter in (("pdf", _extract_pdf_text),
                          ("docx", _extract_docx_text)):
        export_path = paper_path.with_suffix(f".{ext}")
        if not export_path.is_file():
            continue
        if ext == "docx" and (source_hash := _docx_source_hash(export_path)):
            expected = hashlib.sha256(paper_text.encode("utf-8")).hexdigest()
            missing = _docx_missing_lines(export_path, paper_text)
            ok = source_hash == expected and not missing
            checks.append(ConsistencyCheck(
                name="docx_source_match", passed=ok,
                detail=(
                    f"docx source-sha256 {source_hash[:12]} "
                    f"{'==' if source_hash == expected else '!='} markdown source {expected[:12]}; "
                    f"missing visible lines={len(missing)}"
                ),
            ))
            continue
        try:
            export_text = exporter(export_path)
        except ImportError as e:
            checks.append(ConsistencyCheck(
                name=f"{ext}_extracted", passed=False,
                detail=f"{ext} present but text extractor unavailable: {e!r}",
            ))
            continue
        except (OSError, ValueError) as e:
            checks.append(ConsistencyCheck(
                name=f"{ext}_extracted", passed=False,
                detail=f"{ext} present but text extraction failed: {e!r}",
            ))
            continue
        export_hash = _rendered_content_hash(export_text)
        ok = export_hash == paper_hash
        checks.append(ConsistencyCheck(
            name=f"{ext}_match", passed=ok,
            detail=(
                f"{ext} canonical-sha256 {export_hash[:12]} "
                f"{'==' if ok else '!='} markdown hash {paper_hash[:12]}"
            ),
        ))

    # Manifest receipt count. Do not read final_status here: final status
    # consumes this consistency receipt, so doing so creates a trust cycle.
    manifest_path = run_dir / "manifest.json"
    manifest: dict[str, object] = {}
    manifest_receipt_ids: tuple[str, ...] | None = None
    manifest_receipts: dict[str, dict[str, object]] = {}
    if manifest_path.is_file():
        try:
            value = json.loads(manifest_path.read_text())
            if not isinstance(value, dict):
                raise ValueError("manifest must be an object")
            manifest = value
            n_receipts_manifest = int(str(manifest.get("n_receipts", 0)))
            receipt_rows = manifest.get("receipts")
            receipt_ids = tuple(
                str(row.get("receipt_id") or "").strip()
                for row in receipt_rows if isinstance(row, dict)
            ) if isinstance(receipt_rows, list) else ()
            ids_ok = (
                isinstance(receipt_rows, list)
                and len(receipt_ids) == len(receipt_rows)
                and all(receipt_ids)
                and len(set(receipt_ids)) == len(receipt_ids)
                and all(
                    isinstance(row.get("receipt_id"), str)
                    and row["receipt_id"] == row["receipt_id"].strip()
                    for row in receipt_rows if isinstance(row, dict)
                )
            )
            manifest_receipt_ids = receipt_ids if ids_ok else None
            manifest_receipts = {
                str(row["receipt_id"]): row for row in receipt_rows
                if isinstance(row, dict) and isinstance(row.get("receipt_id"), str)
            } if ids_ok and isinstance(receipt_rows, list) else {}
            ok = (isinstance(receipt_rows, list) and n_receipts_manifest > 0
                  and n_receipts_manifest == len(receipt_rows)
                  and all(isinstance(row, dict) for row in receipt_rows)
                  and ids_ok)
            checks.append(ConsistencyCheck(
                name="manifest_receipt_count", passed=ok,
                detail=f"manifest n_receipts={n_receipts_manifest}; receipt rows="
                       f"{len(receipt_rows) if isinstance(receipt_rows, list) else 'missing'}",
            ))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            checks.append(ConsistencyCheck(
                name="manifest_receipt_count", passed=False,
                detail=f"failed to parse manifest: {e!r}",
            ))
    else:
        checks.append(ConsistencyCheck("manifest_receipt_count", False, "manifest.json missing"))

    checks.append(_reviewer_evidence_check(run_dir))
    checks.append(_source_proof_integrity_check(run_dir, manifest))

    # Reference-token coverage: every receipt's body_citation in
    # citation_registry should appear in the References section of
    # the paper. Pre-Slice-3 orphan-ref check covered the reverse
    # direction; this is the manifest-side cross-check.
    registry_path = run_dir / "citation_registry.json"
    if registry_path.is_file():
        try:
            reg = json.loads(registry_path.read_text())
            if not isinstance(reg, dict) or not reg:
                raise ValueError("citation registry must be a non-empty object")
            if any(not isinstance(entry, dict) for entry in reg.values()):
                raise ValueError("citation registry entries must be objects")
            registry_ids = set(reg)
            embedded_ids_match = all(
                isinstance(entry.get("receipt_id"), str)
                and entry["receipt_id"] == receipt_id
                for receipt_id, entry in reg.items()
            )
            identity_ok = (
                manifest_receipt_ids is not None
                and all(receipt_id and receipt_id == receipt_id.strip() for receipt_id in registry_ids)
                and registry_ids == set(manifest_receipt_ids)
                and embedded_ids_match
                and all(_manifest_source_matches_registry(manifest_receipts[receipt_id], reg[receipt_id])
                        for receipt_id in registry_ids)
                and _snapshot_registry_matches(run_dir, reg)
            )
            checks.append(ConsistencyCheck(
                name="manifest_registry_identity", passed=identity_ok,
                detail=(
                    f"manifest receipts={len(manifest_receipt_ids or ())}; "
                    f"registry receipts={len(registry_ids)}"
                ),
            ))
            refs_section = _section(paper_text, "References")
            missing = [
                token or f"{receipt_id}:missing_body_citation"
                for receipt_id, entry in reg.items()
                if not (token := str(entry.get("body_citation") or "").strip())
                or (token not in refs_section
                    and token.replace("é", "e") not in refs_section.replace("é", "e"))
            ]
            ok = not missing
            checks.append(ConsistencyCheck(
                name="citation_registry_coverage",
                passed=ok,
                detail=(
                    f"all {len(reg)} registry entries appear in body "
                    f"References" if ok else
                    f"{len(missing)} registry entries missing from "
                    f"body References (first 3: {missing[:3]})"
                ),
            ))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            checks.append(ConsistencyCheck(
                "manifest_registry_identity", False,
                f"failed to reconcile citation_registry.json: {e!r}"))
            checks.append(ConsistencyCheck(
                name="citation_registry_coverage", passed=False,
                detail=f"failed to parse citation_registry.json: {e!r}",
            ))
    else:
        checks.append(ConsistencyCheck(
            "manifest_registry_identity", False, "citation_registry.json missing"))
        checks.append(ConsistencyCheck(
            name="citation_registry_coverage", passed=False,
            detail="citation_registry.json missing",
        ))

    passed = all(c.passed for c in checks)
    return ArtifactConsistencyReport(passed, tuple(checks), paper_sha256,
                                     trust_inputs_hash(run_dir))


def _reviewer_evidence_check(run_dir: Path) -> ConsistencyCheck:
    receipt_path = run_dir / "full_paper.review_patches.json"
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return ConsistencyCheck("reviewer_evidence", False, f"review receipt unreadable: {exc!r}")
    patches = receipt.get("patches") if isinstance(receipt, dict) else None
    if not isinstance(patches, list) or receipt.get("review_available") is not True:
        return ConsistencyCheck("reviewer_evidence", False, "review receipt unavailable or malformed")
    expected = {str(row.get("id") or "").strip() for row in patches
                if isinstance(row, dict) and str(row.get("id") or "").strip()}
    if len(expected) != len(patches):
        return ConsistencyCheck("reviewer_evidence", False, "review patch ids missing or duplicated")
    log_path = run_dir / "debug" / "full_paper.review_patch_log.json"
    if not patches and not log_path.is_file():
        return ConsistencyCheck("reviewer_evidence", True, "review completed with zero patches")
    try:
        log = json.loads(log_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return ConsistencyCheck("reviewer_evidence", False, f"review log unreadable: {exc!r}")
    rows = log.get("patches") if isinstance(log, dict) else None
    if not isinstance(rows, list):
        return ConsistencyCheck("reviewer_evidence", False, "review log malformed")
    logged = {str(row.get("patch_id") or "").strip() for row in rows
              if isinstance(row, dict) and str(row.get("patch_id") or "").strip()}
    severity = {
        str(row.get("id") or "").strip(): str(row.get("severity") or "").strip().upper()
        for row in patches if isinstance(row, dict)
    }
    valid_decisions = {"applied", "applied_via_repair", "auto_stripped", "flagged", "rejected"}
    decisions_valid = set(severity.values()) <= {"P1", "P2", "P3"} and all(
                          isinstance(row, dict) and row.get("decision") in valid_decisions
                          and str(row.get("severity") or "").strip().upper()
                          == severity.get(str(row.get("patch_id") or "").strip())
                          and (row.get("decision") not in {"flagged", "rejected"}
                               or severity.get(str(row.get("patch_id") or "").strip()) not in {"P1", "HIGH", "CRITICAL"})
                          for row in rows)
    ok = decisions_valid and logged == expected and len(logged) == len(rows)
    return ConsistencyCheck("reviewer_evidence", ok, f"review patch decisions {len(logged)}/{len(expected)}")


def _source_proof_integrity_check(run_dir: Path, manifest: dict[str, object]) -> ConsistencyCheck:
    from agent.publication_evidence import source_proof_matches_record

    receipts = manifest.get("receipts")
    if not isinstance(receipts, list):
        return ConsistencyCheck("source_proof_integrity", False, "manifest receipts missing")
    claimed = [
        row for row in receipts
        if isinstance(row, dict) and any(str(row.get(key) or "").strip() for key in (
            "source_record_locator", "source_record_hash", "source_content_hash",
        ))
    ]
    required_ids: set[str] = set()
    for row in receipts:
        if not isinstance(row, dict):
            continue
        n_claims = row.get("n_claims")
        if type(n_claims) is not int:
            return ConsistencyCheck("source_proof_integrity", False, "manifest n_claims malformed")
        if n_claims < 0:
            return ConsistencyCheck("source_proof_integrity", False, "manifest n_claims negative")
        has_claims = n_claims > 0
        if (
            has_claims
            and str(row.get("directness") or "").lower() == "direct"
            and str(row.get("evidence_tier") or "").upper().startswith("A")
        ):
            required_ids.add(str(row.get("receipt_id") or row.get("id") or "").strip())
    claimed_ids = {
        str(row.get("receipt_id") or row.get("id") or "").strip()
        for row in claimed
    }
    valid = 0
    for row in claimed:
        receipt_id = str(row.get("receipt_id") or row.get("id") or "").strip()
        source_path = run_dir / "revision_evidence_snapshot" / "parsed" / f"{receipt_id}.paper_sections.json"
        valid += int(source_proof_matches_record(row, source_path))
    ok = valid == len(claimed) and required_ids <= claimed_ids
    return ConsistencyCheck(
        "source_proof_integrity", ok,
        f"source proofs verified {valid}/{len(claimed)}; "
        f"required direct proofs {len(required_ids & claimed_ids)}/{len(required_ids)}",
    )


def write_consistency_sidecar(
    run_dir: Path, report: ArtifactConsistencyReport,
) -> Path:
    """Serialise to `artifact_consistency.json`. Universal."""
    path = run_dir / "artifact_consistency.json"
    path.write_text(json.dumps(report.to_json(), indent=2))
    return path


def _section(paper_md: str, heading: str) -> str:
    """Universal section extractor — same semantics as
    `agent.journal_surface_gate._section_body` but inlined to avoid
    a cross-module import cycle. Returns body of `## <heading>`."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\b(.*?)(?=^##\s+|\Z)",
        re.M | re.S,
    )
    m = pattern.search(paper_md)
    return m.group(1) if m else ""


def _extract_pdf_text(path: Path) -> str:
    """Fail-soft PDF text extraction. Tries pypdf if available;
    otherwise raises ImportError (caller catches)."""
    from pypdf import PdfReader  # type: ignore[import-not-found]
    reader = PdfReader(str(path))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def _extract_docx_text(path: Path) -> str:
    """Fail-soft DOCX text extraction. Tries python-docx if
    available; otherwise raises ImportError."""
    from docx import Document  # type: ignore[import-not-found]
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _docx_source_hash(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.read("researka/source.sha256").decode("ascii").strip()
    except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile):
        return ""


def _docx_missing_lines(path: Path, paper: str) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
    except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile):
        return ["word/document.xml"]
    visible = _canonicalize(unescape(re.sub(r"<[^>]+>", " ", xml)).replace("|", " "))
    missing = []
    for raw in paper.splitlines():
        line = raw.strip()
        if not line or set(line) <= set("|-: "):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line).replace("|", " ")
        normalized = _canonicalize(line)
        if normalized and normalized not in visible:
            missing.append(normalized)
    return missing


def refresh_public_exports(run_dir: Path) -> bool:
    paper_path = run_dir / "full_paper.md"
    if not paper_path.is_file():
        return False
    paper = paper_path.read_text(encoding="utf-8")
    source_hash = hashlib.sha256(paper.encode("utf-8")).hexdigest()
    typ_path = run_dir / "full_paper.typ"
    if (
        _docx_source_hash(run_dir / "full_paper.docx") == source_hash
        and typ_path.is_file()
        and typ_path.read_text(encoding="utf-8").startswith(f"// source-sha256: {source_hash}\n")
    ):
        return False
    polish = importlib.import_module("scripts.v3_polish_compiler")
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    typ_path = polish.write_typst_source(run_dir, paper, manifest)
    pdf_path = run_dir / "full_paper.pdf"
    if pdf_path.is_file() and polish._run_typst(typ_path, pdf_path).get("status") != "passed":
        pdf_path.unlink()
    importlib.import_module("scripts.v3_paper_ir").compile_run(run_dir)
    return True
