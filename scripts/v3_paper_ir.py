"""v3 PaperIR and public export sidecars.

Small deterministic compiler layer over an existing synthesis run. It does not
rewrite science; it gives the renderer/export stack a typed source of truth and
keeps public artifacts separate from audit/provenance sidecars.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import tomllib
import zipfile
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class PaperThesis:
    claim: str
    framework_name: str
    axes: list[str]
    falsifier: str
    support_claim_ids: list[str]
    contradiction_ids: list[str]


@dataclass(frozen=True, slots=True)
class SectionIR:
    heading: str
    level: int
    word_count: int


@dataclass(frozen=True, slots=True)
class TableIR:
    name: str
    location: str
    row_count: int


@dataclass(frozen=True, slots=True)
class PaperIR:
    schema: str
    title: str
    topic: str
    thesis: PaperThesis
    sections: list[SectionIR]
    tables: list[TableIR]
    references: list[str]
    exports: dict[str, str | None]


@dataclass(frozen=True, slots=True)
class DomainFramework:
    name: str
    class_terms: tuple[str, ...]
    axes: tuple[str, ...]
    falsifier: str


DOMAIN_FRAMEWORKS: tuple[DomainFramework, ...] = (
    DomainFramework(
        "Microbiome Context Framework",
        ("microbiome", "probiotic", "gut"),
        ("Outcome", "Host state", "Preparation", "Dose", "Strain", "Model"),
        "a direct human trial showing the same effect across host states, preparations, doses, and strains",
    ),
    DomainFramework(
        "Metabolic-Functional Tradeoff Framework",
        ("exercise", "nutrition", "metabolic", "muscle"),
        ("Metabolic signal", "Functional endpoint", "Dose", "Timing", "Population"),
        "a direct trial where metabolic markers and functional endpoints move together",
    ),
    DomainFramework(
        "Dose-Response Safety Framework",
        ("oncology", "drug", "therapy", "hormone"),
        ("Dose", "Exposure duration", "Responder state", "Benefit", "Safety"),
        "a dose-stratified trial showing benefit without safety tradeoff across exposure levels",
    ),
    DomainFramework(
        "Endpoint-Sensitivity Framework",
        ("geroscience", "aging", "longevity", "biomarker"),
        ("Mechanism", "Intermediate biomarker", "Function", "Clinical outcome"),
        "a direct clinical study aligning mechanism, biomarker, function, and clinical outcome",
    ),
)


def compile_run(run_dir: Path) -> dict[str, Any]:
    paper = (run_dir / "full_paper.md").read_text(encoding="utf-8")
    manifest = _read_json(run_dir / "manifest.json")
    manifest = manifest if isinstance(manifest, dict) else {}
    topic = str(manifest.get("topic") or _topic_from_run(run_dir))
    receipts = [r for r in manifest.get("receipts", []) if isinstance(r, dict)]
    tensions = _load_tensions(run_dir)
    framework = select_domain_framework(topic, _topic_class(topic), receipts, _topic_framework(topic))
    thesis = _build_thesis(paper, topic, framework, receipts, tensions)
    exports = _write_exports(run_dir, paper, manifest, receipts, tensions)
    ir = PaperIR(
        schema="researka.paper_ir.v1",
        title=_title(paper, topic),
        topic=topic,
        thesis=thesis,
        sections=_sections(paper),
        tables=_tables(run_dir),
        references=_references(paper),
        exports=exports,
    )
    (run_dir / "paper_ir.json").write_text(json.dumps(asdict(ir), indent=2) + "\n", encoding="utf-8")
    score = _quality_score(ir, paper, receipts, tensions)
    (run_dir / "paper_quality_score.json").write_text(json.dumps(score, indent=2) + "\n", encoding="utf-8")
    manifest_payload = _export_manifest(run_dir, ir, score)
    (run_dir / "public_export_manifest.json").write_text(json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8")
    return {"paper_ir": asdict(ir), "quality_score": score, "export_manifest": manifest_payload}


def select_domain_framework(
    topic: str, topic_class: str, receipts: list[dict[str, Any]],
    configured: DomainFramework | None = None,
) -> DomainFramework:
    if configured:
        return configured
    haystack = " ".join(
        [topic, topic_class]
        + [str(r.get("outcome_class") or "") for r in receipts[:40]]
    ).lower()
    for framework in DOMAIN_FRAMEWORKS:
        if any(term in haystack for term in framework.class_terms):
            return framework
    return DOMAIN_FRAMEWORKS[-1]


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _topic_from_run(run_dir: Path) -> str:
    name = run_dir.name.removeprefix("synthesis-")
    return name.split("-v", 1)[0] if "-v" in name else name


def _topic_class(topic: str) -> str:
    data = _topic_pack(topic)
    return str(data.get("class_") or data.get("class") or "") if data else ""


def _topic_framework(topic: str) -> DomainFramework | None:
    data = _topic_pack(topic)
    if not data or not isinstance(data.get("paper_framework"), dict):
        return None
    raw = data["paper_framework"]
    name = str(raw.get("name") or "").strip()
    axes = tuple(str(x).strip() for x in raw.get("axes", []) if str(x).strip())
    falsifier = str(raw.get("falsifier") or "").strip()
    terms = tuple(str(x).strip().lower() for x in raw.get("class_terms", []) if str(x).strip())
    if not (name and axes and falsifier):
        return None
    return DomainFramework(name, terms or (topic.replace("_", " "),), axes, falsifier)


def _topic_pack(topic: str) -> dict[str, Any] | None:
    pack = REPO / "topic_packs" / f"{topic}.toml"
    if not pack.exists():
        return None
    try:
        return tomllib.loads(pack.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None


def _load_tensions(run_dir: Path) -> list[dict[str, Any]]:
    payload = _read_json(run_dir / "polish_tensions_appendix.json")
    if isinstance(payload, dict):
        items = payload.get("selected") or payload.get("all") or []
        return [t for t in items if isinstance(t, dict)]
    for path in (run_dir / "audit" / "tension_elaboration_plans.json", run_dir / "tension_elaboration_plans.json"):
        payload = _read_json(path)
        if isinstance(payload, dict) and isinstance(payload.get("plans"), list):
            return [t for t in payload["plans"] if isinstance(t, dict)]
    return []


def _build_thesis(
    paper: str, topic: str, framework: DomainFramework,
    receipts: list[dict[str, Any]], tensions: list[dict[str, Any]],
) -> PaperThesis:
    claim = _first_sentence(_section_text(paper, "Discussion")) or _first_sentence(_section_text(paper, "Abstract"))
    support = [
        str(r.get("receipt_id") or r.get("paper_id") or "")
        for r in sorted(receipts, key=_receipt_rank, reverse=True)[:8]
    ]
    contradiction_ids = [
        str(t.get("tension_id") or t.get("id") or f"tension_{i}")
        for i, t in enumerate(tensions[:8], 1)
    ]
    return PaperThesis(
        claim=claim or f"{topic.replace('_', ' ')} evidence requires bounded interpretation.",
        framework_name=framework.name,
        axes=list(framework.axes),
        falsifier=framework.falsifier,
        support_claim_ids=[s for s in support if s],
        contradiction_ids=contradiction_ids,
    )


def _receipt_rank(receipt: dict[str, Any]) -> tuple[int, int, int]:
    tier = str(receipt.get("evidence_tier") or "")
    direct = str(receipt.get("directness") or "")
    return (
        {"A1": 4, "A2": 3, "B1": 2, "B2": 1}.get(tier, 0),
        1 if direct == "direct" else 0,
        int(receipt.get("n_claims") or 0),
    )


def _title(paper: str, topic: str) -> str:
    m = re.search(r"^#\s+(.+)$", paper, re.M)
    return m.group(1).strip() if m else f"Research Synthesis: {topic.replace('_', ' ').title()}"


def _sections(paper: str) -> list[SectionIR]:
    matches = list(re.finditer(r"^(#{1,3})\s+(.+)$", paper, re.M))
    sections: list[SectionIR] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(paper)
        body = paper[match.end():end]
        sections.append(SectionIR(match.group(2).strip(), len(match.group(1)), len(body.split())))
    return sections


def _section_text(paper: str, heading: str) -> str:
    m = re.search(rf"(?ms)^##\s+{re.escape(heading)}\b.*?\n(.*?)(?=^##\s+|\Z)", paper)
    return m.group(1).strip() if m else ""


def _first_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.+?[.!?])(?:\s|$)", text)
    return m.group(1) if m else text[:240]


def _tables(run_dir: Path) -> list[TableIR]:
    supplement = run_dir / "structured_evidence_tables.md"
    if not supplement.exists():
        return []
    text = supplement.read_text(encoding="utf-8")
    tables: list[TableIR] = []
    for m in re.finditer(r"^##\s+(.+)$", text, re.M):
        end = text.find("\n## ", m.end())
        body = text[m.end(): end if end != -1 else len(text)]
        rows = sum(1 for line in body.splitlines() if line.strip().startswith("|")) - 1
        tables.append(TableIR(m.group(1).strip(), "structured_evidence_tables.md", max(rows, 0)))
    return tables


def _references(paper: str) -> list[str]:
    refs = _section_text(paper, "References")
    return [line.strip("- ").strip() for line in refs.splitlines() if line.strip().startswith(("-", "*"))]


def _write_exports(
    run_dir: Path, paper: str, manifest: dict[str, Any],
    receipts: list[dict[str, Any]], tensions: list[dict[str, Any]],
) -> dict[str, str | None]:
    _write_evidence_csv(run_dir / "evidence_table.csv", receipts)
    _write_bib(run_dir / "references.bib", _references(paper), manifest)
    (run_dir / "contradiction_map.json").write_text(json.dumps({"tensions": tensions}, indent=2) + "\n", encoding="utf-8")
    _write_docx(run_dir / "full_paper.docx", paper)
    return {
        "markdown": "full_paper.md",
        "pdf": "full_paper.pdf" if (run_dir / "full_paper.pdf").exists() else None,
        "docx": "full_paper.docx",
        "bibtex": "references.bib",
        "paper_audit": "paper_audit.json" if (run_dir / "paper_audit.json").exists() else None,
        "claim_cards": "claim_graph.json" if (run_dir / "claim_graph.json").exists() else None,
        "evidence_table_csv": "evidence_table.csv",
        "contradiction_map": "contradiction_map.json",
        "supplement": "structured_evidence_tables.md" if (run_dir / "structured_evidence_tables.md").exists() else None,
    }


def _write_evidence_csv(path: Path, receipts: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("receipt_id", "tier", "directness", "outcome_class", "effect_direction", "n_claims"))
        writer.writeheader()
        for r in receipts:
            writer.writerow({
                "receipt_id": r.get("receipt_id") or r.get("paper_id") or "",
                "tier": r.get("evidence_tier") or "",
                "directness": r.get("directness") or "",
                "outcome_class": r.get("outcome_class") or "",
                "effect_direction": r.get("effect_direction") or "",
                "n_claims": r.get("n_claims") or 0,
            })


def _write_bib(path: Path, refs: list[str], manifest: dict[str, Any]) -> None:
    topic = str(manifest.get("topic") or "research_synthesis")
    entries = []
    for idx, ref in enumerate(refs[:250], 1):
        year = re.search(r"\b(19|20)\d{2}\b", ref)
        entries.append(f"@misc{{{topic}_{idx},\n  title = {{{ref}}},\n  year = {{{year.group(0) if year else ''}}}\n}}")
    path.write_text("\n\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")


def _write_docx(path: Path, paper: str) -> None:
    document = _docx_body(paper)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        zf.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        zf.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{document}</w:body></w:document>')
        zf.writestr("researka/source.sha256", hashlib.sha256(paper.encode("utf-8")).hexdigest())


def _docx_body(paper: str) -> str:
    out: list[str] = []
    lines = paper.splitlines()
    idx = 0
    while idx < len(lines):
        table = _table_at(lines, idx)
        if table:
            rows, idx = table
            out.append(_docx_table(rows))
            continue
        line = lines[idx].strip()
        if line:
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            text = m.group(2).strip() if m else line
            bold = bool(m)
            out.append(f"<w:p><w:r>{'<w:b/>' if bold else ''}<w:t>{escape(text)}</w:t></w:r></w:p>")
        idx += 1
    return "".join(out)


def _table_at(lines: list[str], idx: int) -> tuple[list[list[str]], int] | None:
    if idx + 1 >= len(lines):
        return None
    if not (_is_pipe_row(lines[idx]) and _is_pipe_row(lines[idx + 1]) and set(lines[idx + 1].strip(" |:-")) <= {""}):
        return None
    width = len(_pipe_cells(lines[idx]))
    rows = [_pipe_cells(lines[idx])]
    idx += 2
    while idx < len(lines) and _is_pipe_row(lines[idx]):
        cells = _pipe_cells(lines[idx])
        if len(cells) != width:
            return None
        rows.append(cells)
        idx += 1
    return rows, idx


def _is_pipe_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _pipe_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _docx_table(rows: list[list[str]]) -> str:
    trs = []
    for row in rows:
        cells = "".join(f"<w:tc><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>" for cell in row)
        trs.append(f"<w:tr>{cells}</w:tr>")
    return "<w:tbl>" + "".join(trs) + "</w:tbl>"


def _quality_score(ir: PaperIR, paper: str, receipts: list[dict[str, Any]], tensions: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "has_thesis": bool(ir.thesis.claim and ir.thesis.framework_name),
        "has_core_sections": {"Abstract", "Methods", "Results", "Discussion", "Conclusion"}.issubset({s.heading.split(" — ")[0] for s in ir.sections}),
        "has_evidence": len(receipts) >= 5,
        "has_tensions": bool(tensions),
        "clean_public_wrapper": not re.search(r"\b(DECISION: ACCEPT|GATE FAILURES:|not extracted)\b", paper, re.I),
        "has_exports": all(ir.exports.get(k) for k in ("markdown", "docx", "bibtex", "evidence_table_csv", "contradiction_map")),
    }
    return {"schema": "researka.paper_quality_score.v1", "score_out_of_100": round(100 * sum(checks.values()) / len(checks), 1), "checks": checks}


def reresolve_export_manifest(run_dir: Path) -> bool:
    """Re-point public_export_manifest.json at post-organize file locations.

    The manifest is written by compile_run BEFORE _organize_run_artifacts
    relocates appraisal sidecars into audit/, so a recorded bare path can go
    stale (the file is no longer top-level yet `exists` stays True) and the
    public bundle then drops the populated sidecar — the reader shows
    "not appraised". Re-resolve any recorded path that no longer exists to its
    audit/ location. Idempotent; fail-open. Returns True if anything changed."""
    path = run_dir / "public_export_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    changed = False
    for entry in files.values():
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("path") or "")
        if not rel or (run_dir / rel).exists():
            continue
        audit_rel = f"audit/{rel.rsplit('/', 1)[-1]}"
        if (run_dir / audit_rel).exists():
            entry["path"], entry["exists"] = audit_rel, True
            changed = True
        elif entry.get("exists"):
            entry["exists"] = False
            changed = True
    if changed:
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return changed


def _export_manifest(run_dir: Path, ir: PaperIR, score: dict[str, Any]) -> dict[str, Any]:
    # Appraisal sidecars are public artifacts, but _organize_run_artifacts
    # relocates them into audit/; resolve either location so the public
    # manifest points at the populated file instead of reading "not appraised".
    def _rel(name: str) -> str:
        return name if (run_dir / name).exists() else f"audit/{name}"
    # Explicit/appraisal keys are declared AFTER **ir.exports so a named public
    # sidecar always wins over an exports-dict collision.
    export_paths = {
        **ir.exports,
        "paper_ir": "paper_ir.json",
        "paper_quality_score": "paper_quality_score.json",
        "risk_of_bias": _rel("risk_of_bias.json"),
        "grade_assessment": _rel("grade_assessment.json"),
        "quality_methods": _rel("quality_methods.json"),
    }
    files = {
        name: {"path": rel, "exists": bool(rel and (run_dir / rel).exists())}
        for name, rel in export_paths.items()
    }
    return {
        "schema": "researka.public_exports.v1",
        "topic": ir.topic,
        "title": ir.title,
        "quality_score": score["score_out_of_100"],
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(compile_run(args.run_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
