"""Single typed publication policy for all V3 lanes."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent.review_type import COMPACT_REVIEW_TYPES, parse_review_type


class PublicationSurface(StrEnum):
    RESEARCH_SYNTHESIS = "research_synthesis"
    INTERNAL_COMPACT = "internal_compact"


class CandidateState(StrEnum):
    READY_FOR_SYNTHESIS = "ready_for_synthesis"
    PUBLISHABLE = "publishable"
    INTERNAL_ALPHA = "internal_alpha"
    NEEDS_CORPUS = "needs_corpus"
    NEEDS_REVISION = "needs_revision"
    SUBMITTED_PENDING = "submitted_pending"
    OPERATIONAL_ERROR = "operational_error"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class CandidateThresholds:
    min_quant_claims: int
    min_receipts: int
    min_primary_tier: int
    min_direct_receipts: int

    def as_dict(self) -> dict[str, int]:
        return {
            "quant_claims": self.min_quant_claims,
            "receipts": self.min_receipts,
            "primary_tier": self.min_primary_tier,
            "direct_receipts": self.min_direct_receipts,
        }


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    n_quant_claims: int = 0
    n_receipts: int = 0
    n_primary_tier: int = 0
    n_direct_receipts: int = 0
    has_manifest: bool = True
    source_precision_ok: bool = True
    numeric_density_ok: bool = True


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate_id: str
    surface: PublicationSurface
    state: CandidateState
    blocker_code: str | None
    retryable: bool
    next_action: str

    @property
    def publishable(self) -> bool:
        return self.state is CandidateState.PUBLISHABLE

    @property
    def ready_for_synthesis(self) -> bool:
        return self.state is CandidateState.READY_FOR_SYNTHESIS


def publication_surface(review_type: str | None) -> PublicationSurface:
    normalized = str(review_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return PublicationSurface.RESEARCH_SYNTHESIS
    try:
        compact = parse_review_type(normalized) in COMPACT_REVIEW_TYPES
    except ValueError:
        compact = True
    return PublicationSurface.INTERNAL_COMPACT if compact else PublicationSurface.RESEARCH_SYNTHESIS


def source_fit_reasons(
    *,
    n_primary_tier: int,
    n_direct_receipts: int,
    thresholds: CandidateThresholds,
) -> list[str]:
    reasons = []
    if n_primary_tier < thresholds.min_primary_tier:
        reasons.append(
            f"n_primary_tier={n_primary_tier} < {thresholds.min_primary_tier} "
            "(insufficient primary-tier anchors)"
        )
    if n_direct_receipts < thresholds.min_direct_receipts:
        reasons.append(
            f"n_direct_receipts={n_direct_receipts} < {thresholds.min_direct_receipts} "
            "(insufficient direct source anchors)"
        )
    return reasons


def _decision(
    candidate_id: str,
    surface: PublicationSurface,
    state: CandidateState,
    blocker: str | None,
    retryable: bool,
    action: str,
) -> CandidateDecision:
    return CandidateDecision(candidate_id, surface, state, blocker, retryable, action)


def decide_candidate(
    candidate_id: str,
    *,
    review_type: str | None,
    evidence: CandidateEvidence,
    thresholds: CandidateThresholds,
) -> CandidateDecision:
    surface = publication_surface(review_type)
    if surface is PublicationSurface.INTERNAL_COMPACT:
        return _decision(
            candidate_id, surface, CandidateState.INTERNAL_ALPHA,
            "public_research_surface_compact_review", True, "expand_corpus",
        )
    checks = (
        (not evidence.has_manifest, "latest_run_missing_manifest"),
        (not evidence.numeric_density_ok, "prior_numeric_density_failed"),
        (evidence.n_quant_claims < thresholds.min_quant_claims, "quant_claims_below_floor"),
        (evidence.n_receipts < thresholds.min_receipts, "receipts_below_floor"),
        (evidence.n_primary_tier < thresholds.min_primary_tier, "primary_tier_below_floor"),
        (evidence.n_direct_receipts < thresholds.min_direct_receipts, "direct_receipts_below_floor"),
        (not evidence.source_precision_ok, "source_topic_precision_low"),
    )
    blocker = next((code for failed, code in checks if failed), None)
    return (
        _decision(candidate_id, surface, CandidateState.NEEDS_CORPUS, blocker, True, "repair_corpus")
        if blocker
        else _decision(candidate_id, surface, CandidateState.READY_FOR_SYNTHESIS, None, False, "synthesize")
    )


_EXACT_STATUS = {
    "eligible": (CandidateState.PUBLISHABLE, False, "submit"),
    "public_research_surface_ok": (CandidateState.PUBLISHABLE, False, "submit"),
    "published": (CandidateState.TERMINAL, False, "none"),
    "submitted_to_researka": (CandidateState.SUBMITTED_PENDING, True, "poll_decision"),
}
_PREFIX_STATUS = (
    (("cycle_already_running", "remote_dedupe_failed", "submission_failed", "submit_not_configured"), CandidateState.OPERATIONAL_ERROR, True, "retry_operation"),
    (("terminal_", "duplicate_", "retracted_", "researka_rejected_"), CandidateState.TERMINAL, False, "stop"),
    (("preflight_", "receipt_preflight_", "source_topic_precision_", "source_bundle_", "public_surface_direct_receipts_", "needs_corpus"), CandidateState.NEEDS_CORPUS, True, "repair_corpus"),
)


def decision_from_status(
    candidate_id: str,
    *,
    review_type: str | None,
    status: str,
) -> CandidateDecision:
    surface = publication_surface(review_type)
    normalized = str(status or "unknown").strip()
    exact = _EXACT_STATUS.get(normalized)
    if exact and normalized not in {"eligible", "public_research_surface_ok"}:
        state, retryable, action = exact
        return _decision(candidate_id, surface, state, None, retryable, action)
    for prefixes, state, retryable, action in _PREFIX_STATUS[:2]:
        if normalized.startswith(prefixes):
            return _decision(candidate_id, surface, state, normalized, retryable, action)
    if surface is PublicationSurface.INTERNAL_COMPACT:
        return _decision(
            candidate_id, surface, CandidateState.INTERNAL_ALPHA,
            "public_research_surface_compact_review", True, "expand_corpus",
        )
    if exact:
        state, retryable, action = exact
        return _decision(candidate_id, surface, state, None, retryable, action)
    corpus_prefixes, corpus_state, corpus_retryable, corpus_action = _PREFIX_STATUS[2]
    if normalized.startswith(corpus_prefixes):
        return _decision(
            candidate_id,
            surface,
            corpus_state,
            normalized,
            corpus_retryable,
            corpus_action,
        )
    return _decision(
        candidate_id, surface, CandidateState.NEEDS_REVISION, normalized,
        normalized != "unknown", "revise",
    )
