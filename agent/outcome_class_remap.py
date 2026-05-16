"""Post-classifier outcome-class cleanup."""
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
    target = _lookup(endpoint)
    return target is not None and target != current_class


def remap_outcome_class(endpoint: str, current_class: str) -> str:
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
