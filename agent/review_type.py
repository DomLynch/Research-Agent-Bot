"""Universal review-type selector and corpus-scope preflight."""
from __future__ import annotations

import re
from typing import Final

# Stable enum tokens used in topic_pack.toml + manifest.json.
# Display labels are journal-conventional academic phrasing.
REVIEW_TYPES: Final[dict[str, str]] = {
    "prisma_scr_scoping_synthesis": "PRISMA-ScR structured scoping synthesis",
    "structured_evidence_synthesis": "Structured evidence synthesis",
    "narrative_review": "Narrative review",
    "systematic_review": "Systematic review",
    "meta_analysis": "Systematic review and meta-analysis",
    "technical_survey": "Technical survey",
    "management_literature_review": "Management literature review",
    "evidence_map": "Evidence map",
    "evidence_brief": "Evidence brief",
    "thin_corpus_brief": "Thin-corpus evidence brief",
}
COMPACT_REVIEW_TYPES: Final[frozenset[str]] = frozenset({
    "thin_corpus_brief", "evidence_brief", "evidence_map",
})

DEFAULT_REVIEW_TYPE: Final[str] = "prisma_scr_scoping_synthesis"
# Slice 31 universal thresholds — no topic-specific values.
THIN_CORPUS_MIN_RECEIPTS: Final[int] = 10
THIN_CORPUS_MIN_TENSIONS: Final[int] = 1
THIN_CORPUS_MIN_PRIMARY_TIER: Final[int] = 3
BROAD_CORPUS_MAX_RECEIPTS: Final[int] = 500
BROAD_CORPUS_MAX_TENSIONS: Final[int] = 50_000
BROAD_CORPUS_MAX_OUTCOMES: Final[int] = 12


def corpus_sufficiency_verdict(n_receipts: int, n_tensions: int, n_primary_tier: int = -1) -> tuple[bool, tuple[str, ...]]:
    reasons = tuple(r for r in (
        f"n_receipts={n_receipts} < {THIN_CORPUS_MIN_RECEIPTS}" if n_receipts < THIN_CORPUS_MIN_RECEIPTS else "",
        f"n_tensions={n_tensions} < {THIN_CORPUS_MIN_TENSIONS}" if n_tensions < THIN_CORPUS_MIN_TENSIONS else "",
        f"n_primary_tier={n_primary_tier} < {THIN_CORPUS_MIN_PRIMARY_TIER} (insufficient primary-tier anchors)" if 0 <= n_primary_tier < THIN_CORPUS_MIN_PRIMARY_TIER else "",
    ) if r)
    return (not reasons, reasons)


def corpus_scope_verdict(n_receipts: int, n_tensions: int, n_outcome_classes: int = -1) -> tuple[bool, tuple[str, ...]]:
    reasons = tuple(r for r in (
        f"n_receipts={n_receipts} > {BROAD_CORPUS_MAX_RECEIPTS} (split topic or render evidence map)" if n_receipts > BROAD_CORPUS_MAX_RECEIPTS else "",
        f"n_tensions={n_tensions} > {BROAD_CORPUS_MAX_TENSIONS} (split topic or render evidence map)" if n_tensions > BROAD_CORPUS_MAX_TENSIONS else "",
        f"n_outcome_classes={n_outcome_classes} > {BROAD_CORPUS_MAX_OUTCOMES} (split topic or render evidence map)" if n_outcome_classes > BROAD_CORPUS_MAX_OUTCOMES else "",
    ) if r)
    return (not reasons, reasons)


def downshift_review_type_for_thin_corpus(
    declared: str | None, n_receipts: int, n_tensions: int,
    n_primary_tier: int = -1, n_outcome_classes: int = -1,
) -> str:
    if not corpus_scope_verdict(n_receipts, n_tensions, n_outcome_classes)[0]:
        return "evidence_map"
    sufficient, _ = corpus_sufficiency_verdict(n_receipts, n_tensions, n_primary_tier)
    if sufficient:
        return parse_review_type(declared)
    if n_receipts >= THIN_CORPUS_MIN_RECEIPTS and n_tensions >= THIN_CORPUS_MIN_TENSIONS:
        return "evidence_brief"
    return "thin_corpus_brief"


class ReviewTypeError(ValueError):
    """Raised when a topic pack declares an unknown review_type token."""


def parse_review_type(token: str | None) -> str:
    """Validate + normalise a review_type token. Empty/None → default.
    Unknown token raises so misconfigured topic packs fail fast at load
    time, not at gate time."""
    if token is None or not str(token).strip():
        return DEFAULT_REVIEW_TYPE
    norm = str(token).strip().lower().replace("-", "_").replace(" ", "_")
    if norm not in REVIEW_TYPES:
        raise ReviewTypeError(
            f"unknown review_type {token!r}; allowed: "
            f"{sorted(REVIEW_TYPES)}",
        )
    return norm


def display_label(token: str) -> str:
    """Return the journal-conventional display label for a stored
    token. Used in Abstract/Methods prose so the manuscript declares
    its category in standard academic language."""
    return REVIEW_TYPES.get(parse_review_type(token), token)


# --- Gate check: review-type self-claim overclaim ---------------------
# Slice 10 — when manifest declares a weaker review type, Abstract/
# Methods must not SELF-CLAIM a stronger methodology. Distinguishes
# self-claims ("we conducted a systematic review") from legitimate
# cited-evidence mentions ("we included systematic reviews"). Lives
# here (not in journal_surface_gate) because the semantics are
# review-type-specific.

REVIEW_TYPE_SELF_CLAIM_TERMS: Final[dict[str, tuple[str, ...]]] = {
    "prisma_scr_scoping_synthesis": (
        "systematic review", "meta-analysis", "meta analysis",
        "prospero", "prisma 2020",
    ),
    "structured_evidence_synthesis": (
        "systematic review", "meta-analysis", "meta analysis",
        "prospero", "prisma 2020", "prisma-scr",
    ),
    "narrative_review": (
        "systematic review", "scoping review", "meta-analysis",
        "meta analysis", "prospero", "prisma",
    ),
    "evidence_brief": (
        "systematic review", "scoping review", "meta-analysis",
        "meta analysis", "prospero", "prisma",
    ),
    "thin_corpus_brief": (
        "systematic review", "scoping review", "meta-analysis",
        "meta analysis", "prospero", "prisma",
    ),
    "evidence_map": (
        "systematic review", "scoping review", "meta-analysis",
        "meta analysis", "prospero", "prisma",
    ),
    "technical_survey": (
        "systematic review", "meta-analysis", "meta analysis", "prisma",
    ),
    "management_literature_review": (
        "systematic review", "meta-analysis",
    ),
    "systematic_review": (),
    "meta_analysis": (),
}

SELF_CLAIM_QUALIFIERS: Final[tuple[str, ...]] = (
    "we conducted", "we performed", "we undertook", "we report",
    "we present a", "we registered",
    "this is a", "this paper is", "this review is", "this synthesis is",
    "this study is", "this analysis is",
    "registered with prospero", "following prisma",
    "prisma-compliant", "prisma 2020 compliant",
    "our systematic review", "our meta-analysis", "our scoping review",
)


def _self_claim_proximity_window(
    text: str, qualifier: str, token: str, max_chars: int = 60,
) -> bool:
    """Return True if `qualifier` appears within `max_chars` of
    `token` in `text`. Distinguishes self-methodological claims
    (qualifier + token adjacent) from list-construction sentences
    (qualifier + token far apart in a multi-clause sentence)."""
    low = text.lower()
    q_idx = low.find(qualifier)
    if q_idx < 0:
        return False
    t_idx = low.find(token, q_idx)
    if t_idx < 0 or t_idx - q_idx - len(qualifier) > max_chars:
        return False
    return True


def review_type_overclaim_issue_messages(
    abstract_text: str, methods_text: str,
    declared_review_type: str | None,
) -> tuple[str, ...]:
    """Flag Abstract/Methods SELF-CLAIMS of a stronger methodology
    than the manifest's declared review_type. Universal — caller
    extracts the section bodies (gate uses _section_body)."""
    if not declared_review_type:
        return ()
    forbidden = REVIEW_TYPE_SELF_CLAIM_TERMS.get(declared_review_type, ())
    if not forbidden:
        return ()
    scoped = (abstract_text or "") + "\n" + (methods_text or "")
    out: list[str] = []
    seen: set[tuple[str, str]] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", scoped):
        for token in forbidden:
            if token not in sentence.lower():
                continue
            matched_qualifier = next(
                (q for q in SELF_CLAIM_QUALIFIERS
                 if _self_claim_proximity_window(sentence, q, token)),
                None,
            )
            if not matched_qualifier:
                continue
            key = (token, sentence[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                f"review-type overclaim (self-claim): manifest "
                f"declares {declared_review_type!r} but Abstract/"
                f"Methods sentence claims own methodology as "
                f"{token!r} (qualifier {matched_qualifier!r}): "
                f"{sentence[:160].strip()!r}",
            )
    return tuple(out)
