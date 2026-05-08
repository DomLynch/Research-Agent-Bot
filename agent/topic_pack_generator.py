"""Dry-run topic-pack generator.

This module does not replace curated TOML packs. It produces a conservative,
TOML-compatible candidate structure that a human or later persistence layer can
review before use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

TopicTier = Literal["mainstream", "adjacent", "emerging", "contested", "pseudo"]
GenerationStatus = Literal["proceed", "stop"]
ExpansionStatus = Literal["enough", "expand", "stop"]

_SCOPE_TERMS = (
    "aging", "older adults", "elderly", "geriatric", "longevity",
    "healthspan", "frailty", "sarcopenia", "muscle function",
    "physical function", "cognition", "cardiometabolic", "cardiovascular",
    "mortality", "inflammation", "biomarkers", "safety",
)
_EVIDENCE_TYPES = (
    "clinical trial", "randomized controlled trial", "cohort study",
    "observational study", "meta-analysis", "systematic review",
)
_EXCLUDE_TERMS = (
    "pediatric only", "pregnancy only", "case report only",
    "cosmetic device only", "sports performance only",
)
_BACKGROUND_ALLOW = (
    "mechanism", "dose rationale", "field history",
    "preclinical lifespan signal", "mitochondrial function",
    "autophagy mechanism", "inflammation biology", "safety history",
)
_EXPECTED_SLOTS = (
    "human_rcts", "human_observational", "human_mechanism",
    "preclinical_lifespan", "meta_analysis", "systematic_review",
    "safety_tolerability", "dosing_regimen", "cardiometabolic",
    "muscle_function", "cognition", "frailty", "mortality",
    "inflammation", "biomarkers",
)
_SPECIAL_RULES = (
    "Separate direct human endpoints from indirect mechanistic evidence.",
    "Biomarker improvements are not healthspan or lifespan extension.",
    "Disease-treatment evidence is aging-relevant only with explicit outcome directness.",
)
_FORBIDDEN_PROTOCOL_VERBS = (
    "found", "showed", "improved", "reduced", "demonstrated",
    "established", "proved",
)
_PROTOCOL_KEYWORDS = ("planned", "will assess", "pending", "ongoing", "awaiting")
_PLACEBO_SYNONYMS = (
    "placebo", "control", "usual care", "standard care", "vehicle",
    "no intervention", "waitlist",
)
_CAP_BY_TIER = {
    "mainstream": 500,
    "adjacent": 350,
    "emerging": 250,
    "contested": 150,
    "pseudo": 0,
}
_MAINSTREAM = {
    "metformin", "statin", "statins", "omega3", "omega-3",
    "vitamin d", "aspirin", "exercise", "resistance training",
}
_EMERGING = {
    "urolithin a", "spermidine", "nad", "nmn", "nicotinamide riboside",
    "taurine", "berberine", "acarbose", "rapamycin", "everolimus",
}
_CONTESTED = {
    "young blood", "plasma exchange", "growth hormone", "biohacking",
    "stem cell clinic", "peptide stack",
}
_PSEUDO = {
    "homeopathy", "crystal healing", "quantum healing", "alkaline water",
    "aura cleansing", "detox foot bath", "scalar energy",
}
_PRECURSORS = {
    "urolithin a": (
        "ellagitannin", "ellagic acid", "punicalagin",
        "pomegranate polyphenols", "gut microbiome urolithin",
    ),
    "nad": (
        "nicotinamide riboside", "nicotinamide mononucleotide",
        "niacinamide", "nad precursor",
    ),
    "omega3": ("eicosapentaenoic acid", "docosahexaenoic acid", "EPA", "DHA"),
    "omega-3": ("eicosapentaenoic acid", "docosahexaenoic acid", "EPA", "DHA"),
}
_ADAPTIVE_TERMS = (
    "dose response", "older adults", "randomized controlled trial",
    "systematic review", "safety", "mechanism",
)


@dataclass(frozen=True, slots=True)
class RetrievalCounts:
    unique_candidates: int = 0
    pmcid_resolved: int = 0
    extracted: int = 0


@dataclass(frozen=True, slots=True)
class AdaptiveExpansionPlan:
    status: ExpansionStatus
    additional_terms: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class GeneratedTopicPack:
    topic: str
    slug: str
    tier: TopicTier
    status: GenerationStatus
    stop_reason: str | None
    aliases: tuple[str, ...]
    topic_terms: tuple[str, ...]
    scope_terms: tuple[str, ...]
    evidence_types: tuple[str, ...]
    exclude_terms: tuple[str, ...]
    background_allow: tuple[str, ...]
    corpus_search_queries: tuple[str, ...]
    candidate_cap: int
    validation_errors: tuple[str, ...]
    species: tuple[str, ...] = ()

    def to_topic_pack_dict(self) -> dict[str, object]:
        """Return a TOML-style structure compatible with TopicPack fields."""
        return {
            "topic": self.slug,
            "class_": "generated_biomedical",
            "aliases": list(self.aliases),
            "expected_evidence_slots": list(_EXPECTED_SLOTS),
            "special_rules": list(_SPECIAL_RULES),
            "forbidden_verbs_for_protocol_role": list(_FORBIDDEN_PROTOCOL_VERBS),
            "forbidden_verbs_for_results_role_with_protocol_keywords": list(
                _PROTOCOL_KEYWORDS
            ),
            "canonical_trials": [],
            "known_role_overrides": {},
            "active_arm_synonyms": [a.lower() for a in self.aliases],
            "placebo_arm_synonyms": list(_PLACEBO_SYNONYMS),
            "corpus_search_queries": list(self.corpus_search_queries),
            "canonical_rct_paper_ids": [],
            "retrieval": {
                "topic_terms": list(self.topic_terms),
                "scope_terms": list(self.scope_terms),
                "evidence_types": list(self.evidence_types),
                "exclude_terms": list(self.exclude_terms),
                "date_from": 2000,
                "languages": ["English"],
                "species": list(self.species),
                "background": {"allow": list(self.background_allow)},
            },
            "endpoint_polarity": {
                "mortality": "lower_is_better",
                "frailty": "lower_is_better",
                "inflammation": "lower_is_better",
                "cardiometabolic_risk": "lower_is_better",
                "cardiovascular_events": "lower_is_better",
                "adverse_events": "lower_is_better",
                "muscle_function": "higher_is_better",
                "physical_function": "higher_is_better",
                "cognition": "higher_is_better",
                "lean_mass": "higher_is_better",
                "adherence": "higher_is_better",
            },
        }


def generate_candidate_topic_pack(
    topic_name: str,
    *,
    seed_terms: tuple[str, ...] = (),
) -> GeneratedTopicPack:
    topic = _clean_topic(topic_name)
    tier = classify_topic_tier(topic, seed_terms)
    status: GenerationStatus = "stop" if tier == "pseudo" else "proceed"
    aliases = _dedupe((topic, topic.replace("-", " "), *seed_terms))
    topic_terms = _dedupe((topic, *seed_terms, *precursor_terms(topic, seed_terms)))
    pack = GeneratedTopicPack(
        topic=topic,
        slug=slugify(topic),
        tier=tier,
        status=status,
        stop_reason="pseudo or out-of-scope biomedical topic" if status == "stop" else None,
        aliases=aliases,
        topic_terms=topic_terms,
        scope_terms=_SCOPE_TERMS,
        evidence_types=_EVIDENCE_TYPES,
        exclude_terms=_EXCLUDE_TERMS,
        background_allow=_BACKGROUND_ALLOW,
        corpus_search_queries=_queries(topic_terms),
        candidate_cap=_CAP_BY_TIER[tier],
        validation_errors=(),
    )
    return _with_validation(pack)


def classify_topic_tier(topic_name: str, seed_terms: tuple[str, ...] = ()) -> TopicTier:
    text = " ".join((topic_name, *seed_terms)).lower()
    if _contains_any(text, _PSEUDO):
        return "pseudo"
    if _contains_any(text, _CONTESTED):
        return "contested"
    if _contains_any(text, _MAINSTREAM):
        return "mainstream"
    if _contains_any(text, _EMERGING):
        return "emerging"
    return "adjacent"


def precursor_terms(topic_name: str, seed_terms: tuple[str, ...] = ()) -> tuple[str, ...]:
    text = " ".join((topic_name, *seed_terms)).lower()
    terms: list[str] = []
    for marker, expansions in _PRECURSORS.items():
        if marker in text:
            terms.extend(expansions)
    return _dedupe(terms)


def suggest_adaptive_expansion(
    pack: GeneratedTopicPack,
    counts: RetrievalCounts,
    *,
    floor: int = 50,
) -> AdaptiveExpansionPlan:
    if pack.status == "stop":
        return AdaptiveExpansionPlan("stop", (), "pack is stopped")
    if counts.unique_candidates >= pack.candidate_cap:
        return AdaptiveExpansionPlan("stop", (), "candidate cap reached")
    if counts.unique_candidates >= floor:
        return AdaptiveExpansionPlan("enough", (), "candidate floor met")
    terms = _dedupe((*precursor_terms(pack.topic, pack.topic_terms), *_ADAPTIVE_TERMS))
    terms = tuple(t for t in terms if t.lower() not in {x.lower() for x in pack.topic_terms})
    return AdaptiveExpansionPlan("expand", terms, "candidate floor not met")


def validate_candidate_pack(pack: GeneratedTopicPack) -> tuple[str, ...]:
    errors: list[str] = []
    data = pack.to_topic_pack_dict()
    for key in (
        "topic", "class_", "aliases", "expected_evidence_slots",
        "special_rules", "forbidden_verbs_for_protocol_role",
        "forbidden_verbs_for_results_role_with_protocol_keywords",
        "canonical_trials", "known_role_overrides", "retrieval",
    ):
        if key not in data:
            errors.append(f"missing required field: {key}")
    if not pack.topic_terms:
        errors.append("retrieval.topic_terms must be non-empty")
    if pack.tier == "pseudo" and pack.status == "proceed":
        errors.append("pseudo tier cannot proceed")
    if pack.species:
        errors.append("generated biomedical packs must not hard-filter species")
    if pack.status == "proceed" and pack.candidate_cap <= 0:
        errors.append("proceeding pack must have positive candidate_cap")
    return tuple(errors)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "generated_topic"


def _with_validation(pack: GeneratedTopicPack) -> GeneratedTopicPack:
    return replace(pack, validation_errors=validate_candidate_pack(pack))


def _clean_topic(value: str) -> str:
    topic = " ".join(value.strip().split())
    if not topic:
        raise ValueError("topic_name is required")
    return topic


def _queries(topic_terms: tuple[str, ...]) -> tuple[str, ...]:
    queries: list[str] = []
    for term in topic_terms[:5]:
        queries.extend((
            f"{term} aging",
            f"{term} older adults",
            f"{term} randomized controlled trial",
        ))
    return _dedupe(queries)[:10]


def _contains_any(text: str, markers: set[str]) -> bool:
    return any(marker in text for marker in markers)


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value).strip().split())
        key = cleaned.lower()
        if cleaned and key not in seen:
            out.append(cleaned)
            seen.add(key)
    return tuple(out)
