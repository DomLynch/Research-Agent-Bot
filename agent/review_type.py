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
}

DEFAULT_REVIEW_TYPE: Final[str] = "prisma_scr_scoping_synthesis"


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
