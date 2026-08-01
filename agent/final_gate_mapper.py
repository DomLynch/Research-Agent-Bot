"""Map synthesis artifacts into fail-closed final-gate inputs."""
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
    """Accept only an explicit all-pass or complete Stage-1 audit count."""
    if not isinstance(audit, dict):
        return False
    if audit.get("all_pass") is True:
        return True
    pc = audit.get("pass_count", audit.get("n_pass"))
    tc = audit.get("total_count", audit.get("n_total"))
    if isinstance(pc, int) and isinstance(tc, int) and tc > 0:
        complete = not isinstance(pc, bool) and not isinstance(tc, bool) and pc == tc
        return complete and audit.get("p1_pass", True) is True
    return False


def extract_journal_surface_passed(journal_surface: dict | None) -> bool:
    """Read an explicit journal-surface pass from supported artifact shapes."""
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
    """Count unresolved P1 patches and reject missing or malformed review state."""
    if not isinstance(patches, dict):
        raise ValueError("reviewer patch artifact missing or malformed")
    direct = patches.get("unresolved_p1_count")
    if isinstance(direct, int) and not isinstance(direct, bool) and direct >= 0:
        return direct
    patch_list = patches.get("patches")
    if isinstance(patch_list, list):
        if any(not isinstance(p, dict) for p in patch_list):
            raise ValueError("reviewer patch artifact contains a malformed patch")
        return sum(
            str(p.get("severity") or "").upper() == "P1"
            and str(p.get("status") or "").lower() not in ("applied", "resolved", "auto_strip")
            for p in patch_list
        )
    raise ValueError("reviewer patch artifact has no unresolved count or patch list")


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
    """Build final-gate inputs from artifacts, rejecting missing required state."""
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
