"""Post-classifier remap for known endpoint → outcome_class miscategorizations.

2026-05-09 peer-review fix (Bug 2). The live runner's
`_outcome_class_for_endpoint` (in `scripts/run_v06_synthesis.py`) consults
domain vocab files (in `scripts/vocab/`) for endpoint → outcome_class
mappings. The peer-review panel flagged that the rapamycin vocab maps:

    "emotional well-being": "cognitive"   # WRONG — QoL, not cognitive

This module provides a deterministic post-classifier remap that the
runner can apply *after* the vocab/heuristic pass, fixing known mis-
categorizations without modifying vocab files (which are owned by a
separate lane).

Usage (intended wiring point):

    from agent.outcome_class_remap import remap_outcome_class

    raw = _outcome_class_for_endpoint(endpoint)         # existing call
    final = remap_outcome_class(endpoint, raw)          # new line

The remap is conservative: it only rewrites pairs that are demonstrably
wrong per the published literature (e.g. SF-36 emotional well-being is
the canonical QoL/healthspan endpoint, not a cognitive endpoint). It
never invents new outcome classes or routes endpoints away from a
correct class.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

__all__ = [
    "ENDPOINT_REMAP",
    "ENDPOINT_PATTERNS",
    "BIOMEDICAL_OTHER_OUTCOME_RULES",
    "remap_outcome_class",
    "refine_other_outcome_class",
    "is_known_misclassification",
]

# Direct endpoint → corrected outcome_class.
# Keys are the canonical endpoint labels as they appear in vocab/{topic}.py.
# Values are the corrected outcome class (must match OutcomeClass Literal).
ENDPOINT_REMAP: Mapping[str, str] = {
    # PEARL trial QoL endpoints — vocab routes the first to "cognitive"
    # (wrong) and the others to "frailty" (debatable). All four belong
    # under healthspan_qol.
    "emotional well-being": "healthspan_qol",
    "psychological well-being": "healthspan_qol",
    "general health": "healthspan_qol",
    "self-reported health": "healthspan_qol",
    "self-reported pain": "healthspan_qol",
    "pain score": "healthspan_qol",
    "quality of life": "healthspan_qol",
    "qol": "healthspan_qol",
    "sf-36": "healthspan_qol",
    "sf36": "healthspan_qol",
    "vitality": "healthspan_qol",
}

# Regex patterns for fuzzy matching (case-insensitive, word-boundary aware).
# Used when the endpoint string doesn't match an ENDPOINT_REMAP key exactly
# but contains a recognisable QoL phrase. Order: more-specific first.
ENDPOINT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bemotional\s+well[-\s]?being\b", re.I), "healthspan_qol"),
    (re.compile(r"\bpsychological\s+well[-\s]?being\b", re.I), "healthspan_qol"),
    (re.compile(r"\bself[-\s]?reported\s+(?:pain|health|well[-\s]?being)\b", re.I),
     "healthspan_qol"),
    (re.compile(r"\bquality\s+of\s+life\b", re.I), "healthspan_qol"),
    (re.compile(r"\bsf[-\s]?36\b", re.I), "healthspan_qol"),
    (re.compile(r"\bgeneral\s+health\b", re.I), "healthspan_qol"),
    (re.compile(r"\bvitality\s+scale\b", re.I), "healthspan_qol"),
    (re.compile(r"\bpatient[-\s]?reported\s+outcome\b", re.I), "healthspan_qol"),
)

BIOMEDICAL_OTHER_OUTCOME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("skeletal_fracture_bone", ("bone", "fracture", "osteoporosis", "calcium", "skeletal")),
    ("mortality_survival", ("mortality", "survival", "death", "cause_specific_death")),
    ("deficiency_prevalence", ("deficiency", "insufficiency", "prevalence", "serum", "status")),
    ("immune_inflammation", ("inflammation", "immune", "sepsis", "infection", "cytokine")),
    ("dosing_pharmacokinetics", ("dose", "dosing", "supplementation", "pharmacokinetic", "cholecalciferol", "calcifediol")),
    ("safety_comorbidity", ("safety", "adverse", "kidney", "chronic", "comorbidity")),
)


def is_known_misclassification(endpoint: str, current_class: str) -> bool:
    """True if `endpoint` is in the corrections map and `current_class`
    differs from the corrected class. Useful for audit logging."""
    target = _lookup(endpoint)
    return target is not None and target != current_class


def remap_outcome_class(endpoint: str, current_class: str) -> str:
    """Return the corrected outcome class for `endpoint`, or `current_class`
    unchanged if no correction applies.

    Lookup order:
      1. Exact match in ENDPOINT_REMAP (lowercased + whitespace-collapsed).
      2. First-matching pattern in ENDPOINT_PATTERNS.
      3. No match — return current_class verbatim.

    The function is deterministic and side-effect free; it's safe to call
    on every endpoint in the pipeline."""
    target = _lookup(endpoint)
    if target is not None:
        return target
    return current_class


def refine_other_outcome_class(receipt: object, current_class: str) -> str:
    """Split biomedical `other` into more useful sub-outcomes.

    This is a conservative post-classifier fallback: it only rewrites
    the junk-drawer `other` class and uses receipt metadata already
    available before manifest/results rendering. Domain packs can later
    replace the rule tuple without changing the receipt compiler.
    """
    if current_class != "other":
        return current_class
    text = " ".join(str(getattr(receipt, name, "") or "") for name in (
        "receipt_id", "source_title", "population_summary",
    )).lower()
    for label, needles in BIOMEDICAL_OTHER_OUTCOME_RULES:
        if any(needle in text for needle in needles):
            return label
    return "contextual_other"


def _lookup(endpoint: str) -> str | None:
    """Internal lookup; returns the corrected class or None."""
    if not isinstance(endpoint, str):
        return None
    normalized = " ".join(endpoint.strip().lower().split())
    if not normalized:
        return None
    if normalized in ENDPOINT_REMAP:
        return ENDPOINT_REMAP[normalized]
    for pattern, target in ENDPOINT_PATTERNS:
        if pattern.search(normalized):
            return target
    return None
