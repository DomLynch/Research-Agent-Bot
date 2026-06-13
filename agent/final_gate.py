"""Deterministic pre-cert final gate for trust-spine signals."""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "GateThresholds",
    "GateInputs",
    "GateResult",
    "RESEARKA_MIN_SOURCE_CITATIONS",
    "RECOMMENDED_SOURCE_CITATIONS",
    "DEFAULT_THRESHOLDS",
    "evaluate_final_gate",
    "landscape_thresholds",
]

RESEARKA_MIN_SOURCE_CITATIONS = 12
RECOMMENDED_SOURCE_CITATIONS = 30


@dataclass(frozen=True, slots=True)
class GateThresholds:
    """Threshold configuration. Defaults match AAA-CLIN cert expectations.

    P1 thresholds (failure if violated):
      audit_gates_passed                 existing Q/audit gate suite passed.
      journal_surface_passed             journal surface gate passed.
      unresolved_reviewer_p1_count       no unresolved reviewer P1 issues.
      min_numeric_coverage              every numeric must trace (1.0).
      require_complete_citation_registry every cite resolves (True).
      min_rob_coverage                  >=80% of receipts have source-text RoB.
      min_grade_coverage                every outcome class has GRADE (1.0).
      min_tensions                      >=1 tension surfaced.
      min_receipts                      >=12 receipts.
      template_language_must_pass       template-language gate clean.

    P2 thresholds (warning if violated, not blocking):
      warn_below_receipts               warn if receipts < this (default 30).
    """

    min_numeric_coverage: float = 1.0
    require_complete_citation_registry: bool = True
    min_rob_coverage: float = 0.8
    min_grade_coverage: float = 1.0
    min_tensions: int = 1
    min_receipts: int = RESEARKA_MIN_SOURCE_CITATIONS
    template_language_must_pass: bool = True
    warn_below_receipts: int = RECOMMENDED_SOURCE_CITATIONS

    def __post_init__(self) -> None:
        for name in ("min_numeric_coverage", "min_rob_coverage", "min_grade_coverage"):
            value = getattr(self, name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be in [0,1], got {value}")
        if self.min_tensions < 0:
            raise ValueError(f"min_tensions must be ≥0, got {self.min_tensions}")
        if self.min_receipts < 0:
            raise ValueError(f"min_receipts must be ≥0, got {self.min_receipts}")
        if self.warn_below_receipts < self.min_receipts:
            raise ValueError(
                f"warn_below_receipts ({self.warn_below_receipts}) must be "
                f">= min_receipts ({self.min_receipts})"
            )


DEFAULT_THRESHOLDS: GateThresholds = GateThresholds()


def landscape_thresholds(n_receipts: int, n_tensions: int) -> GateThresholds | None:
    """Relaxed thresholds for a zero-tension evidence_map landscape, else None.

    An evidence_map is reviewed for fidelity, not convergence: a corpus with no
    non-orthogonal cross-source tension is a valid landscape survey (nothing to
    adjudicate), not a failed thesis. For such corpora the >=1-tension floor is
    lifted; every integrity threshold (numeric trace, citation registry, RoB,
    GRADE, receipts, template language) is unchanged. Returns None for ordinary
    corpora so the caller falls back to DEFAULT_THRESHOLDS. High-tension
    landscapes already clear min_tensions=1, so only the zero-tension case
    needs relaxing here. Universal — keyed on tension count, not topic."""
    if n_receipts > 0 and n_tensions <= 0:
        return GateThresholds(min_tensions=0)
    return None


@dataclass(frozen=True, slots=True)
class GateInputs:
    """Trust-spine signals for the final gate.

    All coverage values are fractions in [0,1]. Counts are non-negative ints.
    """

    numeric_coverage: float
    audit_gates_passed: bool
    journal_surface_passed: bool
    citation_registry_complete: bool
    rob_coverage: float
    grade_coverage: float
    n_tensions: int
    n_receipts: int
    unresolved_reviewer_p1_count: int
    template_language_blocking: bool

    def __post_init__(self) -> None:
        for name in ("numeric_coverage", "rob_coverage", "grade_coverage"):
            value = getattr(self, name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be in [0,1], got {value}")
        if self.n_tensions < 0:
            raise ValueError(f"n_tensions must be ≥0, got {self.n_tensions}")
        if self.n_receipts < 0:
            raise ValueError(f"n_receipts must be ≥0, got {self.n_receipts}")
        if self.unresolved_reviewer_p1_count < 0:
            raise ValueError(
                "unresolved_reviewer_p1_count must be ≥0, "
                f"got {self.unresolved_reviewer_p1_count}"
            )


@dataclass(frozen=True, slots=True)
class GateResult:
    """Verdict from the final gate.

    passed   — False if any P1 failure; otherwise True.
    failures — names of P1 gates that failed, in declaration order.
    warnings — names of P2 thresholds that were tripped (informational).
    summary  — single human-readable line summarising the verdict.
    """

    passed: bool
    failures: tuple[str, ...]
    warnings: tuple[str, ...]
    summary: str


def _check_p1(inputs: GateInputs, thresholds: GateThresholds) -> list[str]:
    failures: list[str] = []
    if not inputs.audit_gates_passed:
        failures.append("audit_gates_failed")
    if not inputs.journal_surface_passed:
        failures.append("journal_surface_failed")
    if inputs.unresolved_reviewer_p1_count:
        failures.append(
            f"unresolved_reviewer_p1_count={inputs.unresolved_reviewer_p1_count}"
        )
    if inputs.numeric_coverage < thresholds.min_numeric_coverage:
        failures.append(
            f"numeric_coverage={inputs.numeric_coverage:.3f} "
            f"< threshold {thresholds.min_numeric_coverage:.3f}"
        )
    if thresholds.require_complete_citation_registry and not inputs.citation_registry_complete:
        failures.append("citation_registry_incomplete")
    if inputs.rob_coverage < thresholds.min_rob_coverage:
        failures.append(
            f"rob_coverage={inputs.rob_coverage:.3f} "
            f"< threshold {thresholds.min_rob_coverage:.3f}"
        )
    if inputs.grade_coverage < thresholds.min_grade_coverage:
        failures.append(
            f"grade_coverage={inputs.grade_coverage:.3f} "
            f"< threshold {thresholds.min_grade_coverage:.3f}"
        )
    if inputs.n_tensions < thresholds.min_tensions:
        failures.append(
            f"n_tensions={inputs.n_tensions} < threshold {thresholds.min_tensions}"
        )
    if inputs.n_receipts < thresholds.min_receipts:
        failures.append(
            f"n_receipts={inputs.n_receipts} < threshold {thresholds.min_receipts}"
        )
    if thresholds.template_language_must_pass and inputs.template_language_blocking:
        failures.append("template_language_gate_blocking")
    return failures


def _check_p2(inputs: GateInputs, thresholds: GateThresholds) -> list[str]:
    warnings: list[str] = []
    if inputs.n_receipts < thresholds.warn_below_receipts:
        warnings.append(
            f"n_receipts={inputs.n_receipts} below recommended "
            f"{thresholds.warn_below_receipts}"
        )
    return warnings


def evaluate_final_gate(
    inputs: GateInputs, *, thresholds: GateThresholds | None = None
) -> GateResult:
    """Evaluate the trust-spine signals against thresholds. Returns a
    GateResult with passed, failures, warnings, and a one-line summary."""
    thresholds = thresholds or DEFAULT_THRESHOLDS
    failures = _check_p1(inputs, thresholds)
    warnings = _check_p2(inputs, thresholds)
    passed = not failures
    if passed:
        summary = (
            f"PASS — {inputs.n_receipts} receipts, "
            f"RoB cov={inputs.rob_coverage:.0%}, "
            f"GRADE cov={inputs.grade_coverage:.0%}, "
            f"{inputs.n_tensions} tension(s)"
            + (f"; {len(warnings)} warning(s)" if warnings else "")
        )
    else:
        summary = f"FAIL — {len(failures)} blocker(s): " + "; ".join(failures)
    return GateResult(
        passed=passed,
        failures=tuple(failures),
        warnings=tuple(warnings),
        summary=summary,
    )
