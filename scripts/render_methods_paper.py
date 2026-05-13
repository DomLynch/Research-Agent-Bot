#!/usr/bin/env python3
"""Render a methods-paper draft from completed synthesis run artifacts.

This is a meta-output lane, not a second research bot. It reads existing
manifests, gates, audits, and verdicts, then writes a bounded methods paper
and benchmark metrics bundle.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TOPICS = (
    "metformin",
    "caloric_restriction",
    "urolithin_a",
    "rapamycin",
    "statins",
    "glp1",
    "omega3",
    "resistance_training",
    "creatine",
    "berberine",
)
DEFAULT_CASE_STUDIES = ("metformin", "caloric_restriction", "urolithin_a")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _topic_from_run_name(name: str) -> str | None:
    match = re.match(r"^synthesis-(.+?)-v\d+", name)
    return match.group(1) if match else None


def _latest_run(runs_dir: Path, topic: str) -> Path | None:
    candidates = []
    for path in runs_dir.glob(f"synthesis-{topic}-v*"):
        if not path.is_dir():
            continue
        required = (
            "manifest.json",
            "full_paper.final_verdict.json",
            "full_paper.journal_surface.json",
        )
        if all((path / name).exists() for name in required):
            candidates.append(path)
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _audit_counts(audit: dict[str, Any]) -> tuple[int, int]:
    if "n_pass" in audit and "n_total" in audit:
        return int(audit.get("n_pass") or 0), int(audit.get("n_total") or 0)
    checks = audit.get("checks")
    if not isinstance(checks, list):
        return 0, 0
    total = len(checks)
    passed = sum(1 for row in checks if isinstance(row, dict) and row.get("passed"))
    return passed, total


def _numeric_grounding(gate_inputs: dict[str, Any], audit: dict[str, Any]) -> float:
    value = gate_inputs.get("numeric_coverage")
    if isinstance(value, (int, float)):
        return float(value)
    for row in _list(audit.get("checks")):
        if not isinstance(row, dict) or row.get("name") != "Q2_numeric_integrity":
            continue
        detail = str(row.get("detail") or "")
        percent = re.search(r"\((\d+)%\)", detail)
        if percent:
            return int(percent.group(1)) / 100
    return 0.0


def _citation_accuracy(
    run_dir: Path,
    *,
    receipts: int,
    registry: dict[str, Any],
    gate_inputs: dict[str, Any],
) -> tuple[float, str]:
    consistency = _read_json(run_dir / "full_paper.consistency.json")
    consistency_issues = _list(consistency.get("issues")) if consistency else []
    citation_issues = [
        item for item in consistency_issues
        if any(
            token in str(item).lower()
            for token in ("citation", "reference", "doi", "pmid")
        )
    ]
    complete = bool(
        gate_inputs.get("citation_registry_complete")
        or (receipts and len(registry) >= receipts)
    )
    if complete and not citation_issues:
        return 1.0, "registry complete; no citation consistency issues"
    if not complete:
        return 0.0, "citation registry incomplete"
    return 0.5, f"{len(citation_issues)} citation consistency issue(s)"


def _metric_row(run_dir: Path) -> dict[str, Any]:
    manifest = _read_json(run_dir / "manifest.json")
    verdict = _read_json(run_dir / "full_paper.final_verdict.json")
    surface = _read_json(run_dir / "full_paper.journal_surface.json")
    audit = _read_json(run_dir / "full_paper.audit.json")
    gate = _read_json(run_dir / "pre_submit_gate.json")
    citation_registry = _read_json(run_dir / "citation_registry.json")
    gate_inputs = _dict(gate.get("inputs"))
    gate_result = _dict(gate.get("result"))
    audit_pass, audit_total = _audit_counts(audit)
    surface_issues = _list(surface.get("issues"))
    gate_failures = _list(gate_result.get("failures"))
    topic = str(manifest.get("topic") or _topic_from_run_name(run_dir.name) or "")
    receipts = int(manifest.get("n_receipts") or 0)
    citation_accuracy, citation_basis = _citation_accuracy(
        run_dir,
        receipts=receipts,
        registry=citation_registry,
        gate_inputs=gate_inputs,
    )
    runtime = _read_json(run_dir / "benchmark_runtime.json")
    return {
        "topic": topic,
        "run_id": run_dir.name,
        "run_path": str(run_dir),
        "generated_at": manifest.get("generated_at"),
        "receipts": receipts,
        "claims": int(manifest.get("n_high_confidence_claims_total") or 0),
        "tensions": int(manifest.get("n_non_orthogonal_tensions") or 0),
        "citation_accuracy": citation_accuracy,
        "citation_accuracy_basis": citation_basis,
        "citation_registry_complete": citation_accuracy == 1.0,
        "citation_registry_entries": len(citation_registry),
        "numeric_grounding": _numeric_grounding(gate_inputs, audit),
        "section_complete": bool(surface.get("passed")),
        "section_issue_count": len(surface_issues),
        "contract_failures": list(gate_failures) + list(surface_issues),
        "audit_pass": audit_pass,
        "audit_total": audit_total,
        "verdict": str(verdict.get("verdict") or ""),
        "maturity_level": int(verdict.get("maturity_level") or 0),
        "journal_ready": bool(verdict.get("journal_ready")),
        "reviewer_flags": int(verdict.get("grok_flagged") or 0),
        "reviewer_unresolved_p1": int(verdict.get("grok_unresolved_p1") or 0),
        "stage2_p1": int(verdict.get("stage2_p1") or 0),
        "llm_calls": int(manifest.get("n_llm_calls") or 0),
        "cost_usd": float(manifest.get("total_cost_usd") or 0.0),
        "runtime_seconds": float(runtime.get("runtime_seconds") or 0.0),
        "fresh_run": bool(runtime.get("fresh_run")),
    }


def collect_metrics(runs_dir: Path, topics: tuple[str, ...]) -> dict[str, Any]:
    rows = []
    missing = []
    for topic in topics:
        run = _latest_run(runs_dir, topic)
        if run is None:
            missing.append(topic)
            continue
        rows.append(_metric_row(run))
    totals = {
        "topics_requested": len(topics),
        "topics_measured": len(rows),
        "missing_topics": missing,
        "receipts": sum(row["receipts"] for row in rows),
        "claims": sum(row["claims"] for row in rows),
        "tensions": sum(row["tensions"] for row in rows),
        "total_cost_usd": round(sum(row["cost_usd"] for row in rows), 6),
        "total_llm_calls": sum(row["llm_calls"] for row in rows),
        "total_runtime_seconds": round(sum(row["runtime_seconds"] for row in rows), 2),
        "fresh_topics": sum(1 for row in rows if row["fresh_run"]),
        "journal_ready_topics": sum(1 for row in rows if row["journal_ready"]),
        "section_complete_topics": sum(1 for row in rows if row["section_complete"]),
        "pre_submit_clean_topics": sum(1 for row in rows if not row["contract_failures"]),
    }
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "claim_boundary": (
            "auditable structured evidence synthesis; not automated systematic review"
        ),
        "topics": list(topics),
        "case_studies": [
            row for row in rows if row["topic"] in DEFAULT_CASE_STUDIES
        ][:3],
        "rows": rows,
        "totals": totals,
    }


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _status(row: dict[str, Any]) -> str:
    if row["journal_ready"]:
        return "journal-ready by pipeline contract"
    if row["maturity_level"] >= 4:
        return "analytically certified, not journal-ready"
    return "draft-quality or blocked"


def render_methods_paper(metrics: dict[str, Any]) -> str:
    rows = metrics["rows"]
    totals = metrics["totals"]
    if rows:
        numeric_mean = sum(row["numeric_grounding"] for row in rows) / len(rows)
        citation_mean = sum(row["citation_accuracy"] for row in rows) / len(rows)
        citation_complete = sum(1 for row in rows if row["citation_registry_complete"])
    else:
        numeric_mean = 0.0
        citation_mean = 0.0
        citation_complete = 0
    table = [
        "| Topic | Receipts | Claims | Citation accuracy | Numeric grounding | Section contract | Reviewer flags | Verdict | Runtime | Cost |",
        "|---|---:|---:|---:|---:|---|---:|---|---:|---:|",
    ]
    for row in rows:
        section = "pass" if row["section_complete"] else f"{row['section_issue_count']} issue(s)"
        table.append(
            "| {topic} | {receipts} | {claims} | {citation} | {numeric} | {section} | "
            "{flags} | {verdict} / L{level} | {runtime:.0f}s | ${cost:.4f} |".format(
                topic=row["topic"].replace("_", " "),
                receipts=row["receipts"],
                claims=row["claims"],
                citation=_pct(row["citation_accuracy"]),
                numeric=_pct(row["numeric_grounding"]),
                section=section,
                flags=row["reviewer_flags"],
                verdict=row["verdict"] or "unscored",
                level=row["maturity_level"],
                runtime=row["runtime_seconds"],
                cost=row["cost_usd"],
            )
        )
    case_lines = []
    for row in metrics["case_studies"]:
        failures = row["contract_failures"] or ["none"]
        case_lines.append(
            "### {topic}\n\n"
            "The {topic} run contained {receipts} receipts, {claims} high-confidence "
            "observations, and {tensions} cross-study tensions. Numeric grounding was "
            "{numeric}; citation registry completeness was {citation}. The final "
            "pipeline state was {verdict} at L{level}. Remaining contract failures: "
            "{failures}.".format(
                topic=row["topic"].replace("_", " ").title(),
                receipts=row["receipts"],
                claims=row["claims"],
                tensions=row["tensions"],
                numeric=_pct(row["numeric_grounding"]),
                citation="complete" if row["citation_registry_complete"] else "incomplete",
                verdict=row["verdict"] or "unscored",
                level=row["maturity_level"],
                failures=", ".join(map(str, failures)),
            )
        )
    return "\n\n".join([
        "# An Auditable Compiler for AI-Assisted Biomedical Evidence Synthesis",
        "## Abstract\n\n"
        "AI systems can accelerate evidence synthesis, but generated prose is not "
        "itself a trustworthy scientific object. We describe a deterministic "
        "compiler architecture in which language models propose extraction, "
        "drafting, and review artifacts, while code owns corpus state, citation "
        "identity, numeric traceability, section contracts, quarantine, and final "
        "verdicts. In a frozen benchmark of {n} longevity-related topics, the "
        "pipeline processed {receipts} source receipts, {claims} high-confidence "
            "observations, and {tensions} cross-study tensions at ${cost:.4f} recorded "
        "model cost. Mean citation-accuracy proxy was {citation_mean}; mean "
        "numeric grounding was {numeric}; {citation}/{n_measured} runs reported "
        "complete citation registries. These "
        "results support a bounded claim: the system produces auditable structured "
        "evidence syntheses and reproducible support bundles. They do not establish "
        "automated systematic-review equivalence, formal PRISMA compliance, or "
        "clinical validity without external human validation.".format(
            n=totals["topics_requested"],
            n_measured=totals["topics_measured"],
            receipts=totals["receipts"],
            claims=totals["claims"],
            tensions=totals["tensions"],
            cost=totals["total_cost_usd"],
            numeric=_pct(numeric_mean),
            citation_mean=_pct(citation_mean),
            citation=citation_complete,
        ),
        "## Introduction\n\n"
        "The central failure mode for AI-written reviews is not weak prose; it is "
        "unobservable drift between evidence, counts, citations, numeric claims, "
        "and the final manuscript. ReseaRka addresses that problem by treating "
        "the manuscript as a rendered artifact rather than the source of truth. "
        "The source of truth is a bundle of machine-readable manifests, citation "
        "registries, audit reports, reviewer flags, and verdict sidecars.",
        "## Methods\n\n"
        "We froze a benchmark panel of longevity-related topics and evaluated "
        "fresh synthesis runs where runtime sidecars were available, falling back "
        "only to the latest completed run when a fresh run was absent. Metrics "
        "required manifest, "
        "journal-surface, and final-verdict artifacts. Metrics were read from "
        "existing sidecars: corpus size from `manifest.json`, numeric grounding "
        "and citation-registry completeness from `pre_submit_gate.json`, section "
        "completeness from `full_paper.journal_surface.json`, audit performance "
        "from `full_paper.audit.json`, reviewer flags and maturity from "
        "`full_paper.final_verdict.json`, and cost from manifest model-use fields. "
        "This is an internal methods benchmark over completed runs: auditable "
        "structured evidence synthesis, not automated systematic review, not a "
        "new clinical meta-analysis, and not a substitute for blinded dual "
        "screening.",
        "## Results\n\n" + "\n".join(table),
        "## Case Studies\n\n" + "\n\n".join(case_lines),
        "## Discussion\n\n"
        "The benchmark supports the methods claim that deterministic contracts can "
        "make AI-assisted evidence synthesis inspectable. The most important "
        "signal is not that every run becomes journal-ready; several runs remain "
        "blocked or analytically certified only. The value is that those states "
        "are explicit, measurable, and reproducible from sidecar artifacts rather "
        "than inferred from manuscript polish.\n\n"
        "The current system is best described as an auditable structured evidence "
        "synthesis engine. It should not be marketed as an automated systematic "
        "review engine until protocol registration, broader database coverage, "
        "human adjudication benchmarks, and endpoint-compatible meta-analysis "
        "paths are validated.",
        "## Limitations\n\n"
        "This benchmark uses available completed runs and pipeline-side metrics. "
        "Citation completeness is not the same as independent citation accuracy; "
        "numeric grounding is not the same as external statistical validation; "
        "and journal-surface success is not the same as editorial acceptance. The "
        "next validation step is a locked external reference set with human "
        "agreement statistics for study inclusion, claim direction, numeric "
        "traceability, and reviewer-flag adjudication.",
        "## Conclusion\n\n"
        "ReseaRka is closest to a credible methods-paper claim when framed "
        "narrowly: it compiles auditable biomedical evidence-synthesis bundles "
        "with deterministic contracts around AI-written manuscripts. The strongest "
        "next paper is therefore a methods paper with benchmarked failure modes, "
        "not a claim that every generated manuscript is a completed systematic "
        "review.",
    ])


def write_outputs(metrics: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8",
    )
    (out_dir / "methods_paper.md").write_text(
        render_methods_paper(metrics) + "\n", encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", type=Path, default=REPO / "runs")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--topic", action="append", dest="topics")
    args = parser.parse_args()
    topics = tuple(args.topics or DEFAULT_TOPICS)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = args.out_dir or (args.runs_dir / f"methods-paper-benchmark-{stamp}")
    metrics = collect_metrics(args.runs_dir, topics)
    write_outputs(metrics, out_dir)
    print(out_dir)
    print(json.dumps(metrics["totals"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
