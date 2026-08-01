"""Paper audit pack (FactReview / RefCopilot output contract, recreated — the
AGPL FactReview code is NOT copied; only the contract is reproduced).

Consolidates a finished run's already-persisted trust signals — citation
registry, paper-level audit, the unified final verdict, and the OpenAlex
retraction check — into one machine-readable `paper_audit.json` plus a
reviewer-facing `paper_audit.md`: a per-reference citation audit and a single
ship recommendation. This is the "paper + machine-readable audit pack" product
gap; the signals already exist scattered across sidecars — here they are rolled
up, not recomputed.

Deterministic except the retraction lookup (which blocks SHIP when unavailable). The per-claim
evidence/contradiction-snippet layer needs persisted CitationTrace records
(traces are in-memory only today) — flagged as the next slice. Topic-agnostic.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _read_json(run_dir: Path, name: str) -> Any:
    try:
        return json.loads((run_dir / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _bare_doi(doi: str) -> str:
    return doi.strip().lower().removeprefix("https://doi.org/").removeprefix("doi.org/")


def _references(registry: dict[str, Any], retracted: set[str]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for entry in registry.values() if isinstance(registry, dict) else []:
        if not isinstance(entry, dict):
            continue
        ids = [entry.get("source_doi"), entry.get("source_pmid"), entry.get("source_pmcid")]
        doi = _bare_doi(str(entry.get("source_doi") or ""))
        refs.append({
            "reference_id": entry.get("reference_id"),
            "body_citation": entry.get("body_citation"),
            "doi": entry.get("source_doi"),
            "pmid": entry.get("source_pmid"),
            "year": entry.get("source_year"),
            "resolved": any(str(x or "").strip() for x in ids),
            "retracted": bool(doi) and doi in retracted,
        })
    return sorted(refs, key=lambda r: str(r.get("reference_id") or ""))


def _ship_recommendation(verdict: dict[str, Any], ref_audit: dict[str, Any]) -> str:
    if ref_audit["retracted"]:
        return "BLOCK — cites a retracted source"
    if ref_audit.get("unresolved"):
        return "BLOCK — unresolved references"
    if ref_audit.get("retraction_check_available") is not True:
        return "BLOCK — retraction check unavailable"
    if not (verdict.get("p1_clean") if verdict.get("p1_clean") is not None else verdict.get("all_green")):
        return "BLOCK — unresolved P1 / not all-green"
    if verdict.get("all_green") and verdict.get("journal_ready"):
        return "SHIP — all gates green and journal-ready"
    return "CAVEAT — below journal-ready bar; human review advised"


def compose_audit_pack(
    run_dir: Path,
    *,
    retracted: list[str] | None = None,
    retracted_fetch: Callable[[Path], list[str]] | None = None,
) -> dict[str, Any]:
    """Roll a run's persisted sidecars into the audit-pack dict."""
    registry = _read_json(run_dir, "citation_registry.json") or {}
    audit = _read_json(run_dir, "full_paper.audit.json") or {}
    verdict = _read_json(run_dir, "full_paper.final_verdict.json") or {}
    retraction_check_available = retracted is not None
    if retracted is None:
        try:
            import retraction_check
            retracted = (retracted_fetch or retraction_check.retracted_cited_sources)(run_dir)
            retraction_check_available = True
        except Exception:
            retracted = []
    retracted_set = {_bare_doi(d) for d in (retracted or []) if d}
    refs = _references(registry if isinstance(registry, dict) else {}, retracted_set)
    ref_audit = {
        "total": len(refs),
        "resolved": sum(1 for r in refs if r["resolved"]),
        "unresolved": sum(1 for r in refs if not r["resolved"]),
        "retracted": [r["reference_id"] for r in refs if r["retracted"]],
        "retraction_check_available": retraction_check_available,
    }
    paper_verdict = {
        "maturity_level": verdict.get("maturity_level"),
        "maturity_label": verdict.get("maturity_label"),
        "all_green": verdict.get("all_green"),
        "journal_ready": verdict.get("journal_ready"),
        "p1_clean": verdict.get("p1_clean"),
        "journal_surface_pass": verdict.get("journal_surface_pass"),
        "audit_p1_pass": audit.get("p1_pass"),
        "audit_score": audit.get("score_out_of_10"),
    }
    return {
        "references": refs,
        "reference_audit": ref_audit,
        "paper_verdict": paper_verdict,
        "ship_recommendation": _ship_recommendation(verdict if isinstance(verdict, dict) else {}, ref_audit),
    }


def _render_md(pack: dict[str, Any]) -> str:
    ra, pv = pack["reference_audit"], pack["paper_verdict"]
    lines = [
        "# Paper Audit Pack", "",
        f"**Ship recommendation:** {pack['ship_recommendation']}", "",
        f"**Verdict:** maturity={pv.get('maturity_label') or pv.get('maturity_level')} · "
        f"all_green={pv.get('all_green')} · journal_ready={pv.get('journal_ready')} · "
        f"p1_clean={pv.get('p1_clean')} · audit={pv.get('audit_score')}/10", "",
        f"**References:** {ra['total']} total · {ra['resolved']} resolved · "
        f"{ra['unresolved']} unresolved · {len(ra['retracted'])} retracted · "
        f"retraction check available={ra['retraction_check_available']}", "",
    ]
    if ra["retracted"]:
        lines += [f"**RETRACTED sources cited:** {', '.join(str(r) for r in ra['retracted'])}", ""]
    lines += ["| Ref | Citation | DOI/PMID | Resolved | Retracted |", "|---|---|---|---|---|"]
    for r in pack["references"]:
        lines.append(
            f"| {r['reference_id']} | {r['body_citation']} | {r['doi'] or r['pmid'] or '—'} | "
            f"{'yes' if r['resolved'] else 'NO'} | {'YES' if r['retracted'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def write_audit_pack(run_dir: Path, **kwargs: Any) -> Path:
    pack = compose_audit_pack(run_dir, **kwargs)
    (run_dir / "paper_audit.json").write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    (run_dir / "paper_audit.md").write_text(_render_md(pack), encoding="utf-8")
    return run_dir / "paper_audit.json"
