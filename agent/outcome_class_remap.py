"""Post-classifier outcome-class cleanup."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

__all__ = ["ENDPOINT_REMAP", "ENDPOINT_PATTERNS", "BIOMEDICAL_OTHER_OUTCOME_RULES", "OUTCOME_VOCAB", "outcome_display", "outcome_key", "unique_outcome_displays", "remap_outcome_class", "refine_other_outcome_class", "is_known_misclassification"]

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
    (re.compile(r"\b(?:inspiratory muscle|pulmonary function|lung function|vital capacity|minute ventilation|tidal volume|aerobic capacity|(?:maximal|maximum) oxygen uptake|ventilation threshold)\b", re.I), "contextual_other"),
)

SOURCE_TEXT_OUTCOME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:pregnan\w*|pre[-\s]?eclampsia|gestational\s+hypertension|"
            r"hypertensive\s+disorders?\s+of\s+pregnancy)\b",
            re.I,
        ),
        "cardiometabolic",
    ),
    (
        re.compile(
            r"\b(?:cardiovascular|cvd|ischemic\s+stroke|stroke|blood\s+pressure|"
            r"hypertension|hypertensive|type\s+2\s+diabetes|diabetes|insulin|"
            r"glucose|body\s+weight|bmi|overweight|metabolic)\b",
            re.I,
        ),
        "cardiometabolic",
    ),
    (re.compile(r"\b(?:creatinine|kidney)\b", re.I), "safety_comorbidity"),
)

OUTCOME_VOCAB: Mapping[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "animal_preclinical_context": ("Animal/Preclinical Context", ("animal preclinical context",), ()),
    "cardiometabolic": ("Cardiometabolic", (), ()),
    "cognitive": ("Cognitive", (), ()),
    "contextual_other": ("Contextual Adjacent Evidence", ("contextual other", "adjacent evidence"), ()),
    "deficiency_prevalence": ("Deficiency Prevalence", ("deficiency prevalence",), ("deficiency", "insufficiency", "prevalence")),
    "dosing_pharmacokinetics": ("Dosing and Pharmacokinetics", ("dosing pharmacokinetics",), ("dose", "dosing", "pharmacokinetic")),
    "frailty": ("Frailty", (), ()),
    "healthspan_qol": ("Healthspan and Quality of Life", ("healthspan qol", "quality of life"), ()),
    # "immune" is merged into immune_inflammation (same domain) so a corpus
    # does not fragment into two singleton sections; outcome_key canonicalizes
    # both ids to immune_inflammation.
    "immune_inflammation": ("Immune and Inflammation", ("immune inflammation", "immune"), ("inflammation", "immune", "immunoregulat", "sepsis", "infection", "cytokine")),
    "longevity": ("Longevity", (), ()),
    "mechanism": ("Mechanism", (), ()),
    "mortality_survival": ("Mortality and Survival", ("mortality survival",), ("mortality", "survival", "death", "cause_specific_death")),
    "muscle_function": ("Muscle Function", (), ("muscle", "sarcopenia", "myopathy")),
    "oncology": ("Oncology", (), ()),
    "ophthalmologic": ("Ophthalmologic", (), ()),
    "other": ("Other", (), ()),
    "safety": ("Safety", (), ()),
    "safety_comorbidity": ("Safety and Comorbidity", ("safety comorbidity",), ("safety", "adverse", "kidney", "chronic", "comorbidity")),
    # NB: bare "skeletal" was dropped — it substring-matched "skeletal muscle",
    # mis-filing muscle papers as bone. muscle_function (above, earlier in dict
    # order) now claims those via its "muscle" needle.
    "skeletal_fracture_bone": ("Skeletal, Fracture, and Bone", ("skeletal fracture bone", "bone fracture"), ("bone", "fracture", "osteoporosis", "calcium")),
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


def unique_outcome_displays(labels: Iterable[str], *, lower: bool = False) -> tuple[str, ...]:
    """Public labels, deduped after canonical alias resolution."""
    seen: set[str] = set()
    out: list[str] = []
    for label in labels:
        display = outcome_display(str(label))
        key = display.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(display.lower() if lower else display)
    return tuple(out)


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
    if str(getattr(receipt, "directness", "") or "").lower() == "protocol" and outcome_key(current_class) == "contextual_other":
        return "contextual_other"
    text = " ".join(str(getattr(receipt, name, "") or "") for name in ("receipt_id", "source_title", "population_summary")).lower()
    source_override = _lookup_source_text(text)
    if source_override is not None and current_class in {
        "other", "contextual_other", "skeletal_fracture_bone", "dosing_pharmacokinetics",
    }:
        return source_override
    if current_class != "other":
        return outcome_key(current_class)
    for label, needles in BIOMEDICAL_OTHER_OUTCOME_RULES:
        if any(needle in text for needle in needles):
            return label
    # A mechanistic-directness source whose outcome WHAT wasn't classifiable
    # above is MECHANISM evidence, not the undifferentiated catch-all — this
    # drains the "contextual adjacent" junk drawer (mostly preclinical work)
    # and separates mechanistic from clinical strata for tension grouping.
    # Universal: keys on the directness field, no topic terms.
    if str(getattr(receipt, "directness", "") or "").lower() == "mechanistic":
        return "mechanism"
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


def _lookup_source_text(text: str) -> str | None:
    normalized = " ".join(str(text or "").lower().split())
    if not normalized:
        return None
    for pattern, target in SOURCE_TEXT_OUTCOME_PATTERNS:
        if pattern.search(normalized):
            return target
    return None
