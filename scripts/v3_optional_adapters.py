"""Optional v3 polish/ingestion adapters with no mandatory dependencies."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any


def _write_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _sections_from_markdown(markdown: str) -> dict[str, str]:
    sections = {k: "" for k in ("abstract", "introduction", "methods", "results", "discussion", "limitations", "conclusion", "references")}
    current = "abstract"
    buf: list[str] = []
    for line in markdown.splitlines():
        m = re.match(r"^#{1,3}\s+(.+)$", line.strip())
        if m:
            if buf and not sections[current]:
                sections[current] = "\n".join(buf).strip()
            label = m.group(1).lower()
            current = next((k for k in sections if k in label), current)
            buf = []
            continue
        buf.append(line)
    if buf and not sections[current]:
        sections[current] = "\n".join(buf).strip()
    if not sections["abstract"]:
        sections["abstract"] = markdown[:4000].strip()
    return sections


def write_docling_paper_sections(
    *,
    source_uri: str,
    parsed_dir: Path,
    paper_id: str,
    metadata: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Use Docling as fallback ingestion when primary JATS/PDF paths fail."""
    if not source_uri:
        return {"status": "skipped", "reason": "no_source_uri"}
    if not (source_uri.startswith(("http://", "https://")) or Path(source_uri).exists()):
        return {"status": "skipped", "reason": "source_missing"}
    if not _module_available("docling.document_converter"):
        return {"status": "skipped", "reason": "docling_not_installed"}
    try:
        from docling.document_converter import DocumentConverter  # type: ignore[import-not-found]

        document = DocumentConverter().convert(source_uri).document
        markdown = document.export_to_markdown() if hasattr(document, "export_to_markdown") else str(document)
        raw = document.export_to_dict() if hasattr(document, "export_to_dict") else {"markdown": markdown}
    except Exception as exc:
        return {"status": "failed", "reason": type(exc).__name__, "detail": str(exc)[:500]}
    if not markdown.strip():
        return {"status": "failed", "reason": "empty_docling_markdown"}
    parsed_dir.mkdir(parents=True, exist_ok=True)
    (parsed_dir / f"{paper_id}.docling_document.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    doc = {
        "paper_id": paper_id,
        "source_pdf": source_uri,
        "title": metadata.get("title", ""),
        "authors": metadata.get("authors", []),
        "year": metadata.get("year"),
        "journal": metadata.get("journal", ""),
        "doi": metadata.get("doi", ""),
        "pmid": metadata.get("pmid", ""),
        "trial_ids": sorted(set(re.findall(r"\bNCT\d{8}\b", markdown))),
        "sections": _sections_from_markdown(markdown),
        "tables": [],
        "figures": [],
        "extraction_quality": {
            "section_coverage": [k for k, v in _sections_from_markdown(markdown).items() if v],
            "table_count": 0,
            "figure_count": 0,
            "reference_count": 0,
            "warnings": [f"docling-fallback:{reason}"],
        },
    }
    (parsed_dir / f"{paper_id}.paper_sections.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return {"status": "passed", "paper_id": paper_id, "sections": len(doc["extraction_quality"]["section_coverage"])}


def normalize_biomed_terms(text: str, cache_path: Path | None = None) -> dict[str, Any]:
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if cache_path and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("cache_key") == key:
            return cached
    model_name = "en_core_sci_sm"
    try:
        import spacy  # type: ignore[import-not-found]

        nlp = spacy.load(model_name)
        terms = [{"text": ent.text, "label": ent.label_} for ent in nlp(text[:20000]).ents[:200]]
        payload = {"status": "passed", "adapter": "scispacy", "model": model_name, "cache_key": key, "terms": terms}
    except Exception as exc:
        tokens = sorted(set(re.findall(r"\b[A-Za-z][A-Za-z0-9-]{3,}\b", text)))[:200]
        payload = {
            "status": "fallback",
            "adapter": "regex",
            "reason": type(exc).__name__,
            "cache_key": key,
            "terms": [{"text": t, "label": "TERM"} for t in tokens],
        }
    if cache_path:
        _write_json(cache_path, payload)
    return payload


def validate_structured_output(payload: dict[str, Any], schema: dict[str, str], out_path: Path | None = None) -> dict[str, Any]:
    type_map = {"bool": bool, "dict": dict, "list": list, "str": str, "int": int}
    errors: list[str] = []
    for key, type_name in schema.items():
        expected = type_map[type_name]
        if key not in payload:
            errors.append(f"missing:{key}")
        elif not isinstance(payload[key], expected):
            errors.append(f"type:{key}:expected_{type_name}")
    result = {
        "status": "passed" if not errors else "failed",
        "adapter": "stdlib_schema",
        "outlines_available": _module_available("outlines"),
        "errors": errors,
    }
    return _write_json(out_path, result) if out_path else result


def run_offline_eval_harness(run_dir: Path, report: dict[str, Any], out_path: Path | None = None) -> dict[str, Any]:
    gates = report.get("gates", {}) if isinstance(report.get("gates"), dict) else {}
    checks = {
        "polish_report_schema": isinstance(report.get("passed"), bool) and isinstance(gates, dict),
        "raw_pipe_tables_not_hard_failed_when_advisory": gates.get("raw_pipe_tables", {}).get("status") != "failed",
        "falsifier_gate_present": "falsifier_or_next_study" in gates,
        "paper_exists": (run_dir / "full_paper.md").is_file(),
    }
    result = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "optional_eval_tools": {
            name: _module_available(name)
            for name in ("deepeval", "dspy", "textgrad")
        },
    }
    return _write_json(out_path, result) if out_path else result
