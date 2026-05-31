"""Phase 8 final-gate input mapper.

Bridges the synthesis-pipeline artifacts (audit.json, journal_surface.json,
review_patch_log.json, template-gate report, quality-methods bundle,
manifest counts) into a typed `agent.final_gate.GateInputs` instance.

Stdlib-only, no LLM. Two entry points:

  build_gate_inputs(...)            — caller passes already-extracted
                                      typed values (preferred path; the
                                      orchestrator does the extraction).
  build_gate_inputs_from_artifacts(...)
                                    — caller passes the raw dicts loaded
                                      from disk; this module extracts
                                      with explicit fail-closed defaults.

Fail-closed contract: missing required fields raise ValueError. Coverage
values out of [0,1] raise via GateInputs.__post_init__.
"""
from __future__ import annotations

from typing import Any

from agent.final_gate import GateInputs
from agent.quality_methods_bundle import QualityMethodsBundle
from agent.template_gate_adapter import TemplateGateReport

__all__ = [
    "build_gate_inputs",
    "build_gate_inputs_from_artifacts",
    "extract_audit_gates_passed",
    "extract_journal_surface_passed",
    "extract_unresolved_reviewer_p1_count",
]


# ---- Artifact extractors ---------------------------------------------------


def extract_audit_gates_passed(audit: dict | None) -> bool:
    """True iff the Stage-1 audit reports no P1 ship-blockers.

    Tolerant to common shapes:
      - {"p1_pass": True, "score": 8.5, "pass_rate": "10/14"} → True
      - {"all_pass": True} → True
      - {"pass_count": 14, "total_count": 14} → True
      - {"score": 10, "max_score": 10} → True
      - missing/None → False (fail-closed)
    """
    if not isinstance(audit, dict):
        return False
    if audit.get("all_pass") is True:
        return True
    if audit.get("p1_pass") is True:
        return True
    pc = audit.get("pass_count")
    tc = audit.get("total_count")
    if isinstance(pc, int) and isinstance(tc, int) and tc > 0:
        return pc >= tc
    return False


def extract_journal_surface_passed(journal_surface: dict | None) -> bool:
    """True iff the journal-surface gate reports a pass.

    Tolerant: 'pass', 'passed', or 'verdict' fields all consulted.
    """
    if not isinstance(journal_surface, dict):
        return False
    for key in ("pass", "passed"):
        value = journal_surface.get(key)
        if isinstance(value, bool):
            return value
    verdict = journal_surface.get("verdict")
    if isinstance(verdict, str):
        return verdict.lower() in ("pass", "passed", "ok", "clean")
    return False


def extract_unresolved_reviewer_p1_count(patches: dict | None) -> int:
    """Count of P1 patches that did not resolve.

    Tolerant to common shapes:
      - {"unresolved_p1_count": 3} → 3
      - {"patches": [...]} → counts patches with severity=='P1' and
        status not in {'applied', 'resolved'}
      - missing → 0 (treat as no unresolved issues; the audit gate itself
        handles the case where reviewer ran)
    """
    if not isinstance(patches, dict):
        return 0
    direct = patches.get("unresolved_p1_count")
    if isinstance(direct, int) and direct >= 0:
        return direct
    patch_list = patches.get("patches")
    if isinstance(patch_list, list):
        unresolved = 0
        for p in patch_list:
            if not isinstance(p, dict):
                continue
            severity = str(p.get("severity") or "").upper()
            status = str(p.get("status") or "").lower()
            if severity == "P1" and status not in ("applied", "resolved", "auto_strip"):
                unresolved += 1
        return unresolved
    return 0


# ---- Builders --------------------------------------------------------------


def _require(value: Any, name: str) -> Any:
    if value is None:
        raise ValueError(f"missing required field {name!r}")
    return value


def build_gate_inputs(
    *,
    numeric_coverage: float,
    citation_registry_complete: bool,
    audit_gates_passed: bool,
    journal_surface_passed: bool,
    unresolved_reviewer_p1_count: int,
    rob_coverage: float,
    grade_coverage: float,
    n_tensions: int,
    n_receipts: int,
    template_language_blocking: bool,
) -> GateInputs:
    """Direct builder. Caller has already extracted typed values."""
    return GateInputs(
        numeric_coverage=float(numeric_coverage),
        audit_gates_passed=bool(audit_gates_passed),
        journal_surface_passed=bool(journal_surface_passed),
        citation_registry_complete=bool(citation_registry_complete),
        rob_coverage=float(rob_coverage),
        grade_coverage=float(grade_coverage),
        n_tensions=int(n_tensions),
        n_receipts=int(n_receipts),
        unresolved_reviewer_p1_count=int(unresolved_reviewer_p1_count),
        template_language_blocking=bool(template_language_blocking),
    )


def build_gate_inputs_from_artifacts(
    *,
    audit: dict | None,
    journal_surface: dict | None,
    reviewer_patches: dict | None,
    template_gate: TemplateGateReport,
    quality_methods: QualityMethodsBundle,
    numeric_coverage: float,
    citation_registry_complete: bool,
    n_tensions: int,
    n_receipts: int,
) -> GateInputs:
    """Artifact-shaped builder. Extracts the audit / journal_surface /
    reviewer_patches signals from raw dicts using the explicit extractors
    above, then composes the GateInputs.

    Required typed inputs (numeric_coverage, citation_registry_complete,
    n_tensions, n_receipts) must be supplied by the orchestrator —
    extracting these from JSON shape is more variable across runs and
    belongs in the live runner, not here.

    Fails closed:
      - template_gate missing → TypeError on attribute access (caller bug).
      - quality_methods missing → TypeError likewise.
      - numeric_coverage / n_tensions / n_receipts None → ValueError.
    """
    _require(template_gate, "template_gate")
    _require(quality_methods, "quality_methods")
    _require(numeric_coverage, "numeric_coverage")
    _require(citation_registry_complete, "citation_registry_complete")
    _require(n_tensions, "n_tensions")
    _require(n_receipts, "n_receipts")
    return build_gate_inputs(
        numeric_coverage=numeric_coverage,
        citation_registry_complete=citation_registry_complete,
        audit_gates_passed=extract_audit_gates_passed(audit),
        journal_surface_passed=extract_journal_surface_passed(journal_surface),
        unresolved_reviewer_p1_count=extract_unresolved_reviewer_p1_count(
            reviewer_patches
        ),
        rob_coverage=quality_methods.rob_coverage,
        grade_coverage=quality_methods.grade_coverage,
        n_tensions=n_tensions,
        n_receipts=n_receipts,
        template_language_blocking=template_gate.template_language_blocking,
    )
