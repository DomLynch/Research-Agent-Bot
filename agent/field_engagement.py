"""Deterministic field-framework engagement primitives.

Phase 3 of the WORLDCLASS rapamycin sprint. Stdlib-only, no LLM, no raw
paper shortcut. Given normalized receipts + background references, emits
structured FrameworkEngagement records that say which named field
frameworks (Mannick, Lamming, Kennedy, Kaeberlein, Lopez-Otin) the
corpus supports / challenges / extends / cannot evaluate.

Hard rule: LLM PROPOSES, CODE DISPOSES. The engagement label is derived
from corpus signals (effect_direction, outcome_class, citation tokens),
never from prose interpretation.

Engagement labels:
  - support      — corpus evidence aligned with framework's primary claim.
  - challenge    — corpus evidence contradicts framework's primary claim.
  - extends      — corpus evidence supports + adds adjacent-domain finding.
  - insufficient — no matching evidence in corpus or background refs.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "EngagementStatus",
    "Framework",
    "FrameworkEngagement",
    "FIELD_FRAMEWORK_REGISTRY",
    "evaluate_engagement",
]

EngagementStatus = Literal["support", "challenge", "extends", "insufficient"]
_VALID_STATUSES: frozenset[str] = frozenset(("support", "challenge", "extends", "insufficient"))

# Effect-direction values treated as "supportive" of a framework prediction.
_POSITIVE_DIRECTIONS: frozenset[str] = frozenset(("positive", "supports", "increase"))
# Effect-direction values treated as "challenging" of a framework prediction.
_NEGATIVE_DIRECTIONS: frozenset[str] = frozenset(("null", "negative", "contradicts", "decrease"))


@dataclass(frozen=True, slots=True)
class Framework:
    """Registry record for one named field framework.

    primary_domains  — outcome classes the framework's core claim addresses.
    adjacent_domains — outcome classes that, if also matched, mark "extends".
    anchor_authors   — author tokens (case-insensitive) used to find evidence
                       in receipts/background refs.
    """

    name: str
    primary_claim: str
    primary_domains: tuple[str, ...]
    adjacent_domains: tuple[str, ...]
    anchor_authors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FrameworkEngagement:
    """One framework's engagement with the corpus."""

    framework_name: str
    status: EngagementStatus
    matched_receipts: tuple[str, ...] = ()
    matched_background_refs: tuple[str, ...] = ()
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"invalid status {self.status!r}; must be one of {sorted(_VALID_STATUSES)}"
            )
        if not self.framework_name:
            raise ValueError("framework_name must be non-empty")


# Established field frameworks. Domains use the same outcome-class
# vocabulary the corpus uses (immune, cardiometabolic, lifespan, etc.).
FIELD_FRAMEWORK_REGISTRY: tuple[Framework, ...] = (
    Framework(
        name="Mannick",
        primary_claim="Low-dose intermittent rapalogs improve immune aging in older adults.",
        primary_domains=("immune", "infection_rate", "vaccine_response"),
        adjacent_domains=("cardiometabolic",),
        anchor_authors=("mannick",),
    ),
    Framework(
        name="Lamming",
        primary_claim="mTORC2 disruption is the off-target tax of chronic rapamycin dosing.",
        primary_domains=("mtorc2", "cardiometabolic", "glycemic"),
        adjacent_domains=("immune",),
        anchor_authors=("lamming",),
    ),
    Framework(
        name="Kennedy",
        primary_claim="Composite endpoints are required to detect geroprotective benefit.",
        primary_domains=("composite", "geroscience"),
        adjacent_domains=("immune", "cardiometabolic", "physical_function"),
        anchor_authors=("kennedy",),
    ),
    Framework(
        name="Kaeberlein",
        primary_claim="Companion-animal evidence is the cleanest pre-human translation.",
        primary_domains=("companion_animal", "dog", "frailty"),
        adjacent_domains=("lifespan",),
        anchor_authors=("kaeberlein", "urfer", "creevy"),
    ),
    Framework(
        name="Lopez-Otin",
        primary_claim="Hallmarks of aging integrate rapamycin into a multi-pathway target landscape.",
        primary_domains=("hallmarks", "senescence", "autophagy", "genomic_instability"),
        adjacent_domains=("lifespan", "immune", "cardiometabolic"),
        anchor_authors=("lopez-otin", "lópez-otín", "lopez_otin"),
    ),
)


def _author_tokens(record: dict) -> tuple[str, ...]:
    """Extract candidate author tokens from a receipt or background ref dict.

    Looks at: 'authors' (string or list), 'citation_token' (e.g. "Mannick 2014"),
    'study_id', 'receipt_id'. Returns lowercase tokens for matching."""
    tokens: list[str] = []
    authors = record.get("authors")
    if isinstance(authors, str):
        tokens.append(authors)
    elif isinstance(authors, (list, tuple)):
        tokens.extend(str(a) for a in authors)
    for key in ("citation_token", "study_id", "receipt_id"):
        value = record.get(key)
        if isinstance(value, str):
            tokens.append(value)
    return tuple(t.lower() for t in tokens)


def _matches_framework(record: dict, framework: Framework) -> bool:
    record_tokens = " ".join(_author_tokens(record))
    return any(anchor in record_tokens for anchor in framework.anchor_authors)


def _record_id(record: dict) -> str:
    for key in ("receipt_id", "citation_token", "study_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return "<unidentified>"


def _classify_evidence(records: Iterable[dict], framework: Framework) -> tuple[bool, bool, bool]:
    """Classify matching evidence into (has_primary_positive, has_primary_negative, has_adjacent).

    Looks at outcome_class + effect_direction on each matching record.
    """
    has_positive = False
    has_negative = False
    has_adjacent = False
    for record in records:
        if not _matches_framework(record, framework):
            continue
        outcome = str(record.get("outcome_class", "")).lower()
        direction = str(record.get("effect_direction", "")).lower()
        in_primary = outcome in framework.primary_domains
        in_adjacent = outcome in framework.adjacent_domains
        if in_primary and direction in _POSITIVE_DIRECTIONS:
            has_positive = True
        elif in_primary and direction in _NEGATIVE_DIRECTIONS:
            has_negative = True
        elif in_adjacent:
            has_adjacent = True
    return has_positive, has_negative, has_adjacent


def _label_engagement(
    has_positive: bool,
    has_negative: bool,
    has_adjacent: bool,
    has_any_match: bool,
) -> EngagementStatus:
    if not has_any_match:
        return "insufficient"
    if has_positive and has_adjacent:
        return "extends"
    if has_positive:
        return "support"
    if has_negative:
        return "challenge"
    return "insufficient"


def _build_rationale(
    framework: Framework,
    matched_receipts: Sequence[str],
    matched_refs: Sequence[str],
    status: EngagementStatus,
) -> str:
    base = f"{framework.name} (primary domains: {', '.join(framework.primary_domains)})"
    counts = (
        f"{len(matched_receipts)} receipt(s), {len(matched_refs)} background ref(s)"
    )
    return f"{base}; status={status} based on {counts}."


def evaluate_engagement(
    receipts: Sequence[dict],
    background_refs: Sequence[dict] = (),
    *,
    frameworks: Sequence[Framework] | None = None,
) -> list[FrameworkEngagement]:
    """Evaluate corpus engagement with each framework. Returns one
    FrameworkEngagement per framework. Fails closed (status="insufficient")
    when no source/citation support is present. Never invents claims."""
    frameworks = tuple(frameworks) if frameworks is not None else FIELD_FRAMEWORK_REGISTRY
    results: list[FrameworkEngagement] = []
    for framework in frameworks:
        matched_receipts = tuple(
            _record_id(r) for r in receipts if _matches_framework(r, framework)
        )
        matched_refs = tuple(
            _record_id(r) for r in background_refs if _matches_framework(r, framework)
        )
        has_any_match = bool(matched_receipts or matched_refs)
        # Receipts drive the support/challenge call; background refs alone
        # are not enough to claim support — they only establish presence.
        has_pos, has_neg, has_adj = _classify_evidence(receipts, framework)
        status = _label_engagement(has_pos, has_neg, has_adj, has_any_match)
        # Background-ref-only matches downgrade to "insufficient" because
        # background refs lack outcome_class/effect_direction signals.
        if has_any_match and not (has_pos or has_neg or has_adj):
            status = "insufficient"
        rationale = _build_rationale(framework, matched_receipts, matched_refs, status)
        results.append(FrameworkEngagement(
            framework_name=framework.name,
            status=status,
            matched_receipts=matched_receipts,
            matched_background_refs=matched_refs,
            rationale=rationale,
        ))
    return results
