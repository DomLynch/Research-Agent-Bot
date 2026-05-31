"""v3 polish compiler: optional PDF/lint sidecars plus deterministic paper QA.

No mandatory third-party deps. If Typst, sciwrite-lint, or sentence-transformers
are unavailable, the compiler records a skipped status and still emits useful
JSON. Standalone CLI exits nonzero only for deterministic polish failures.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import v3_optional_adapters as _optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = REPO_ROOT / "templates" / "paper.typ"
TOP_N_TENSIONS = 8


def _load_json(path: Path | None) -> Any:
    if not path or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _title(paper: str, manifest: dict[str, Any] | None) -> str:
    if manifest and manifest.get("topic"):
        return f"Research Synthesis: {str(manifest['topic']).replace('_', ' ').title()}"
    m = re.search(r"^#\s+(.+)$", paper, re.M)
    return m.group(1).strip() if m else "Research Synthesis"


def _typ_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("#", "\\#")
        .replace("$", "\\$")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("@", "\\@")
    )


def _is_pipe_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _pipe_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _pipe_table_gate(markdown: str) -> dict[str, Any]:
    lines = markdown.splitlines()
    tables = 0
    malformed: list[int] = []
    for idx, (header, separator) in enumerate(zip(lines, lines[1:], strict=False), 1):
        if not (_is_pipe_row(header) and _is_pipe_row(separator) and set(separator.strip(" |:-")) <= {""}):
            continue
        tables += 1
        width = len(_pipe_cells(header))
        rows = []
        for row in lines[idx + 1:]:
            if not _is_pipe_row(row):
                break
            rows.append(row)
        if any(len(_pipe_cells(row)) != width for row in rows):
            malformed.append(idx)
    if malformed:
        return {"status": "failed", "table_count": tables, "malformed_tables": malformed[:10]}
    if tables:
        return {"status": "advisory", "table_count": tables, "reason": "canonical_markdown_tables_present"}
    return {"status": "passed", "table_count": 0}


def _markdown_to_typst(markdown: str) -> str:
    out: list[str] = []
    in_table = False
    for line in markdown.splitlines():
        if _is_pipe_row(line):
            if not in_table:
                out.append("_Structured table omitted from PDF main text; see audit sidecars._")
                in_table = True
            continue
        in_table = False
        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m:
            out.append(f"{'=' * len(m.group(1))} {_typ_escape(m.group(2).strip())}")
        elif line.startswith("- "):
            out.append(f"- {_typ_escape(line[2:].strip())}")
        else:
            out.append(_typ_escape(line))
    return "\n".join(out).strip() + "\n"


def write_typst_source(run_dir: Path, paper: str, manifest: dict[str, Any] | None) -> Path:
    template = DEFAULT_TEMPLATE.read_text(encoding="utf-8")
    body = _markdown_to_typst(paper)
    typ = template.replace("{{TITLE}}", _typ_escape(_title(paper, manifest))).replace("{{BODY}}", body)
    out = run_dir / "full_paper.typ"
    out.write_text(typ, encoding="utf-8")
    return out


def _run_typst(typ_path: Path, pdf_path: Path) -> dict[str, Any]:
    exe = shutil.which("typst")
    if not exe:
        return {"status": "skipped", "reason": "typst_not_installed"}
    proc = subprocess.run(
        [exe, "compile", str(typ_path), str(pdf_path)],
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )
    return {
        "status": "passed" if proc.returncode == 0 else "failed",
        "return_code": proc.returncode,
        "pdf": str(pdf_path.name) if proc.returncode == 0 else None,
        "stderr": proc.stderr[-2000:],
    }


def _tension_text(tension: dict[str, Any]) -> str:
    return " ".join(str(tension.get(k, "")) for k in (
        "tension_id", "paper_a", "paper_b", "conflict_type", "outcome_class", "severity",
    ))


def _cosine(a: list[float], b: list[float]) -> float:
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=False)) / denom if denom else 0.0


def _embedding_vectors(texts: list[str]) -> list[list[float]] | None:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return [list(map(float, row)) for row in model.encode(texts, normalize_embeddings=True)]
    except Exception:
        return None


def select_diverse_tensions(tensions: list[dict[str, Any]], *, top_n: int = TOP_N_TENSIONS) -> list[dict[str, Any]]:
    ranked = sorted(tensions, key=lambda t: (-int(t.get("severity") or 0), str(t.get("outcome_class") or ""), str(t.get("tension_id") or "")))
    vectors = _embedding_vectors([_tension_text(t) for t in ranked]) if len(ranked) > top_n else None
    selected: list[int] = []
    used_keys: set[tuple[str, str]] = set()
    for idx, item in enumerate(ranked):
        key = (str(item.get("outcome_class") or ""), str(item.get("conflict_type") or ""))
        if key in used_keys and len(ranked) - idx > top_n:
            continue
        if vectors and any(_cosine(vectors[idx], vectors[j]) > 0.86 for j in selected):
            continue
        selected.append(idx)
        used_keys.add(key)
        if len(selected) >= top_n:
            break
    return [ranked[i] for i in selected] or ranked[:top_n]


def _tensions_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("plans"), list):
        return [t for t in payload["plans"] if isinstance(t, dict)]
    if isinstance(payload, list):
        return [t for t in payload if isinstance(t, dict)]
    return []


def _run_sciwrite(paper_path: Path) -> dict[str, Any]:
    exe = shutil.which("sciwrite-lint")
    if not exe:
        return {"status": "skipped", "reason": "sciwrite_lint_not_installed"}
    proc = subprocess.run(
        [exe, "--json", str(paper_path)],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    try:
        payload: Any = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {"stdout": proc.stdout[-2000:]}
    return {
        "status": "passed" if proc.returncode == 0 else "failed",
        "return_code": proc.returncode,
        "payload": payload,
        "stderr": proc.stderr[-2000:],
    }


def _sciwrite_abstract_mismatch(result: dict[str, Any]) -> bool:
    text = json.dumps(result.get("payload", {})).lower()
    severe = any(word in text for word in ("critical", "severe", "error"))
    return severe and "abstract" in text and ("body" in text or "mismatch" in text)


def _claim_graph_gate(claim_graph: Any) -> dict[str, Any]:
    if not isinstance(claim_graph, dict):
        return {"status": "skipped", "reason": "claim_graph_missing"}
    claims = claim_graph.get("claims")
    if not isinstance(claims, list):
        return {"status": "skipped", "reason": "claims_missing"}
    missing = [
        c.get("claim_id") or c.get("id") or i
        for i, c in enumerate(claims[:10], 1) if isinstance(c, dict)
        and not (c.get("supporting_refs") or c.get("source_ids") or c.get("sources"))
    ]
    return {"status": "passed" if not missing else "failed", "missing_source_ids": missing}


def compile_run(run_dir: Path) -> dict[str, Any]:
    paper_path = run_dir / "full_paper.md"
    paper = paper_path.read_text(encoding="utf-8")
    manifest = _load_json(run_dir / "manifest.json")
    if not isinstance(manifest, dict):
        manifest = None
    tension_payload = _load_json(run_dir / "audit" / "tension_elaboration_plans.json") or _load_json(run_dir / "tension_elaboration_plans.json")
    all_tensions = _tensions_from_payload(tension_payload)
    selected_tensions = select_diverse_tensions(all_tensions)
    (run_dir / "polish_tensions_appendix.json").write_text(
        json.dumps({"selected": selected_tensions, "all": all_tensions}, indent=2),
        encoding="utf-8",
    )
    typ_path = write_typst_source(run_dir, paper, manifest)
    sciwrite = _run_sciwrite(paper_path)
    gates = {
        "raw_pipe_tables": _pipe_table_gate(paper),
        "top_claim_source_ids": _claim_graph_gate(_load_json(run_dir / "claim_graph.json")),
        "abstract_body_mismatch": {"status": "failed" if _sciwrite_abstract_mismatch(sciwrite) else "passed"},
        "falsifier_or_next_study": {
            "status": "passed" if re.search(r"\b(falsif|next[- ]study|future work|targeted research|registered trial)\b", paper, re.I) else "failed",
        },
    }
    passed = all(g["status"] in {"passed", "skipped", "advisory"} for g in gates.values())
    report = {
        "passed": passed,
        "run_dir": str(run_dir),
        "tensions": {"selected": len(selected_tensions), "total": len(all_tensions)},
        "typst": _run_typst(typ_path, run_dir / "full_paper.pdf"),
        "sciwrite_lint": sciwrite,
        "gates": gates,
    }
    report["biomed_normalization"] = _optional.normalize_biomed_terms(
        paper[:12000], run_dir / "biomed_normalization.json",
    )
    report["docling_fallback"] = _optional.write_docling_paper_sections(
        source_uri="", parsed_dir=run_dir, paper_id="polish_docling_probe",
        metadata={}, reason="polish_probe_no_source",
    )
    (run_dir / "docling_fallback.json").write_text(
        json.dumps(report["docling_fallback"], indent=2),
        encoding="utf-8",
    )
    report["structured_output"] = _optional.validate_structured_output(
        report,
        {"passed": "bool", "run_dir": "str", "tensions": "dict", "gates": "dict"},
        run_dir / "structured_output_contract.json",
    )
    report["offline_eval_harness"] = _optional.run_offline_eval_harness(
        run_dir, report, run_dir / "offline_eval_harness.json",
    )
    (run_dir / "polish_compiler.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (run_dir / "polish_compiler.md").write_text(_format_report(report), encoding="utf-8")
    return report


def _format_report(report: dict[str, Any]) -> str:
    lines = ["# v3 Polish Compiler", "", f"**Passed:** {report['passed']}", ""]
    lines.append(f"**Tensions:** selected {report['tensions']['selected']} / {report['tensions']['total']}")
    lines.append(f"**Typst:** {report['typst']['status']}")
    lines.append(f"**sciwrite-lint:** {report['sciwrite_lint']['status']}")
    lines.append("")
    lines.append("## Gates")
    for name, gate in report["gates"].items():
        lines.append(f"- **{name}:** {gate['status']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile v3 paper polish sidecars for one run directory.")
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    report = compile_run(args.run_dir)
    print(args.run_dir / "polish_compiler.json")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
