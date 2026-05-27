"""Post-classifier outcome-class cleanup."""
from __future__ import annotations

import re
from collections.abc import Mapping

__all__ = ["ENDPOINT_REMAP", "ENDPOINT_PATTERNS", "BIOMEDICAL_OTHER_OUTCOME_RULES", "OUTCOME_VOCAB", "outcome_display", "outcome_key", "remap_outcome_class", "refine_other_outcome_class", "is_known_misclassification"]

# PEARL trial QoL endpoints belong under healthspan_qol.
ENDPOINT_REMAP: Mapping[str, str] = dict.fromkeys((
    "emotional well-being", "psychological well-being", "general health", "self-reported health", "self-reported pain",
    "pain score", "quality of life", "qol", "sf-36", "sf36", "vitality",
), "healthspan_qol")

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

OUTCOME_VOCAB: Mapping[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "cardiometabolic": ("Cardiometabolic", (), ()),
    "cognitive": ("Cognitive", (), ()),
    "contextual_other": ("Contextual Other", (), ()),
    "deficiency_prevalence": ("Deficiency Prevalence", ("deficiency prevalence",), ("deficiency", "insufficiency", "prevalence", "serum", "status")),
    "dosing_pharmacokinetics": ("Dosing and Pharmacokinetics", ("dosing pharmacokinetics",), ("dose", "dosing", "supplementation", "pharmacokinetic", "cholecalciferol", "calcifediol")),
    "frailty": ("Frailty", (), ()),
    "healthspan_qol": ("Healthspan and Quality of Life", ("healthspan qol", "quality of life"), ()),
    "immune": ("Immune", (), ()),
    "immune_inflammation": ("Immune and Inflammation", ("immune inflammation",), ("inflammation", "immune", "sepsis", "infection", "cytokine")),
    "longevity": ("Longevity", (), ()),
    "mechanism": ("Mechanism", (), ()),
    "mortality_survival": ("Mortality and Survival", ("mortality survival",), ("mortality", "survival", "death", "cause_specific_death")),
    "muscle_function": ("Muscle Function", (), ()),
    "oncology": ("Oncology", (), ()),
    "ophthalmologic": ("Ophthalmologic", (), ()),
    "other": ("Other", (), ()),
    "safety": ("Safety", (), ()),
    "safety_comorbidity": ("Safety and Comorbidity", ("safety comorbidity",), ("safety", "adverse", "kidney", "chronic", "comorbidity")),
    "skeletal_fracture_bone": ("Skeletal, Fracture, and Bone", ("skeletal fracture bone", "bone fracture"), ("bone", "fracture", "osteoporosis", "calcium", "skeletal")),
}

BIOMEDICAL_OTHER_OUTCOME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (label, spec[2]) for label, spec in OUTCOME_VOCAB.items() if spec[2]
)


def _words_key(value: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", str(value).lower()) if w != "and"]
    while words and words[-1] in {"outcome", "outcomes", "endpoint", "endpoints"}:
        words.pop()
    return "_".join(words)


_OUTCOME_KEYS: Mapping[str, str] = {
    key: canon
    for canon, (display, aliases, _needles) in OUTCOME_VOCAB.items()
    for key in {_words_key(canon), _words_key(display), *(_words_key(a) for a in aliases)}
    if key
}


def outcome_key(label: str) -> str:
    """Canonical outcome id for a raw id, display label, or section heading."""
    key = _words_key(label)
    return _OUTCOME_KEYS.get(key, key)


def outcome_display(label: str) -> str:
    """Public display label for an outcome id or label."""
    canon = outcome_key(label)
    return OUTCOME_VOCAB.get(canon, (str(label).replace("_", " ").strip().title() or "Other", (), ()))[0]


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
    text = " ".join(str(getattr(receipt, name, "") or "") for name in ("receipt_id", "source_title", "population_summary")).lower()
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
