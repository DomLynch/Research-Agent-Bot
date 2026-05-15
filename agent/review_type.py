"""Universal review-type selector — names the manuscript category up
front so Methods, Abstract, and target-journal formatting can flow
from a single declared contract.

Reviewer feedback 2026-05-14: the manuscript must obey ONE review type
(systematic review, scoping review, narrative review, etc.) rather
than drift between framings. Without this, even strong prose looks
non-standard to journal editors.

Universal — no biomedical-specific tokens. Works for any field:
biomedical, climate, materials, economics, social science. The 7
canonical types match Cochrane / JBI / PRISMA-ScR / Greenhalgh
taxonomies.
"""
from __future__ import annotations

import re
from typing import Final

# Stable enum tokens used in topic_pack.toml + manifest.json.
# Display labels are journal-conventional academic phrasing.
REVIEW_TYPES: Final[dict[str, str]] = {
    "prisma_scr_scoping_synthesis":
        "PRISMA-ScR structured scoping synthesis",
    "structured_evidence_synthesis":
        "Structured evidence synthesis",
    "narrative_review":
        "Narrative review",
    "systematic_review":
        "Systematic review",
    "meta_analysis":
        "Systematic review and meta-analysis",
    "technical_survey":
        "Technical survey",
    "management_literature_review":
        "Management literature review",
    # Slice 31 (2026-05-15): thin-corpus product-type downshift. Used
    # universally when n_receipts<10 OR n_tensions=0 — signals to
    # downstream readers + the maturity ladder that the run produced
    # an evidence brief, not a full journal manuscript.
    "thin_corpus_brief":
        "Thin-corpus evidence brief",
}

DEFAULT_REVIEW_TYPE: Final[str] = "prisma_scr_scoping_synthesis"

# Slice 31 universal thresholds for thin-corpus downshift. Universal —
# no topic-specific values; any topic with corpus thinness below these
# downshifts to `thin_corpus_brief` regardless of declared review type.
THIN_CORPUS_MIN_RECEIPTS: Final[int] = 10
THIN_CORPUS_MIN_TENSIONS: Final[int] = 1


def downshift_review_type_for_thin_corpus(
    declared: str | None, n_receipts: int, n_tensions: int,
) -> str:
    """Return `thin_corpus_brief` when the run's corpus is too thin to
    support a full journal manuscript; otherwise return the parsed
    declared token. Universal — no topic-specific logic. Conditions
    track the reviewer's explicit guidance: n_receipts<10 OR
    n_tensions==0 means render an evidence note, not a manuscript."""
    if n_receipts < THIN_CORPUS_MIN_RECEIPTS or n_tensions < THIN_CORPUS_MIN_TENSIONS:
        return "thin_corpus_brief"
    return parse_review_type(declared)


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
