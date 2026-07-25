"""Universal evidence-lane engine.

Reviewer feedback 2026-05-14: every source should map to one of six
canonical evidence lanes so the manuscript can never silently use
animal/preclinical evidence as human clinical proof — and so reviewers
can read each subsection knowing what lane the citations come from.

The six lanes are universal across any topic (biomedical, climate,
materials, economics, social science). For non-biomedical topics, the
`human_*` lanes still apply when the "subjects" are humans
(observational social-science data, field studies on participants);
the `animal_preclinical` lane generalises to "model-system" evidence.

This module is the single source of truth for lane derivation. Both
the runtime sidecar generator and the journal-surface gate read from
here.
"""
from __future__ import annotations

import re
from typing import Any, Final

from agent.journal_surface_gate import is_animal_paper
from agent.text_signals import HUMAN_TRIAL_SIGNAL_RE

# Six canonical lanes, ordered by clinical / evidentiary strength.
# Lower index = stronger direct-clinical claim weight.
LANE_TOKENS: Final[tuple[str, ...]] = (
    "human_rct",
    "human_observational",
    "human_mechanistic",
    "review_meta_analysis",
    "animal_preclinical",
    "background_only",
)

LANE_DISPLAY: Final[dict[str, str]] = {
    "human_rct": "Human randomised controlled trial",
    "human_observational": "Human observational study",
    "human_mechanistic": "Human mechanistic / biomarker study",
    "review_meta_analysis": "Review or meta-analysis",
    "animal_preclinical": "Animal / preclinical evidence",
    "background_only": "Background / methodological reference",
}

_HUMAN_POPULATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:humans?|people|adults|men|women|human\s+(?:patients?|participants?|subjects?))\b",
    re.IGNORECASE,
)
_CLINICAL_TRIAL_IDENTITY_RE: Final[re.Pattern[str]] = re.compile(
    r"\brandomi[sz]ed(?:\s+controlled)?\s+clinical\s+trial\b",
    re.IGNORECASE,
)


def derive_lane(
    *,
    evidence_tier: str | None,
    directness: str | None,
    title: str | None = None,
    venue: str | None = None,
    population: str | None = None,
    source_excerpt: str | None = None,
) -> str:
    """Map a receipt's (tier, directness, source-text) triple to one
    of the six canonical lanes. Universal — no per-topic table.

    Decision rules (ordered, first-match wins). Universal — based on
    the canonical evidence-tier taxonomy used across project corpora
    (A1=RCT, A2=strong obs., B1=review/meta, B2=weaker obs., C=preclinical):
      1. directness == "review" OR evidence_tier == "B1" → review_meta_analysis
      2. A1 with human source identity → human_rct
      3. explicit non-human identity or animal-only excerpt → animal_preclinical
      4. directness == "mechanistic" → human_mechanistic
      5. evidence_tier in ("A2", "B2") → human_observational
      6. evidence_tier == "C" → animal_preclinical (preclinical tier code)
      7. fallback → background_only
    """
    # source_excerpt (the receipt's claim-sentence excerpts) is included so
    # species named only in the body text — "in male arctic foxes", "broiler
    # chickens" — flip the lane even when the title is generic.
    tier = (evidence_tier or "").upper()
    direct = (directness or "").lower()
    identity = " ".join(s for s in (title, venue, population) if s)
    animal_identity = is_animal_paper(identity)
    animal_excerpt = is_animal_paper(source_excerpt)
    human_population = bool(_HUMAN_POPULATION_RE.search(identity))
    human_signal = human_population and bool(
        HUMAN_TRIAL_SIGNAL_RE.search(identity)
        or _CLINICAL_TRIAL_IDENTITY_RE.search(identity)
    )
    if direct == "review" or tier == "B1":
        return "review_meta_analysis"
    # Human trial papers routinely mention mouse work in their background.
    # Strong human-study metadata wins unless the source identity itself is
    # explicitly non-human; incidental excerpt text must not relabel the paper.
    if tier == "A1" and not animal_identity and (not animal_excerpt or human_signal):
        return "human_rct"
    if animal_identity or (animal_excerpt and not human_signal):
        return "animal_preclinical"
    if direct == "mechanistic":
        return "human_mechanistic"
    if tier in ("A2", "B2"):
        return "human_observational"
    if tier == "C":
        return "animal_preclinical"
    return "background_only"


def lane_qualifier_phrases_for(lane: str) -> tuple[str, ...]:
    """Return the set of academic phrasings that, when found in the
    same paragraph as a citation from this lane, satisfy the lane-label
    requirement. Used by the journal-surface gate's evidence-lane
    check. Universal — no topic-specific tokens."""
    if lane == "animal_preclinical":
        # Slice 26 (2026-05-15): added the everyday-prose terms researchers
        # actually use in body text ("mice", "mouse", "rat", "rats", "in
        # vitro", "cell line"). Senolytics audit surfaced that the writer
        # routinely writes "aged mice" or "in cultured cells" rather than
        # the formal "rodent / murine / in vivo" — so the qualifier check
        # missed legitimate lane-labelled prose. Caller must use word-
        # boundary matching to avoid e.g. "rat" matching "iterate".
        return (
            "animal", "preclinical", "rodent", "murine", "in vivo",
            "model organism", "veterinary", "non-human",
            "equine", "equid", "primate", "macaque", "horse",
            "swine", "porcine", "canine", "ovine",
            # Everyday-prose terms (Slice 26 additions):
            "mouse", "mice", "rat", "rats",
            "dog", "cat", "pig",  # everyday counterparts to canine/feline/porcine
            "in vitro", "cell line",
            "transgenic", "knockout", "knock-out", "wild-type",
        )
    if lane == "human_rct":
        return ("randomised", "randomized", "rct", "clinical trial")
    if lane == "human_observational":
        return ("observational", "cohort", "cross-sectional", "registry")
    if lane == "human_mechanistic":
        return ("mechanistic", "biomarker", "in vitro", "ex vivo")
    if lane == "review_meta_analysis":
        return ("review", "meta-analysis", "systematic", "umbrella")
    return ()


def build_lane_map(receipts: Any) -> dict[str, str]:
    """Build {citation_token: lane_token} from a receipts iterable.
    Each receipt must expose attributes/keys: citation_token (or
    body_citation), evidence_tier, directness, source_title, source_venue,
    population_summary. Falls back gracefully when fields are missing.
    Universal — works for any receipt shape that has these fields."""
    out: dict[str, str] = {}
    for r in receipts:
        cite = _get(r, "citation_token") or _get(r, "body_citation")
        if not cite:
            continue
        out[str(cite)] = derive_receipt_lane(r)
    return out


def derive_receipt_lane(receipt: Any) -> str:
    return derive_lane(
        evidence_tier=_get(receipt, "evidence_tier"),
        directness=_get(receipt, "directness"),
        title=_get(receipt, "source_title"),
        venue=_get(receipt, "source_venue"),
        population=_get(receipt, "population_summary"),
        source_excerpt=_get(receipt, "thesis_text"),
    )


def effective_directness(receipt: Any) -> str:
    """Prevent model-system evidence from counting as direct human evidence."""
    directness = str(_get(receipt, "directness") or "indirect").lower()
    return "indirect" if directness == "direct" and derive_receipt_lane(receipt) == "animal_preclinical" else directness


def _get(receipt: Any, field: str) -> str | None:
    """Universal attr-or-key getter so this works for both
    ReceiptSummary dataclasses and dict receipts (manifest serialised
    form)."""
    if hasattr(receipt, field):
        return getattr(receipt, field, None)
    if isinstance(receipt, dict):
        return receipt.get(field)
    return None
