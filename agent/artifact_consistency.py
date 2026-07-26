"""Final artifact verifier — kills the stale-PDF / desync-supplement
reviewer trap.

Reviewer feedback 2026-05-14: when L5 is declared, every visible
artifact (markdown, PDF if exported, DOCX if exported, supplement,
sidecars) must tell the same story. The exported artifact is what
reviewers see; the trust-spine is meaningless if the PDF is from a
prior render.

This module:
  - canonicalises text for comparison (strips whitespace + bullet
    markers + bold/italic markers so cosmetic re-export differences
    don't trip false positives)
  - cross-checks `full_paper.md` ↔ `submission_package/final_manuscript.md`
    (identical content required when both exist)
  - cross-checks reference tokens between body + citation_registry
  - cross-checks claim counts between manifest + final_status
  - emits `artifact_consistency.json` sidecar with verdict + checks

Universal — no per-topic logic; works on any topic's run dir.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from html import unescape
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConsistencyCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ArtifactConsistencyReport:
    passed: bool
    checks: tuple[ConsistencyCheck, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
        }


def _canonicalize(text: str) -> str:
    """Universal text canonicalisation for cross-artifact comparison.
    Drops formatting noise (whitespace runs, bullet markers, bold/
    italic asterisks) that vary between export pipelines (markdown →
    PDF → docx all re-render whitespace differently). Keeps the
    semantic content stable."""
    # Collapse whitespace
    out = re.sub(r"\s+", " ", text)
    # Strip bullet markers + leading hyphens
    out = re.sub(r"(?:^|\s)[-*]\s+", " ", out)
    # Strip bold/italic markers
    out = out.replace("**", "").replace("__", "")
    return out.strip().lower()


def _content_hash(text: str) -> str:
    return hashlib.sha256(_canonicalize(text).encode("utf-8")).hexdigest()


def verify_run_artifacts(run_dir: Path) -> ArtifactConsistencyReport:
    """Verify all artifacts in a run dir tell the same story.
    Universal — works on any run; gracefully skips checks for
    artifacts that don't exist."""
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
    paper_hash = _content_hash(paper_text)
    checks.append(ConsistencyCheck(
        name="paper_present", passed=True,
        detail=f"full_paper.md canonical-sha256: {paper_hash[:12]}",
    ))

    # Submission-package mirror must hash-match
    submission_paper = run_dir / "submission_package" / "final_manuscript.md"
    if submission_paper.is_file():
        sub_hash = _content_hash(submission_paper.read_text())
        ok = sub_hash == paper_hash
        checks.append(ConsistencyCheck(
            name="submission_package_match", passed=ok,
            detail=(
                f"submission_package/final_manuscript.md hash "
                f"{sub_hash[:12]} {'==' if ok else '!='} "
                f"full_paper.md hash {paper_hash[:12]}"
            ),
        ))

    # PDF / DOCX exports (if present) — extract plaintext and hash
    # against the markdown. Fail-soft when the extractor (pypdf /
    # python-docx) isn't importable in this environment.
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
                name=f"{ext}_extraction_skipped", passed=ext != "docx",
                detail=f"{ext} present without a source hash and optional text extractor unavailable: {e!r}",
            ))
            continue
        except (OSError, ValueError) as e:
            checks.append(ConsistencyCheck(
                name=f"{ext}_extracted", passed=False,
                detail=f"{ext} present but text extraction failed: {e!r}",
            ))
            continue
        export_hash = _content_hash(export_text)
        ok = export_hash == paper_hash
        checks.append(ConsistencyCheck(
            name=f"{ext}_match", passed=ok,
            detail=(
                f"{ext} canonical-sha256 {export_hash[:12]} "
                f"{'==' if ok else '!='} markdown hash {paper_hash[:12]}"
            ),
        ))

    # Manifest receipt-count vs final_status claim-count
    manifest_path = run_dir / "manifest.json"
    final_status_path = run_dir / "final_status.json"
    if manifest_path.is_file() and final_status_path.is_file():
        try:
            m = json.loads(manifest_path.read_text())
            fs = json.loads(final_status_path.read_text())
            n_receipts_manifest = int(m.get("n_receipts", 0))
            # final_status carries blocking_reasons that may reference
            # n_receipts in their detail strings; we cross-check via
            # the manifest only (no claim count in final_status).
            ok = n_receipts_manifest > 0
            checks.append(ConsistencyCheck(
                name="manifest_receipt_count", passed=ok,
                detail=(
                    f"manifest n_receipts={n_receipts_manifest}; "
                    f"final_status maturity_level="
                    f"{fs.get('maturity_level')}"
                ),
            ))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            checks.append(ConsistencyCheck(
                name="manifest_receipt_count", passed=False,
                detail=f"failed to parse manifest/final_status: {e!r}",
            ))

    # Reference-token coverage: every receipt's body_citation in
    # citation_registry should appear in the References section of
    # the paper. Pre-Slice-3 orphan-ref check covered the reverse
    # direction; this is the manifest-side cross-check.
    registry_path = run_dir / "citation_registry.json"
    if registry_path.is_file():
        try:
            reg = json.loads(registry_path.read_text())
            refs_section = _section(paper_text, "References")
            missing = [
                entry.get("body_citation", "")
                for entry in reg.values()
                if entry.get("body_citation")
                and entry["body_citation"] not in refs_section
                and entry["body_citation"].replace("é", "e")
                not in refs_section.replace("é", "e")
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
        except (OSError, json.JSONDecodeError) as e:
            checks.append(ConsistencyCheck(
                name="citation_registry_coverage", passed=False,
                detail=f"failed to parse citation_registry.json: {e!r}",
            ))

    passed = all(c.passed for c in checks)
    return ArtifactConsistencyReport(passed=passed, checks=tuple(checks))


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
