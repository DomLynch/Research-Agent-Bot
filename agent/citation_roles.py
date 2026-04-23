from __future__ import annotations

import re
from typing import Any, Literal


CitationRole = Literal[
    "published_results",
    "meta_analysis",
    "review",
    "registered_pending",
    "published_protocol",
    "observational",
    "animal_model",
    "off_domain_indirect",
    "mechanistic",
    "unknown",
]

ROLE_LANGUAGE_RULES: dict[CitationRole, dict[str, Any]] = {
    "published_results": {
        "forbidden": ["is investigating", "will examine", "plans to assess", "is evaluating", "ongoing rct", "ongoing trial"],
        "requires_numeric": True,
    },
    "meta_analysis": {
        "forbidden": ["is investigating", "will examine"],
        "requires_numeric": True,
    },
    "review": {
        "forbidden": ["randomized participants", "placebo arm"],
        "requires_numeric": False,
    },
    "registered_pending": {
        "forbidden": ["found", "reported", "showed", "demonstrated", "improved", "reduced", "increased"],
        "requires_numeric": False,
    },
    "published_protocol": {
        "forbidden": ["found", "reported", "showed", "demonstrated"],
        "requires_numeric": False,
    },
    "observational": {
        "forbidden": ["caused", "proved causation"],
        "requires_numeric": False,
        "requires_hedge": r"\b(observational|association|associated|cohort|retrospective|prospective)\b",
    },
    "animal_model": {
        "forbidden": ["patients", "older adults", "participants"],
        "requires_numeric": False,
        "requires_hedge": r"\b(animal models?|mouse|mice|murine|rat|zebrafish|drosophila|preclinical)\b",
    },
    "off_domain_indirect": {
        "forbidden": [],
        "requires_numeric": False,
        "requires_hedge": r"\b(oncology|cancer|pregnancy|pregestational|pediatric|neonatal|gestational|peripheral artery disease|parkinson|burn patients|hiv)\b",
    },
    "mechanistic": {
        "forbidden": ["patients", "older adults", "participants"],
        "requires_numeric": False,
        "requires_hedge": r"\b(mechanistic|mechanism|pathway|compound|preclinical)\b",
    },
    "unknown": {"forbidden": [], "requires_numeric": False},
}

ROLE_SECTION_TITLES: dict[CitationRole, str] = {
    "published_results": "=== PUBLISHED RESULTS (cite outcomes with numbers; use past tense) ===",
    "meta_analysis": "=== META-ANALYSES (cite pooled findings with numbers when available) ===",
    "review": "=== REVIEWS (contextual synthesis; do not overstate as new trial data) ===",
    "registered_pending": "=== REGISTERED / NOT YET REPORTED (cite design only, no outcomes) ===",
    "published_protocol": "=== PROTOCOLS (describe the planned trial only) ===",
    "observational": "=== OBSERVATIONAL STUDIES (use association/cohort language, not causality) ===",
    "animal_model": "=== ANIMAL MODELS (hedge with preclinical or animal-model language) ===",
    "off_domain_indirect": "=== OFF-DOMAIN INDIRECT (name the different domain explicitly) ===",
    "mechanistic": "=== MECHANISTIC / COMPOUND CONTEXT (not human outcome evidence) ===",
    "unknown": "=== OTHER / UNCERTAIN ROLE ===",
}

ROLE_ORDER: tuple[CitationRole, ...] = (
    "published_results",
    "meta_analysis",
    "observational",
    "review",
    "registered_pending",
    "published_protocol",
    "animal_model",
    "off_domain_indirect",
    "mechanistic",
    "unknown",
)

_PROTOCOL_RE = re.compile(
    r"(study protocol|protocol for|trial design|study design|rationale and (study )?design|design and rationale)",
    re.IGNORECASE,
)
_ANIMAL_RE = re.compile(
    r"\b(c\.?\s*elegans|caenorhabditis|mouse|mice|murine|rat|zebrafish|drosophila|animal model|mice\b|rats\b|mice\W|mice$|mitopark)\b",
    re.IGNORECASE,
)

_OFF_DOMAIN = {
    "longevity": (
        "esophageal", "pancreatic cancer", "gastric cancer", "cancer", "carcinoma",
        "pregnancy", "pregestational", "pediatric", "paediatric", "neonatal",
        "gestational", "prescription cascade", "peripheral artery disease", "parkinson",
    ),
    "anti-aging": (
        "esophageal", "pancreatic cancer", "gastric cancer", "cancer", "carcinoma",
        "pregnancy", "pregestational", "pediatric", "paediatric", "neonatal",
        "gestational", "prescription cascade", "peripheral artery disease", "parkinson",
    ),
    "anti aging": (
        "esophageal", "pancreatic cancer", "gastric cancer", "cancer", "carcinoma",
        "pregnancy", "pregestational", "pediatric", "paediatric", "neonatal",
        "gestational", "prescription cascade", "peripheral artery disease", "parkinson",
    ),
    "cardiology": ("pregnancy", "pediatric", "neonatal"),
    "metabolic": ("pediatric", "neonatal", "oncology", "cancer", "carcinoma"),
}

_REVIEW_TYPES = {"meta-analysis", "systematic-review", "review"}
_OBSERVATIONAL_TYPES = {"observational", "cohort", "case-control", "cross-sectional"}
_RESULT_TYPES = {"primary", "rct", "clinical-trial", "interventional"}


def _normalized_domain(domain_slug: str) -> str:
    return (domain_slug or "").strip().lower()


def _aging_signal(card: dict[str, Any], item: dict[str, Any]) -> bool:
    blob = " ".join(
        str(v or "")
        for v in (
            item.get("title"),
            item.get("excerpt"),
            card.get("population"),
            card.get("outcomes"),
            card.get("context"),
        )
    ).lower()
    return any(
        phrase in blob
        for phrase in ("aging", "ageing", "older adults", "frailty", "sarcopenia", "healthspan", "longevity", "cognitive")
    )


def _title_match(item: dict[str, Any], topic_tokens: list[str]) -> bool:
    title = str(item.get("title") or "").lower()
    return any(tok in title for tok in topic_tokens if tok)


def _off_domain_match(item: dict[str, Any], card: dict[str, Any], domain_slug: str) -> bool:
    domain = _normalized_domain(domain_slug)
    text = " ".join(str(v or "") for v in (item.get("title"), item.get("excerpt"))).lower()
    if domain in {"longevity", "anti-aging", "anti aging"} and card.get("context") in {"oncology", "transplant", "device", "pediatric"}:
        return True
    return any(term in text for term in _OFF_DOMAIN.get(domain, ()))


def classify_citation_role(
    item: dict[str, Any],
    card: dict[str, Any],
    domain_slug: str,
    topic_tokens: list[str],
) -> CitationRole:
    source_type = str(item.get("source_type") or "")
    evidence_type = str(item.get("evidence_type") or "").lower()
    quality = str(card.get("quality_signal") or "")
    study_type = str(card.get("study_type") or "")
    title = str(item.get("title") or "")

    if source_type == "clinicaltrials" and not item.get("has_results"):
        return "registered_pending"
    if source_type == "clinicaltrials" and item.get("has_results"):
        return "published_results"
    if source_type == "chembl" or evidence_type == "mechanism":
        return "mechanistic"
    if _PROTOCOL_RE.search(title) or quality == "protocol" or study_type == "protocol":
        return "published_protocol"
    if _ANIMAL_RE.search(title):
        return "animal_model"
    if _off_domain_match(item, card, domain_slug):
        return "off_domain_indirect"
    if quality in {"meta-analysis", "systematic-review"} or study_type == "meta-analysis":
        return "meta_analysis"
    if evidence_type == "review" or quality == "review":
        return "review"
    if study_type in _OBSERVATIONAL_TYPES or evidence_type in _OBSERVATIONAL_TYPES:
        return "observational"
    if (study_type in _RESULT_TYPES or evidence_type in _RESULT_TYPES or quality == "rct") and (
        _title_match(item, topic_tokens) or _aging_signal(card, item)
    ):
        return "published_results"
    if _title_match(item, topic_tokens) and evidence_type == "primary":
        return "published_results"
    return "unknown"


def citation_directness(
    role: CitationRole,
    item: dict[str, Any],
    card: dict[str, Any],
    domain_slug: str,
    topic_tokens: list[str],
) -> str:
    if role == "mechanistic":
        return "mechanistic"
    if role in {"registered_pending", "published_protocol", "animal_model", "off_domain_indirect", "unknown"}:
        return "indirect"
    title_match = _title_match(item, topic_tokens)
    if _normalized_domain(domain_slug) in {"longevity", "anti-aging", "anti aging"} or "aging" in _normalized_domain(domain_slug):
        return "direct" if title_match and _aging_signal(card, item) else "indirect"
    return "direct" if title_match else "indirect"


def role_sort_priority(role: CitationRole) -> int:
    return len(ROLE_ORDER) - ROLE_ORDER.index(role)


def role_relevance_bonus(role: CitationRole) -> float:
    return {
        "published_results": 0.2,
        "meta_analysis": 0.18,
        "observational": 0.08,
        "review": 0.08,
        "registered_pending": -0.05,
        "published_protocol": -0.08,
        "animal_model": -0.15,
        "off_domain_indirect": -0.15,
        "mechanistic": -0.1,
        "unknown": -0.02,
    }[role]


def role_section_title(role: CitationRole) -> str:
    return ROLE_SECTION_TITLES[role]
