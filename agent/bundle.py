"""Deterministic role / tier / design / directness classifier.

Pure functions. No LLM. Same input -> same output. The classifier is the
single typed contract that prevents the LLM from contradicting metadata
in compose.py and beyond.

CLASSIFICATION TRUTH TABLE
==========================

Step 1 - role  (the most load-bearing decision)
| Signal                                                 | role                  |
|--------------------------------------------------------|-----------------------|
| source=clinicaltrials AND has_results=True             | published_results     |
| source=clinicaltrials AND has_results=False            | registered_pending    |
| title or abstract has REVIEW marker                    | review                |
| abstract has PROTOCOL marker but no REPORTED_OUTCOME   | published_protocol    |
| abstract has REPORTED_OUTCOME (effect, p, CI, %, ...)  | published_results     |
| abstract has only MECHANISTIC markers                  | mechanistic           |
| anything else                                          | mechanistic (default) |

Step 2 - design  (derived from role + abstract markers)
| role + signal                            | design          |
|------------------------------------------|-----------------|
| published_results + RANDOMIZED marker    | rct             |
| published_results without randomized     | observational   |
| review + META_ANALYSIS marker            | meta_analysis   |
| review (other)                           | review          |
| published_protocol                       | protocol        |
| registered_pending                       | registry        |
| mechanistic                              | mechanistic     |

Step 3 - tier   (evidence quality, A1 best)
| condition                                                | tier |
|----------------------------------------------------------|------|
| design in {rct, meta_analysis} AND venue is high-impact  | A1   |
| design in {rct, meta_analysis}                           | A2   |
| role=published_results, design=observational             | A2   |
| role=review                                              | A2   |
| role in {published_protocol, registered_pending}         | B    |
| role=mechanistic                                         | C    |

Step 4 - direct (binary, defaults True; degraded by mismatch with domain)
| condition                                                       | direct |
|-----------------------------------------------------------------|--------|
| ANIMAL or CELL marker AND domain looks human-focused            | False  |
| PEDIATRIC marker AND domain mentions adult/older                | False  |
| otherwise                                                       | True   |

Step 5 - strict (whether the item meets criteria's strict-eligibility bar)
| condition                                                       | strict |
|-----------------------------------------------------------------|--------|
| direct=False                                                    | False  |
| year present AND year >= criteria_min_year (if specified)       | True   |
| no year filter or no year info                                  | True   |

If the truth table changes, update this docstring AND the per-rule constant
below in lockstep. Tests in test_bundle.py drive every row.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from agent.types import Design, EvidenceItem, Role, Source, Tier

# --- Marker dictionaries (lowercase substring matches against abstract+title) ---

_REVIEW = (
    "systematic review",
    "meta-analysis",
    "meta analysis",
    "umbrella review",
    "narrative review",
    "scoping review",
    "literature review",
)
_META_ANALYSIS = ("meta-analysis", "meta analysis")
_PROTOCOL = (
    "study protocol",
    "trial protocol",
    "is a protocol",
    "rationale and design",
    "study design and rationale",
    "design of a randomized",
    "design of a randomised",
    "design of an open-label",
)
# Patterns use word boundaries (\b) so "Mice were treated" matches as well
# as "transgenic mice." String containment (" mice ") was too brittle —
# missed sentence-initial and post-punctuation cases.
_RANDOMIZED_RE = re.compile(
    r"\b(randomi[sz]ed|rct|double[-\s]blind|placebo[-\s]controlled)\b",
    re.IGNORECASE,
)
# Numeric outcome regex: e.g. "p = 0.03", "95% CI", "HR 0.85", "reduced by 12%".
_REPORTED_OUTCOME_RE = re.compile(
    r"\b(p\s*[=<>]\s*0\.\d+|95%\s*ci|hazard ratio|odds ratio|risk ratio|"
    r"\bhr\s*=?\s*\d|\bor\s*=?\s*\d|\brr\s*=?\s*\d|"
    r"reduced by \d|increased by \d|\d+\s*%|mean (difference|change)|"
    r"\bn\s*=\s*\d{2,})",
    re.IGNORECASE,
)
_MECHANISTIC_RE = re.compile(
    r"\b(in[-\s]vitro|ex\s+vivo|cell\s+(line|culture)|transgenic\s+mice|"
    r"knock(out|-out)\s+mice|wild[-\s]type\s+mice|rat\s+model|mouse\s+model|"
    r"mtor\s+signaling|molecular\s+mechanism)\b",
    re.IGNORECASE,
)
_ANIMAL_RE = re.compile(
    r"\b(mice|mouse|rats?|murine|canine|porcine|bovine|zebrafish|drosophila|"
    r"c\.\s*elegans)\b",
    re.IGNORECASE,
)
_CELL_RE = re.compile(
    r"\b(in[-\s]vitro|cell\s+(line|culture)|primary\s+cells|ex\s+vivo)\b",
    re.IGNORECASE,
)
_PEDIATRIC_RE = re.compile(
    r"\b(pediatric|paediatric|children|adolescen[ct]|infants?|neonatal)\b",
    re.IGNORECASE,
)
# High-impact venues for tier A1 promotion. Conservative seed list; expand
# only when a fixture proves the omission is hurting tier accuracy.
_HIGH_IMPACT_VENUES = (
    "new england journal of medicine",
    "lancet",
    "jama",
    "bmj",
    "nature medicine",
    "cell",
    "nature",
    "science",
    "annals of internal medicine",
)

_HUMAN_DOMAIN_MARKERS = (
    "human",
    "longevity",
    "aging",
    "ageing",
    "older adult",
    "adult",
    "patient",
    "clinical",
)
_ADULT_DOMAIN_MARKERS = ("adult", "older", "elderly", "geriatric")


# --- Public entry point ----------------------------------------------------


def bundle(
    sources: list[Source],
    abstracts: Mapping[int, str],
    *,
    domain: str = "",
    criteria_min_year: int | None = None,
    raw_signals: Mapping[int, Mapping[str, object]] | None = None,
) -> list[EvidenceItem]:
    """Map (Source, abstract) -> EvidenceItem with role/tier/design/direct/strict.

    `raw_signals` is the per-ref `RawHit.raw` dict from the adapter (e.g.
    clinicaltrials passes `has_results`). Pure function; deterministic.
    """
    items: list[EvidenceItem] = []
    domain_lower = (domain or "").lower()
    signals = raw_signals or {}
    for src in sources:
        abstract = abstracts.get(src.ref, "")
        sig = signals.get(src.ref, {}) or {}
        role = _classify_role(src, abstract, sig)
        design = _classify_design(role, abstract)
        tier = _classify_tier(role, design, src.venue)
        direct = _is_direct(abstract, domain_lower)
        strict = _is_strict(direct, src.year, criteria_min_year)
        items.append(
            EvidenceItem(
                source=src,
                abstract=abstract,
                design=design,
                role=role,
                tier=tier,
                direct=direct,
                strict=strict,
            )
        )
    return items


# --- Step 1: role ----------------------------------------------------------


def _classify_role(src: Source, abstract: str, sig: Mapping[str, object]) -> Role:
    haystack = f"{src.title} {abstract}".lower()
    if src.source == "clinicaltrials":
        return "published_results" if sig.get("has_results") else "registered_pending"
    if any(token in haystack for token in _REVIEW):
        return "review"
    has_protocol = any(token in haystack for token in _PROTOCOL)
    has_outcome = bool(_REPORTED_OUTCOME_RE.search(abstract))
    if has_protocol and not has_outcome:
        return "published_protocol"
    if has_outcome:
        return "published_results"
    if _MECHANISTIC_RE.search(haystack):
        return "mechanistic"
    return "mechanistic"


# --- Step 2: design --------------------------------------------------------


def _classify_design(role: Role, abstract: str) -> Design:
    haystack = abstract.lower()
    if role == "published_results":
        return "rct" if _RANDOMIZED_RE.search(haystack) else "observational"
    if role == "review":
        return "meta_analysis" if any(t in haystack for t in _META_ANALYSIS) else "review"
    if role == "published_protocol":
        return "protocol"
    if role == "registered_pending":
        return "registry"
    if role == "mechanistic":
        return "mechanistic"
    return "other"


# --- Step 3: tier ----------------------------------------------------------


def _classify_tier(role: Role, design: Design, venue: str | None) -> Tier:
    is_high_impact = bool(venue) and any(
        marker in venue.lower() for marker in _HIGH_IMPACT_VENUES
    )
    if design in {"rct", "meta_analysis"}:
        return "A1" if is_high_impact else "A2"
    if role == "published_results":
        return "A2"
    if role == "review":
        return "A2"
    if role in {"published_protocol", "registered_pending"}:
        return "B"
    return "C"


# --- Step 4: direct --------------------------------------------------------


def _is_direct(abstract: str, domain: str) -> bool:
    domain_human = any(marker in domain for marker in _HUMAN_DOMAIN_MARKERS)
    domain_adult = any(marker in domain for marker in _ADULT_DOMAIN_MARKERS)
    if domain_human and (_ANIMAL_RE.search(abstract) or _CELL_RE.search(abstract)):
        return False
    if domain_adult and _PEDIATRIC_RE.search(abstract):
        return False
    return True


# --- Step 5: strict --------------------------------------------------------


def _is_strict(direct: bool, year: int | None, min_year: int | None) -> bool:
    if not direct:
        return False
    if min_year is not None and year is not None and year < min_year:
        return False
    return True
