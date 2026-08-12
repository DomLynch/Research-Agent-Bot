"""Publication-readiness scorer for the 2026-05-09 panel rubric.

Stdlib-only, no LLM. Reproduces the 6-dimension x 5-point scorecard
+ two boolean gates (claim_support, overclaim) deterministically from
manifest / audit / RoB / GRADE / tension / template-gate signals.

Rubric: research_question, synthesis, gaps, claim_evidence, limitations,
source_grounding (each 0-5). Total accept floor = 27/30 + claim_support
="supported" + overclaim="none". Else REVISE or REJECT.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from agent.final_gate import RESEARKA_MIN_SOURCE_CITATIONS

__all__ = [
    "RubricDimension",
    "ClaimSupport",
    "OverclaimLevel",
    "Verdict",
    "ScoreInputs",
    "RubricScore",
    "ScorecardResult",
    "score_publication",
    "ACCEPT_TOTAL_FLOOR",
]

RubricDimension = Literal[
    "research_question",
    "synthesis",
    "gaps",
    "claim_evidence",
    "limitations",
    "source_grounding",
]
ClaimSupport = Literal["supported", "partially_supported", "unsupported"]
OverclaimLevel = Literal["none", "mild", "moderate", "severe"]
Verdict = Literal["accept", "revise", "reject"]

ACCEPT_TOTAL_FLOOR: int = 27  # panel boundary
_VALID_CLAIM_SUPPORT: frozenset[str] = frozenset(
    ("supported", "partially_supported", "unsupported")
)
_VALID_OVERCLAIM: frozenset[str] = frozenset(("none", "mild", "moderate", "severe"))


@dataclass(frozen=True, slots=True)
class ScoreInputs:
    """Signals required to compute the rubric score.

    All bool/float values are derived upstream (manifest, audit.json,
    quality_methods_bundle, framework_section_engagements, etc.).
    """

    n_receipts: int
    n_outcome_classes: int
    n_tensions: int
    rob_coverage: float
    grade_coverage: float
    numeric_coverage: float
    citation_registry_complete: bool
    audit_gates_passed: bool
    template_language_blocking: bool
    field_engagements_supported: int    # applicable frameworks with support
    field_engagements_total: int        # applicable named frameworks; zero means N/A
    has_explicit_thesis: bool           # manifest.thesis non-empty
    has_limitations_section: bool       # paper has Limitations section
    has_clinical_practice_statement: bool  # Bug 3: conclusion has the line
    unresolved_reviewer_p1_count: int
    appraisal_required: bool = True

    def __post_init__(self) -> None:
        for name in ("rob_coverage", "grade_coverage", "numeric_coverage"):
            v = getattr(self, name)
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"{name} must be in [0,1], got {v}")
        for name in ("n_receipts", "n_outcome_classes", "n_tensions",
                     "field_engagements_supported", "field_engagements_total",
                     "unresolved_reviewer_p1_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >=0")


@dataclass(frozen=True, slots=True)
class RubricScore:
    """Per-dimension scores."""

    research_question: int
    synthesis: int
    gaps: int
    claim_evidence: int
    limitations: int
    source_grounding: int

    @property
    def total(self) -> int:
        return (
            self.research_question + self.synthesis + self.gaps
            + self.claim_evidence + self.limitations + self.source_grounding
        )

    def as_mapping(self) -> Mapping[RubricDimension, int]:
        return {
            "research_question": self.research_question,
            "synthesis": self.synthesis,
            "gaps": self.gaps,
            "claim_evidence": self.claim_evidence,
            "limitations": self.limitations,
            "source_grounding": self.source_grounding,
        }


@dataclass(frozen=True, slots=True)
class ScorecardResult:
    """Full scorecard: rubric + boolean gates + verdict + actionable list."""

    rubric: RubricScore
    claim_support: ClaimSupport
    overclaim: OverclaimLevel
    verdict: Verdict
    blockers: tuple[str, ...]      # named issues blocking ACCEPT
    notes: tuple[str, ...]         # informational findings
    summary: str                   # one-line verdict


# ---- Rubric scorers (each returns int 0-5) -------------------------------


def _score_research_question(s: ScoreInputs) -> tuple[int, list[str]]:
    notes: list[str] = []
    score = 0
    if s.has_explicit_thesis:
        score += 3
    else:
        notes.append("research_question: thesis not explicit in manifest")
    if s.n_outcome_classes >= 2:
        score += 2
    elif s.n_outcome_classes == 1:
        score += 1
        notes.append("research_question: single outcome class limits scope")
    return min(5, score), notes


def _score_synthesis(s: ScoreInputs) -> tuple[int, list[str]]:
    notes: list[str] = []
    score = 0
    if s.n_receipts >= 30:
        score += 3
    elif s.n_receipts >= RESEARKA_MIN_SOURCE_CITATIONS:
        score += 2
    elif s.n_receipts >= 5:
        score += 1
    if s.n_receipts < RESEARKA_MIN_SOURCE_CITATIONS:
        notes.append(f"synthesis: only {s.n_receipts} receipts (panel expects >=12)")
    if s.n_tensions >= 3:
        score += 2
    elif s.n_tensions >= 1:
        score += 1
    else:
        notes.append("synthesis: no cross-paper tensions surfaced")
    return min(5, score), notes


def _score_gaps(s: ScoreInputs) -> tuple[int, list[str]]:
    notes: list[str] = []
    score = 0
    if s.has_limitations_section:
        score += 2
    if s.field_engagements_total == 0:
        # Named framework registries are topic-specific. N/A must not penalize
        # an otherwise complete paper from another research domain.
        score += 1
    else:
        ratio = s.field_engagements_supported / s.field_engagements_total
        if ratio < 1.0:
            # Some frameworks unsupported; corpus gap acknowledged.
            score += 2
            notes.append(
                f"gaps: {s.field_engagements_total - s.field_engagements_supported} "
                f"of {s.field_engagements_total} field frameworks insufficient"
            )
        else:
            score += 1
    if s.n_tensions >= 1:
        score += 1
    return min(5, score), notes


def _score_claim_evidence(s: ScoreInputs) -> tuple[int, list[str]]:
    notes: list[str] = []
    score = 0
    if s.numeric_coverage >= 1.0:
        score += 3
    elif s.numeric_coverage >= 0.95:
        score += 2
        notes.append(
            f"claim_evidence: numeric_coverage={s.numeric_coverage:.2f} "
            f"(target 1.0)"
        )
    elif s.numeric_coverage >= 0.8:
        score += 1
        notes.append("claim_evidence: numeric trace gaps")
    else:
        notes.append("claim_evidence: numeric trace seriously broken")
    if s.audit_gates_passed:
        score += 1
    if not s.template_language_blocking:
        score += 1
    return min(5, score), notes


def _score_limitations(s: ScoreInputs) -> tuple[int, list[str]]:
    notes: list[str] = []
    score = 0
    if s.has_limitations_section:
        score += 2
    if s.has_clinical_practice_statement:
        score += 2
    else:
        notes.append("limitations: missing clinical-practice statement (Bug 3)")
    if not s.appraisal_required or s.rob_coverage >= 0.5:
        score += 1
    return min(5, score), notes


def _score_source_grounding(s: ScoreInputs) -> tuple[int, list[str]]:
    notes: list[str] = []
    score = 0
    if s.citation_registry_complete:
        score += 2
    else:
        notes.append("source_grounding: citation registry incomplete")
    if not s.appraisal_required:
        score += 2
    elif s.rob_coverage >= 0.8:
        score += 1
    elif s.rob_coverage >= 0.5:
        score += 0  # explicit no-credit
        notes.append(
            f"source_grounding: rob_coverage={s.rob_coverage:.2f} (target >=0.8)"
        )
    if s.appraisal_required and s.grade_coverage >= 1.0:
        score += 1
    if s.field_engagements_total == 0 or s.field_engagements_supported >= 1:
        score += 1
    return min(5, score), notes


# ---- Boolean gates -------------------------------------------------------


def _classify_claim_support(s: ScoreInputs) -> ClaimSupport:
    if (s.numeric_coverage >= 1.0 and s.audit_gates_passed
            and s.citation_registry_complete and s.unresolved_reviewer_p1_count == 0):
        return "supported"
    if s.numeric_coverage >= 0.85 and s.unresolved_reviewer_p1_count <= 1:
        return "partially_supported"
    return "unsupported"


def _classify_overclaim(s: ScoreInputs) -> OverclaimLevel:
    """Template-language gate is the canonical overclaim signal.
    P1 hits = severe; P2 only = mild; clean = none.

    Caller passes only `template_language_blocking`; for finer
    granularity, expose p1_count via ScoreInputs in a future revision."""
    if s.template_language_blocking and s.unresolved_reviewer_p1_count >= 1:
        return "severe"
    if s.template_language_blocking:
        return "mild"
    return "none"


def _decide_verdict(
    total: int, claim_support: ClaimSupport, overclaim: OverclaimLevel
) -> Verdict:
    if (total >= ACCEPT_TOTAL_FLOOR
            and claim_support == "supported"
            and overclaim == "none"):
        return "accept"
    if total >= 18 and claim_support != "unsupported":
        return "revise"
    return "reject"


# ---- Top-level scorer ----------------------------------------------------


def score_publication(inputs: ScoreInputs) -> ScorecardResult:
    """Compute the full scorecard. Deterministic; no LLM."""
    rq, n1 = _score_research_question(inputs)
    syn, n2 = _score_synthesis(inputs)
    gaps, n3 = _score_gaps(inputs)
    ce, n4 = _score_claim_evidence(inputs)
    lim, n5 = _score_limitations(inputs)
    sg, n6 = _score_source_grounding(inputs)
    rubric = RubricScore(rq, syn, gaps, ce, lim, sg)

    claim_support = _classify_claim_support(inputs)
    overclaim = _classify_overclaim(inputs)
    verdict = _decide_verdict(rubric.total, claim_support, overclaim)

    blockers = _collect_blockers(rubric, claim_support, overclaim)
    notes = tuple(n1 + n2 + n3 + n4 + n5 + n6)
    summary = (
        f"{verdict.upper()} - {rubric.total}/30 "
        f"(claim_support={claim_support}, overclaim={overclaim})"
        + (f"; {len(blockers)} blocker(s)" if blockers else "")
    )
    return ScorecardResult(
        rubric=rubric, claim_support=claim_support, overclaim=overclaim,
        verdict=verdict, blockers=blockers, notes=notes, summary=summary,
    )


def _collect_blockers(
    rubric: RubricScore, claim_support: ClaimSupport, overclaim: OverclaimLevel
) -> tuple[str, ...]:
    out: list[str] = []
    if rubric.total < ACCEPT_TOTAL_FLOOR:
        out.append(f"total={rubric.total} < accept floor {ACCEPT_TOTAL_FLOOR}")
    if claim_support != "supported":
        out.append(f"claim_support={claim_support}")
    if overclaim != "none":
        out.append(f"overclaim={overclaim}")
    return tuple(out)
