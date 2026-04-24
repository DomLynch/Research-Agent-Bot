from __future__ import annotations

from agent.evidence_cards import build_card
from agent.citation_roles import (
    ROLE_ORDER,
    classify_citation_role,
    citation_directness,
    role_relevance_bonus,
    role_section_title,
    role_sort_priority,
)
from agent.entity_resolver import resolve_topic
from agent.submit import RESEARKA_MIN_SOURCES
from agent.validator import validate_citations

import os
import re
from datetime import datetime, timezone
from typing import Any


SECTION_FIELDS = (
    ("Research Question", "question"),
    ("Search Summary", "search_summary"),
    ("Evidence Landscape", "landscape"),
    ("Key Findings", "findings"),
    ("Limitations", "limitations"),
    ("Gaps Identified", "gaps_identified"),
    ("Conclusion", "conclusion"),
)
LEAKY_PHRASES = (
    "coverage decay detected",
    "replace this section",
    "revision brief",
    "[placeholder",
    "[tbd",
    "[tk]",
)
_FALLBACKS = {
    "Research Question": "This draft asks whether {topic} has decision-relevant evidence in the {domain} domain and keeps the scope narrow enough to stay faithful to the retained evidence.",
    "Key Findings": "The main signal is directional rather than definitive. The evidence bundle suggests the topic is relevant, but the confidence level should stay bounded by heterogeneous designs, limited samples, and incomplete replication.",
    "Conclusion": "The draft supports a cautious summary on {topic} without claiming more than the retained evidence can justify. Representative retained titles include {titles}.",
}
_GENERIC_FALLBACK = "This section draws on {nr} retained evidence receipts ({rv} review, {pr} primary) queried on {today} via {nq} scoped search strings."

_STOPWORDS = {"and", "in", "for", "of", "the", "with", "on", "to", "a", "an"}
_SYNONYMS = {"rapamycin": ["sirolimus"], "metformin": ["glucophage"], "senolytic": ["senolytics"]}
_GENERIC_TOPIC_TOKENS = {
    "aging", "ageing", "older", "adult", "adults", "elderly", "longevity", "healthspan",
    "health", "outcome", "outcomes", "function", "functional", "study", "studies",
    "trial", "trials", "therapy", "therapies", "treatment", "treatments", "intervention",
    "interventions", "disease", "prevention", "risk", "risks",
}

_INJECTION_PATTERNS = (
    r"ignore previous instructions",
    r"you are now",
    r"system prompt",
    r"reveal your",
    r"act as",
    r"do not follow",
    r"new instructions",
    r"override",
    r"jailbreak",
    r"prompt injection",
    r"disregard.*above",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"BEGINCHAT",
    r"ENDCHAT",
)
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)
_NUMERIC_CLAIM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_QUANT_LITERAL_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|ppm|mg|fold|x|years?|months?|days?|patients?|subjects?|participants?|kg|mg/kg|ug|l|ml|nm|um|ul|mmhg|bpm)",
    re.IGNORECASE,
)
_OUTCOME_VERB_RE = re.compile(
    r"\b(found|showed|reported|demonstrated|improved|reduced|increased|decreased|achieved|yielded)\b",
    re.IGNORECASE,
)
_NUMERIC_SENTENCE_RE = re.compile(
    r"(?:\bhr\b|hazard ratio|odds ratio|\bor\b|\brr\b|confidence interval|\bci\b|"
    r"p\s*[<=>]|n\s*=|\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*(?:months?|years?|weeks?|days?|kg|mg|mmhg))",
    re.IGNORECASE,
)
_EFFECT_STYLE_RE = re.compile(
    r"(?:\bhr\b|hazard ratio|odds ratio|\bor\b|\brr\b|confidence interval|\bci\b|"
    r"p\s*[<=>]|vs\.?|versus|mean(?:\s+(?:change|difference))?|difference|"
    r"reduced?|increased?|decreased?|improved?|worsened?|higher|lower|"
    r"\d+(?:\.\d+)?\s*%)",
    re.IGNORECASE,
)
_RESULT_MARKER_RE = re.compile(
    r"(?:p\s*[<=>]|n\s*=|95%\s*ci|confidence interval|\bhr\b|hazard ratio|"
    r"\bor\b|odds ratio|\brr\b|placebo\b|control\b|\d+(?:\.\d+)?\s*%)",
    re.IGNORECASE,
)
_CITATION_TOKEN_RE = re.compile(r"\[(\d+)\]")
_PUBLISHED_RESULT_REPAIRS = {
    "is investigating": "evaluated",
    "is evaluating": "evaluated",
    "will examine": "evaluated",
    "plans to assess": "evaluated",
}
_STRUCTURED_RESULT_LABEL_RE = re.compile(
    r"\b(FINDINGS|RESULTS|INTERPRETATION|CONCLUSIONS?)\s*:\s*",
    re.IGNORECASE,
)
_OUTCOME_SENTENCE_RE = re.compile(
    r"(?:adjusted treatment effect|did not improve|no significant|mean [\w\- ]+ at \d+|"
    r"treatment group|placebo group|intervention group|versus placebo|compared (?:with|to) placebo)",
    re.IGNORECASE,
)
_PRIMARY_RESULT_SENTENCE_RE = re.compile(
    r"(?:primary outcome|adjusted treatment effect|did not improve|no significant|"
    r"mean [\w\- ]+ at \d+|between-group difference)",
    re.IGNORECASE,
)
_STRONG_RESULT_SENTENCE_RE = re.compile(
    r"(?:adjusted treatment effect|95%\s*ci|confidence interval|p\s*[<=>]|"
    r"hazard ratio|odds ratio|\brr\b|versus placebo|compared (?:with|to) placebo|"
    r"placebo group|intervention group|treatment group|mean (?:difference|change))",
    re.IGNORECASE,
)
_SAFETY_EVENT_SENTENCE_RE = re.compile(
    r"(?:adverse events?|serious adverse|hospital admissions?|poorly tolerated|death occurred|funding:)",
    re.IGNORECASE,
)
_TRIAL_FLOW_SENTENCE_RE = re.compile(
    r"(?:screened|eligible|randomly assigned|randomised|enrolled|recruited|"
    r"mean age|baseline|follow-up completed|dropout)",
    re.IGNORECASE,
)
_DECIMAL_INTERPUNCT_RE = re.compile(r"(?<=\d)[·•](?=\d)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CLAIM_QUALITY_RE = re.compile(
    r"(?:effect|result|mean|median|difference|n\s*=|p\s*[<=>]|confidence interval|\bci\b|"
    r"vs\.?|versus|compared|reduced|increased|significant|reported|found|improved)",
    re.IGNORECASE,
)
_LONGEVITY_OUTCOME_RE = re.compile(
    r"(?:frailty|sarcopenia|muscle|strength|endurance|cognition|cognitive|mobility|"
    r"walking|gait|healthspan|longevity|resilience|functional|physical performance|"
    r"visceral adiposity|lean (?:mass|tissue)|body composition|brain)",
    re.IGNORECASE,
)
_POPULATION_SIGNAL_RE = re.compile(
    r"(?:older adults?|older people|aging adults?|healthy adults?|human|clinical|participants?|patients?)",
    re.IGNORECASE,
)
_LONGEVITY_SUPPORT_RE = re.compile(
    r"(?:older adults?|older people|elderly|geriatric|frailty|prefrailty|sarcopenia|"
    r"healthspan|aging|ageing|cognitive|brain aging|physical performance|gait|mobility)",
    re.IGNORECASE,
)
_PROCEDURAL_ACUTE_RE = re.compile(
    r"(?:surgery|surgical|peri-?operat|post-?operat|icu admission|hospital free days?|elective surgery|hospital admission|length of stay)",
    re.IGNORECASE,
)
_ACTIVE_COMPARATOR_RE = re.compile(
    r"\b(vs\.?|versus|compared with|comparison|target trial emulation)\b",
    re.IGNORECASE,
)
_CONTROL_COMPARATOR_RE = re.compile(
    r"\b(placebo|usual care|standard care|control group|control arm|sham)\b",
    re.IGNORECASE,
)
_SINGULAR_STUDY_RE = re.compile(r"\b(one|single|a)\s+(trial|study|rct|cohort)\b", re.IGNORECASE)
_CITATION_CLUSTER_RE = re.compile(r"\[((?:\d+\s*,\s*)+\d+)\]")
_ANY_CITATION_RE = re.compile(r"\[((?:\d+\s*,\s*)*\d+)\]")

_SYNONYM_CANONICALS = {
    alias: canonical
    for canonical, aliases in _SYNONYMS.items()
    for alias in aliases
}
_VALID_TOPIC_FIT_BUCKETS = {"core", "landscape", "drop"}
_VALID_DIRECTNESS = {"direct", "indirect", "mechanistic"}
_TIER_A1 = "Tier A1 direct aging evidence"
_TIER_A2 = "Tier A2 disease-context human evidence"
_TIER_B = "Tier B supporting human evidence"
_TIER_C = "Tier C protocol/mechanistic support"
_VALID_EVIDENCE_TIERS = {
    _TIER_A1,
    _TIER_A2,
    _TIER_B,
    _TIER_C,
}
_DISEASE_CONTEXT_RE = re.compile(
    r"(?:alzheimer|dementia|diabetes|burn|fibrosis|ipf|oral health|periodont|"
    r"angiodysplas|polyposis|covid|cancer|obesity|depression|stroke|"
    r"cardiovascular|renal|kidney|liver disease|retinopathy|glaucoma)",
    re.IGNORECASE,
)


def _clean(value: Any, limit: int = 2000) -> str:
    raw = str(value or "")
    raw = _INJECTION_RE.sub("[REDACTED]", raw)
    raw = _DECIMAL_INTERPUNCT_RE.sub(".", raw)
    return re.sub(r"\s+", " ", raw).strip()[:limit]


def _normalized_title_key(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", _clean(value, limit=400).lower())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _duplicate_keys(item: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    doi = _clean(item.get("doi"), limit=200).lower()
    if doi:
        keys.append(f"doi:{doi}")
    url = _clean(item.get("url"), limit=300).lower()
    if url:
        keys.append(f"url:{url}")
    title_key = _normalized_title_key(item.get("title"))
    year = int(item.get("year") or 0)
    if title_key:
        keys.append(f"title:{title_key}")
        if year:
            keys.append(f"title_year:{title_key}:{year}")
    return keys


def _raw_evidence_rank(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
    source_type = str(item.get("source_type") or "")
    url = str(item.get("url") or "").lower()
    source_bonus = 3 if source_type == "pubmed" else 2 if source_type == "clinicaltrials" else 1
    if source_type == "europepmc" and "/med/" in url:
        source_bonus += 1
    return (
        int(item.get("year") or 0),
        1 if _clean(item.get("doi"), limit=120) else 0,
        source_bonus,
        len(_clean(item.get("excerpt"), limit=1600)),
        len(item.get("authors") or []),
    )


def _intervention_terms(topic_meta: dict[str, Any]) -> tuple[list[str], list[str]]:
    exact = []
    for term in [topic_meta.get("canonical_term"), *(topic_meta.get("aliases") or [])]:
        cleaned = _clean(term, limit=80).lower()
        if cleaned and cleaned not in exact:
            exact.append(cleaned)
    class_terms = []
    for term in topic_meta.get("class_terms") or []:
        cleaned = _clean(term, limit=80).lower()
        if cleaned and cleaned not in class_terms and cleaned not in exact:
            class_terms.append(cleaned)
    return exact, class_terms


def _intervention_fit_level(item: dict[str, Any], card: dict[str, Any], topic_meta: dict[str, Any]) -> str:
    exact_terms, class_terms = _intervention_terms(topic_meta)
    blob = " ".join(
        _clean(v, limit=400).lower()
        if not isinstance(v, list)
        else " ".join(_clean(part, limit=120).lower() for part in v[:12])
        for v in (
            item.get("title"),
            item.get("excerpt"),
            card.get("intervention"),
            item.get("topic_terms"),
            item.get("mesh_terms"),
            item.get("summary"),
        )
    )
    if any(term in blob for term in exact_terms):
        return "exact"
    if any(term in blob for term in class_terms):
        return "class"
    return "none"


def _disease_context_signal(item: dict[str, Any], card: dict[str, Any]) -> bool:
    blob = " ".join(
        str(v or "")
        for v in (
            item.get("title"),
            item.get("excerpt"),
            card.get("population"),
            card.get("context"),
        )
    )
    return bool(_DISEASE_CONTEXT_RE.search(blob))


def _longevity_support_signal(entry: dict[str, Any]) -> bool:
    card = entry.get("card") or {}
    blob = " ".join(
        str(v or "")
        for v in (
            entry.get("title"),
            entry.get("excerpt"),
            card.get("population"),
            card.get("outcomes"),
        )
    )
    return bool(_LONGEVITY_SUPPORT_RE.search(blob) or _aging_outcome_signal(blob))


def _active_comparator_signal(item: dict[str, Any], card: dict[str, Any]) -> bool:
    blob = " ".join(
        str(v or "")
        for v in (
            item.get("title"),
            item.get("excerpt"),
            card.get("intervention"),
            card.get("comparator"),
            card.get("outcomes"),
        )
    )
    return bool(_ACTIVE_COMPARATOR_RE.search(blob) and not _CONTROL_COMPARATOR_RE.search(blob))


def _longevity_intent_signal(entry: dict[str, Any]) -> bool:
    card = entry.get("card") or {}
    blob = " ".join(
        str(v or "")
        for v in (
            entry.get("title"),
            entry.get("excerpt"),
            card.get("population"),
            card.get("outcomes"),
            card.get("context"),
            card.get("methods_summary"),
        )
    )
    has_longevity_signal = bool(_LONGEVITY_SUPPORT_RE.search(blob) or _aging_outcome_signal(blob))
    has_disease_context = _disease_context_signal(entry, card)
    if not has_longevity_signal and not has_disease_context:
        return False
    if _PROCEDURAL_ACUTE_RE.search(blob) and not _aging_outcome_signal(blob):
        return False
    if _active_comparator_signal(entry, card) and not _aging_outcome_signal(blob):
        return False
    return True


def _core_topic_tokens(topic_tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    core: list[str] = []
    for token in topic_tokens:
        cleaned = _clean(token, limit=80).lower()
        if not cleaned or cleaned in _STOPWORDS or cleaned in _GENERIC_TOPIC_TOKENS:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        core.append(cleaned)
    if core:
        return core
    return [token for token in topic_tokens if token and token not in _STOPWORDS]


def _mentions_topic(text: str, topic_tokens: list[str]) -> bool:
    haystack = _clean(text, limit=2400).lower()
    return any(token in haystack for token in _core_topic_tokens(topic_tokens))


def _topic_profile(topic: str, topic_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    topic_meta = topic_meta or resolve_topic(topic, chembl_client=None)
    raw_tokens = [t for t in _clean(topic).lower().split() if t not in _STOPWORDS]
    canonical = _clean((topic_meta or {}).get("canonical_term"), limit=80).lower()
    if not canonical:
        core = _core_topic_tokens(raw_tokens)
        canonical = core[0] if core else (raw_tokens[0] if raw_tokens else "")
    canonical = _SYNONYM_CANONICALS.get(canonical, canonical)
    aliases: list[str] = []
    for value in ((topic_meta or {}).get("aliases") or []) + _SYNONYMS.get(canonical, []):
        cleaned = _clean(value, limit=80).lower()
        if cleaned and cleaned != canonical and cleaned not in aliases:
            aliases.append(cleaned)
    class_terms: list[str] = []
    for value in (topic_meta or {}).get("class_terms") or []:
        cleaned = _clean(value, limit=80).lower()
        if cleaned and cleaned != canonical and cleaned not in aliases and cleaned not in class_terms:
            class_terms.append(cleaned)
    claim_terms = [term for term in [canonical, *aliases] if term]
    fit_terms = [term for term in [*claim_terms, *class_terms] if term]
    query_terms = list(dict.fromkeys([*raw_tokens, *fit_terms]))
    return {
        "canonical_term": canonical,
        "aliases": aliases,
        "class_terms": class_terms,
        "claim_terms": claim_terms,
        "fit_terms": fit_terms,
        "query_terms": query_terms,
    }


def _term_hits(text: str, terms: list[str]) -> int:
    haystack = _clean(text, limit=3000).lower()
    return sum(1 for term in terms if term and term in haystack)


def _entry_title_mentions_topic(entry: dict[str, Any], topic_tokens: list[str]) -> bool:
    return _mentions_topic(str(entry.get("title") or ""), topic_tokens)


def _sentence_complete(sentence: str) -> bool:
    bare = _strip_citations(_clean(sentence, limit=500), limit=500)
    if not bare or bare[-1] not in ".!?":
        return False
    if re.search(r"\bvs\.$", bare, re.IGNORECASE):
        return False
    if bare.count("(") != bare.count(")") or bare.count("[") != bare.count("]"):
        return False
    return True


def _complete_sentences(text: str, *, max_sentences: int | None = None, limit: int = 1200) -> str:
    kept = [sentence for sentence in _split_sentences(_trim_incomplete_fragments(text, limit=limit), limit=limit) if _sentence_complete(sentence)]
    if max_sentences is not None:
        kept = kept[:max_sentences]
    return _clean(" ".join(kept), limit=limit)


def _sentence_key(sentence: str) -> str:
    return re.sub(r"[^a-z0-9.%/\-]+", " ", _strip_citations(sentence, limit=900).lower()).strip()


def _drop_shared_sentences(text: str, other: str, *, limit: int = 1200) -> str:
    other_keys = {_sentence_key(sentence) for sentence in _split_sentences(other, limit=limit)}
    kept = [sentence for sentence in _split_sentences(text, limit=limit) if _sentence_key(sentence) not in other_keys]
    return _clean(" ".join(kept), limit=limit) if kept else _clean(text, limit=limit)


def _trim_incomplete_fragments(text: str, *, limit: int = 1200) -> str:
    cleaned = re.sub(r"\bvs\.(?=(?:\s*[).,;:]|$))", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bversus(?=(?:\s*[).,;:]|$))", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\.\.+", ".", cleaned)
    cleaned = re.sub(r"\s+\.", ".", cleaned)
    return _clean(cleaned, limit=limit)


def _normalize_numeric_phrase(text: str, *, limit: int = 400) -> str:
    cleaned = _trim_incomplete_fragments(text, limit=limit)
    if not cleaned:
        return cleaned
    cleaned = re.sub(r"\bMEAN\b", "mean", cleaned)
    cleaned = re.sub(r"\bMEDIAN\b", "median", cleaned)
    cleaned = re.sub(r"\bspread\b", "SD", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?!CI\b|RR\b|HR\b|OR\b|SD\b|MD\b|N\b|P\b)([A-Z][A-Za-z0-9+/\-]{2,})=([-+]?\d)",
        r"\1 \2",
        cleaned,
    )
    return cleaned


def _split_sentences(text: str, *, limit: int = 4000) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(_clean(text, limit=limit)) if part.strip()]


def _sentence_refs(sentence: str) -> list[int]:
    return [int(match.group(1)) for match in _CITATION_TOKEN_RE.finditer(sentence)]


def _claim_sentence_quality_ok(sentence: str) -> bool:
    bare = _strip_citations(_normalize_numeric_phrase(sentence), limit=400)
    if not bare:
        return False
    if len(bare) < 40 or len(bare) > 300:
        return False
    if bare[-1] not in ".!?":
        return False
    return bool(_CLAIM_QUALITY_RE.search(bare))


def _aging_outcome_signal(text: str) -> bool:
    return bool(_LONGEVITY_OUTCOME_RE.search(_clean(text, limit=3000)))


def _topic_fit_score(
    item: dict[str, Any],
    card: dict[str, Any],
    topic_meta: dict[str, Any],
    domain_slug: str,
) -> float:
    role = str(item.get("role") or "")
    if role in {"off_domain_indirect", "animal_model"}:
        return 0.0
    canonical = str(topic_meta.get("canonical_term") or "")
    aliases = list(topic_meta.get("aliases") or [])
    class_terms = list(topic_meta.get("class_terms") or [])
    title = _clean(item.get("title"), limit=300).lower()
    abstract = _clean(item.get("excerpt"), limit=2200).lower()
    intervention = _clean(card.get("intervention"), limit=200).lower()
    metadata_blob = " ".join(
        _clean(v, limit=200).lower()
        if not isinstance(v, list)
        else " ".join(_clean(item, limit=80).lower() for item in v[:8])
        for v in (
            item.get("topic_terms"),
            item.get("mesh_terms"),
            item.get("summary"),
        )
    )
    negative_terms = [term for term in [canonical, *aliases, *class_terms] if term]
    negative_context = any(
        re.search(rf"\b(without|unrelated to|not|non|no)\b[^.;,]{{0,40}}\b{re.escape(term)}\b", abstract)
        for term in negative_terms
    )
    score = 0.0
    if canonical and canonical in title:
        score += 0.4
    has_alias_title = any(alias in title for alias in aliases)
    has_class_text = any(term in f"{title} {abstract} {intervention} {metadata_blob}" for term in class_terms)
    if has_alias_title:
        score += 0.3
    if any(term in title for term in class_terms):
        score += 0.15
    if str(item.get("evidence_type") or "") == "review" and has_class_text:
        score += 0.15
        if _POPULATION_SIGNAL_RE.search(f"{title} {abstract}"):
            score += 0.1
    mention_count = 0 if negative_context else _term_hits(f"{title} {abstract} {intervention} {metadata_blob}", [canonical, *aliases])
    if mention_count >= 2:
        score += 0.2
    elif mention_count == 1:
        score += 0.1
    if any(term in intervention for term in [canonical, *aliases, *class_terms] if term):
        score += 0.25
    if role == "published_results" and (canonical in title or has_alias_title):
        if _POPULATION_SIGNAL_RE.search(f"{title} {abstract}") or _aging_outcome_signal(f"{title} {abstract}"):
            score += 0.2
    if (domain_slug or "").lower() in {"longevity", "anti-aging", "anti aging"}:
        blob = " ".join(
            str(v or "")
            for v in (
                item.get("title"),
                item.get("excerpt"),
                card.get("population"),
                card.get("outcomes"),
                card.get("context"),
            )
        )
        if _aging_outcome_signal(f"{blob} {metadata_blob}"):
            score += 0.15
    return round(min(score, 1.0), 2)


def _topic_fit_bucket(score: float) -> str:
    if score >= 0.5:
        return "core"
    if score >= 0.3:
        return "landscape"
    return "drop"


def _evidence_tier(
    item: dict[str, Any],
    card: dict[str, Any],
    *,
    role: str,
    directness: str,
    topic_fit_bucket: str,
    intervention_fit: str,
) -> str:
    if role in {"registered_pending", "published_protocol", "animal_model", "mechanistic", "off_domain_indirect", "unknown"}:
        return _TIER_C
    if str(item.get("evidence_type") or "") == "review" or role == "meta_analysis":
        return _TIER_B
    blob = " ".join(
        str(v or "")
        for v in (
            item.get("title"),
            item.get("excerpt"),
            card.get("population"),
            card.get("outcomes"),
            card.get("context"),
        )
    )
    study_type = str(card.get("study_type") or "").lower()
    exact_fit = intervention_fit == "exact"
    if _active_comparator_signal(item, card) and not _aging_outcome_signal(blob):
        return _TIER_B
    if directness == "direct" and exact_fit and topic_fit_bucket == "core":
        if study_type in {"cohort", "observational", "case-control", "cross-sectional"} or _disease_context_signal(item, card):
            return _TIER_A2
        if _aging_outcome_signal(blob) and (
            role == "published_results"
            or study_type in {"rct", "clinical-trial"}
            or str(item.get("evidence_type") or "") == "interventional"
        ):
            return _TIER_A1
    if exact_fit and role in {"published_results", "observational"} and (
        study_type in {"cohort", "observational", "case-control", "cross-sectional"} or _disease_context_signal(item, card)
    ):
        return _TIER_A2
    return _TIER_B


def _claim_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    extraction = entry.get("extraction") or {}
    effects = extraction.get("effects") or []
    card = entry.get("card") or {}
    if effects:
        effect = effects[0]
        source_span = _normalize_numeric_phrase(_clean(effect.get("source_span"), limit=320), limit=320)
        if source_span and source_span[-1] not in ".!?":
            source_span = f"{source_span}."
        claim = {
            "intervention": _clean(extraction.get("intervention") or card.get("intervention"), limit=120),
            "comparator": _clean(extraction.get("comparator") or card.get("comparator"), limit=120),
            "endpoint": _clean(effect.get("outcome") or extraction.get("primary_outcome"), limit=120),
            "metric": _normalize_numeric_phrase(_clean(effect.get("metric"), limit=40), limit=40),
            "effect": _normalize_numeric_phrase(_clean(effect.get("value"), limit=160), limit=160),
            "p_value": _clean(effect.get("p_value"), limit=32),
            "n": _clean(effect.get("n"), limit=80),
            "source_span": source_span,
        }
        return claim
    excerpt = _clean(entry.get("excerpt"), limit=700)
    for sentence in _split_sentences(excerpt, limit=700):
        if not _claim_sentence_quality_ok(sentence):
            continue
        if not (_RESULT_MARKER_RE.search(sentence) or _STRONG_RESULT_SENTENCE_RE.search(sentence)):
            continue
        return {
            "intervention": _clean(card.get("intervention"), limit=120),
            "comparator": _clean(card.get("comparator"), limit=120),
            "endpoint": _clean(card.get("outcomes"), limit=120) or "reported outcome",
            "metric": "",
            "effect": "",
            "p_value": "",
            "n": "",
            "source_span": _normalize_numeric_phrase(sentence, limit=320),
        }
    return None


def _claim_has_structured_fields(claim: dict[str, Any] | None) -> bool:
    return bool(claim and any(claim.get(field) for field in ("metric", "effect", "p_value", "n")))


def _claim_schema_ok(claim: dict[str, Any] | None) -> bool:
    if not claim:
        return False
    if not claim.get("endpoint"):
        return False
    if _claim_has_structured_fields(claim):
        return True
    if not _RESULT_MARKER_RE.search(str(claim.get("source_span") or "")):
        return False
    return _claim_sentence_quality_ok(str(claim.get("source_span") or ""))


def _claim_sentence(claim: dict[str, Any] | None) -> str:
    if not _claim_schema_ok(claim):
        return ""
    if _claim_has_structured_fields(claim):
        return ""
    source_span = _strip_citations(str((claim or {}).get("source_span") or ""), limit=320)
    sentences = _split_sentences(source_span, limit=320)
    if len(sentences) != 1:
        return ""
    sentence = sentences[0]
    if not _claim_sentence_quality_ok(sentence):
        return ""
    return sentence


def _dedupe_repeated_sentences(text: str) -> str:
    cleaned = _clean(text, limit=4000)
    if not cleaned:
        return cleaned
    kept: list[str] = []
    seen: set[tuple[tuple[int, ...], str]] = set()
    for sentence in _split_sentences(cleaned):
        norm = re.sub(r"[^a-z0-9.%/\-]+", " ", _strip_citations(sentence, limit=900).lower()).strip()
        key = (tuple(sorted(set(_sentence_refs(sentence)))), norm)
        if norm and key in seen:
            continue
        seen.add(key)
        kept.append(sentence)
    return " ".join(kept).strip()


def _strip_offtopic_claims(text: str, source_bundle: list[dict[str, Any]], topic_tokens: list[str]) -> str:
    cleaned = _clean(text, limit=4000)
    if not cleaned:
        return cleaned
    kept: list[str] = []
    reviewish_roles = {"meta_analysis", "review", "observational", "off_domain_indirect", "unknown"}
    for sentence in _split_sentences(cleaned):
        refs = [ref for ref in _sentence_refs(sentence) if 1 <= ref <= len(source_bundle)]
        if not refs:
            kept.append(sentence)
            continue
        entries = [source_bundle[ref - 1] for ref in refs]
        roles = {str(entry.get("role") or "unknown") for entry in entries}
        if roles.issubset(reviewish_roles):
            if _mentions_topic(sentence, topic_tokens) or any(_entry_title_mentions_topic(entry, topic_tokens) for entry in entries):
                kept.append(sentence)
                continue
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


def _trim_singular_mixed_citations(text: str, source_bundle: list[dict[str, Any]]) -> str:
    cleaned = _clean(text, limit=4000)
    if not cleaned:
        return cleaned
    kept: list[str] = []
    for sentence in _split_sentences(cleaned):
        cluster = _CITATION_CLUSTER_RE.search(sentence)
        if cluster:
            refs = [int(match) for match in re.findall(r"\d+", cluster.group(1)) if 1 <= int(match) <= len(source_bundle)]
        else:
            refs = [ref for ref in _sentence_refs(sentence) if 1 <= ref <= len(source_bundle)]
        if len(refs) < 2 or not cluster or not _SINGULAR_STUDY_RE.search(sentence):
            kept.append(sentence)
            continue
        entries = [source_bundle[ref - 1] for ref in refs]
        mixed = (
            len({str(entry.get("role") or "unknown") for entry in entries}) > 1
            or len({str(entry.get("evidence_tier") or "unknown") for entry in entries}) > 1
            or len({str((entry.get("card") or {}).get("study_type") or "unknown") for entry in entries}) > 1
        )
        if not mixed:
            kept.append(sentence)
            continue
        preferred = [
            ref for ref in refs
            if source_bundle[ref - 1].get("role") == "published_results"
            and source_bundle[ref - 1].get("directness") == "direct"
        ]
        chosen = preferred[0] if preferred else refs[0]
        kept.append(f"{sentence[:cluster.start()]}[{chosen}]{sentence[cluster.end():]}")
    return " ".join(part for part in kept if part).strip()


def _retarget_singular_trial_citations(text: str, source_bundle: list[dict[str, Any]]) -> str:
    cleaned = _clean(text, limit=4000)
    if not cleaned:
        return cleaned
    kept: list[str] = []
    for sentence in _split_sentences(cleaned):
        if not _SINGULAR_STUDY_RE.search(sentence):
            kept.append(sentence)
            continue
        cluster = _ANY_CITATION_RE.search(sentence)
        if not cluster:
            kept.append(sentence)
            continue
        refs = [int(match) for match in re.findall(r"\d+", cluster.group(1)) if 1 <= int(match) <= len(source_bundle)]
        if not refs:
            kept.append(sentence)
            continue
        cited_entries = [source_bundle[ref - 1] for ref in refs]
        if any(
            entry.get("role") == "published_results" and entry.get("directness") == "direct"
            for entry in cited_entries
        ):
            kept.append(sentence)
            continue
        tokens = [
            token for token in re.findall(r"[a-z0-9]+", _strip_citations(sentence, limit=600).lower())
            if len(token) > 3 and token not in _STOPWORDS and token not in _GENERIC_TOPIC_TOKENS
        ]
        best_ref = 0
        best_score = 0
        for idx, entry in enumerate(source_bundle, start=1):
            if entry.get("role") != "published_results" or entry.get("directness") != "direct":
                continue
            hay = " ".join(
                str(v or "").lower()
                for v in (
                    entry.get("title"),
                    entry.get("excerpt"),
                    (entry.get("card") or {}).get("outcomes"),
                    (entry.get("card") or {}).get("population"),
                )
            )
            score = sum(1 for token in tokens if token in hay)
            if score > best_score:
                best_ref = idx
                best_score = score
        if best_ref and best_score >= 2:
            kept.append(f"{sentence[:cluster.start()]}[{best_ref}]{sentence[cluster.end():]}")
            continue
        kept.append(sentence)
    return " ".join(part for part in kept if part).strip()


def _entry_result_sentence(entry: dict[str, Any]) -> str:
    if claim := _claim_from_entry(entry):
        if sentence := _claim_sentence(claim):
            return sentence
    excerpt = _clean(entry.get("excerpt"), limit=700)
    if not excerpt:
        return ""
    sentences = [sentence for sentence in _split_sentences(excerpt, limit=700) if _claim_sentence_quality_ok(sentence)]
    if not sentences:
        return ""
    def _score(sentence: str) -> tuple[int, int, int, int]:
        return (
            1 if _PRIMARY_RESULT_SENTENCE_RE.search(sentence) else 0,
            1 if _STRONG_RESULT_SENTENCE_RE.search(sentence) else 0,
            1 if _RESULT_MARKER_RE.search(sentence) else 0,
            len(sentence),
        )
    best = sorted(sentences, key=_score, reverse=True)[0]
    return _strip_citations(_normalize_numeric_phrase(best), limit=500)


def _best_direct_result_entry(source_bundle: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        entry for entry in source_bundle
        if entry.get("directness") == "direct" and entry.get("role") == "published_results"
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda entry: (
            1 if _claim_schema_ok(_claim_from_entry(entry)) else 0,
            1 if _entry_result_sentence(entry) else 0,
            1 if entry.get("source_type") != "clinicaltrials" else 0,
            float(entry.get("topic_fit") or 0.0),
            float(entry.get("relevance") or 0.0),
            int(entry.get("year") or 0),
        ),
    )


def _bundle_excerpt(item: dict[str, Any]) -> str:
    raw = _clean(item.get("excerpt"), limit=5000)
    if not raw:
        return ""
    structured_parts = _STRUCTURED_RESULT_LABEL_RE.split(raw)
    priority_sentences: list[str] = []
    if len(structured_parts) > 1:
        for i in range(1, len(structured_parts), 2):
            label = structured_parts[i].upper()
            text = structured_parts[i + 1] if i + 1 < len(structured_parts) else ""
            if label not in {"FINDINGS", "RESULTS", "INTERPRETATION", "CONCLUSION", "CONCLUSIONS"}:
                continue
            priority_sentences.extend([part for part in _split_sentences(text, limit=1200) if _claim_sentence_quality_ok(part)])
    def _priority_score(sentence: str) -> tuple[int, int, int, int, int]:
        return (
            1 if _PRIMARY_RESULT_SENTENCE_RE.search(sentence) else 0,
            1 if _STRONG_RESULT_SENTENCE_RE.search(sentence) else 0,
            1 if _OUTCOME_SENTENCE_RE.search(sentence) else 0,
            0 if _SAFETY_EVENT_SENTENCE_RE.search(sentence) else 1,
            0 if _TRIAL_FLOW_SENTENCE_RE.search(sentence) else 1,
            1 if _RESULT_MARKER_RE.search(sentence) else 0,
            len(sentence),
        )
    priority_sentences = sorted(priority_sentences, key=_priority_score, reverse=True)
    sentences = _split_sentences(raw, limit=5000)
    picked: list[str] = []
    length = 0
    for sentence in priority_sentences:
        if length >= 260:
            break
        if sentence in picked:
            continue
        picked.append(sentence)
        length += len(sentence) + 1
    for sentence in sentences:
        if length >= 220:
            break
        if sentence in picked:
            continue
        picked.append(sentence)
        length += len(sentence) + 1
    for sentence in sentences:
        if not _NUMERIC_SENTENCE_RE.search(sentence):
            continue
        if sentence in picked:
            continue
        picked.append(sentence)
        if len(" ".join(picked)) >= 420:
            break
    excerpt = _clean(" ".join(picked) or raw, limit=420)
    effect_spans = []
    for effect in (item.get("extraction") or {}).get("effects") or []:
        span = _normalize_numeric_phrase(_clean(effect.get("source_span"), limit=160), limit=160)
        if span and span.lower() not in excerpt.lower():
            effect_spans.append(span)
    if effect_spans:
        excerpt = _clean(f"{excerpt} {' '.join(effect_spans[:2])}", limit=500)
    return excerpt


def _dedupe(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for item in evidence:
        keys = _duplicate_keys(item)
        if not keys:
            continue
        duplicate_idx = next((seen[key] for key in keys if key in seen), None)
        if duplicate_idx is None:
            kept.append(item)
            idx = len(kept) - 1
            for key in keys:
                seen[key] = idx
            continue
        if _raw_evidence_rank(item) <= _raw_evidence_rank(kept[duplicate_idx]):
            continue
        kept[duplicate_idx] = item
        for key in list(seen):
            if seen[key] == duplicate_idx:
                seen.pop(key)
        for key in keys:
            seen[key] = duplicate_idx
    return kept


def _rank(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _s(item: dict[str, Any]) -> tuple[int, int, int]:
        return (
            int(item.get("year") or 0),
            1 if item.get("evidence_type") == "review" else 0,
            len(_clean(item.get("excerpt"))),
        )

    return sorted(_dedupe(evidence), key=_s, reverse=True)


def _classify_directness(item: dict[str, Any], card: dict[str, Any], domain_slug: str, topic_tokens: list[str]) -> str:
    role = classify_citation_role(item, card, domain_slug, topic_tokens)
    return citation_directness(role, item, card, domain_slug, topic_tokens)


def _relevance(
    item: dict[str, Any],
    topic_tokens: list[str],
    *,
    card: dict[str, Any] | None = None,
    directness: str = "indirect",
    role: str = "unknown",
) -> float:
    title = str(item.get("title") or "").lower()
    card = card or {}
    text = " ".join(
        str(v or "")
        for v in (
            item.get("title"),
            item.get("excerpt"),
            item.get("query"),
            card.get("population"),
            card.get("intervention"),
            card.get("outcomes"),
            card.get("journal"),
        )
    ).lower()
    if not topic_tokens:
        return 0.25
    title_matched = sum(1 for t in topic_tokens if t in title)
    text_matched = sum(1 for t in topic_tokens if t in text)
    if text_matched == 0:
        return 0.1 if directness != "mechanistic" else 0.05
    base = 0.2 + (text_matched / len(topic_tokens)) * 0.25
    if title_matched > 0:
        base += 0.15 + min(0.1, (title_matched / len(topic_tokens)) * 0.1)
    base += {"direct": 0.2, "indirect": 0.05, "mechanistic": 0.0}.get(directness, 0.0)
    if item.get("evidence_type") == "review":
        base += 0.1
    elif item.get("evidence_type") in {"interventional", "observational"}:
        base += 0.05
    if int(item.get("year") or 0) >= 2020:
        base += 0.05
    base += role_relevance_bonus(role)
    return round(min(base, 1.0), 2)


def _bundle_entry(item: dict[str, Any], topic_tokens: list[str], domain_slug: str, *, topic_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    card = build_card(item)
    role = classify_citation_role(item, card, domain_slug, topic_tokens)
    card["role"] = role
    directness = _classify_directness(item, card, domain_slug, topic_tokens)
    card["directness"] = directness
    relevance = _relevance(item, topic_tokens, card=card, directness=directness, role=role)
    topic_meta = topic_meta or _topic_profile(" ".join(topic_tokens))
    topic_fit = _topic_fit_score({**item, "role": role}, card, topic_meta, domain_slug)
    topic_fit_bucket = _topic_fit_bucket(topic_fit)
    intervention_fit = _intervention_fit_level(item, card, topic_meta)
    evidence_tier = _evidence_tier(
        item,
        card,
        role=role,
        directness=directness,
        topic_fit_bucket=topic_fit_bucket,
        intervention_fit=intervention_fit,
    )
    claim = _claim_from_entry({"excerpt": _bundle_excerpt(item), "extraction": item.get("extraction") or {}, "card": card})
    return {
        "title": _clean(item.get("title"), limit=200),
        "excerpt": _bundle_excerpt(item),
        "evidence_type": item.get("evidence_type"),
        "source_type": item.get("source_type"),
        "trial_status": item.get("trial_status"),
        "has_results": bool(item.get("has_results")),
        "year": int(item["year"]) if isinstance(item.get("year"), int) else None,
        "url": item.get("url"),
        "doi": item.get("doi"),
        "query": item.get("query"),
        "extraction": item.get("extraction") or {},
        "deterministic_relevance": relevance,
        "relevance": relevance,
        "topic_fit": topic_fit,
        "deterministic_topic_fit_bucket": topic_fit_bucket,
        "topic_fit_bucket": topic_fit_bucket,
        "deterministic_evidence_tier": evidence_tier,
        "evidence_tier": evidence_tier,
        "deterministic_role": role,
        "role": role,
        "deterministic_directness": directness,
        "directness": directness,
        "claim": claim if _claim_schema_ok(claim) else None,
        "intervention_fit": intervention_fit,
        "card": card,
    }


def _effect_brief(extraction: dict[str, Any]) -> str:
    effects = extraction.get("effects") or []
    if not effects:
        return ""
    parts = []
    for effect in effects[:2]:
        outcome = _clean(effect.get("outcome"), limit=80)
        metric = _clean(effect.get("metric"), limit=20)
        value = _clean(effect.get("value"), limit=20)
        ci_low = _clean(effect.get("ci_low"), limit=20)
        ci_high = _clean(effect.get("ci_high"), limit=20)
        n = _clean(effect.get("n"), limit=20)
        snippet = []
        if outcome:
            snippet.append(outcome)
        if metric and value:
            snippet.append(f"{metric} {value}")
        if ci_low and ci_high:
            snippet.append(f"95% CI {ci_low}-{ci_high}")
        if n:
            snippet.append(f"N={n}")
        parts.append(", ".join(snippet))
    return " | ".join(part for part in parts if part)


def _is_reported_finding(entry: dict[str, Any]) -> bool:
    return entry.get("role") in {"published_results", "meta_analysis", "review", "observational"}


def _sanitize_registry_claims(text: str, blocked_refs: list[int]) -> str:
    cleaned = _clean(text, limit=4000)
    if not cleaned or not blocked_refs:
        return cleaned
    blocked_tags = [f"[{idx}]" for idx in blocked_refs]
    sentences = _split_sentences(cleaned)
    kept = []
    hit_tags: list[str] = []
    for sentence in sentences:
        tags = [tag for tag in blocked_tags if tag in sentence]
        if tags and _OUTCOME_VERB_RE.search(sentence):
            hit_tags.extend(tags)
            continue
        kept.append(sentence)
    if hit_tags:
        refs = ", ".join(dict.fromkeys(hit_tags))
        kept.append(f"Registered studies {refs} describe study design only; outcome results have not been posted.")
    return " ".join(part for part in kept if part).strip()


def _sanitize_published_result_language(text: str, source_bundle: list[dict[str, Any]]) -> str:
    cleaned = _clean(text, limit=4000)
    if not cleaned:
        return cleaned
    sentences = _split_sentences(cleaned)
    kept: list[str] = []
    for sentence in sentences:
        refs = _sentence_refs(sentence)
        if not refs:
            kept.append(sentence)
            continue
        roles = {
            str(source_bundle[ref - 1].get("role") or "unknown")
            for ref in refs
            if 1 <= ref <= len(source_bundle)
        }
        patched = sentence
        if roles & {"published_results", "meta_analysis"}:
            for phrase, replacement in _PUBLISHED_RESULT_REPAIRS.items():
                patched = re.sub(re.escape(phrase), replacement, patched, flags=re.IGNORECASE)
            patched = re.sub(r"\bongoing (RCT|trial)\b", lambda m: f"published {m.group(1)}", patched, flags=re.IGNORECASE)
        kept.append(patched)
    return " ".join(part for part in kept if part).strip()


def _numeric_effect_sentence(index: int, entry: dict[str, Any]) -> str:
    claim = entry.get("claim") or _claim_from_entry(entry)
    if not _claim_schema_ok(claim):
        return ""
    if source_span := _claim_sentence(claim):
        lead = "Meta-analysis" if entry.get("role") == "meta_analysis" else "Published results"
        return f"{lead} [{index}] reported {source_span.rstrip('.')}."
    outcome = _normalize_numeric_phrase(str(claim.get("endpoint") or "reported outcome"), limit=90)
    metric = _normalize_numeric_phrase(str(claim.get("metric") or ""), limit=40).lower()
    effect = _normalize_numeric_phrase(str(claim.get("effect") or ""), limit=140)
    p_value = _clean(claim.get("p_value"), limit=20)
    n = _clean(claim.get("n"), limit=80)
    bits = [f"Published results [{index}] report {outcome}"]
    if metric and effect:
        bits.append(f"{metric} {effect}")
    elif effect:
        bits.append(effect)
    if p_value:
        bits.append(f"p={p_value}")
    if n:
        bits.append(n)
    return "; ".join(bits).strip() + "."


def _excerpt_numeric_sentence(index: int, entry: dict[str, Any]) -> str:
    if claim := _claim_from_entry(entry):
        if source_span := _claim_sentence(claim):
            lead = "Meta-analysis" if str(entry.get("role") or "unknown") == "meta_analysis" else "Published results"
            return f"{lead} [{index}] reported {source_span.rstrip('.')}."
    return ""


def _ground_required_numeric_sentences(text: str, source_bundle: list[dict[str, Any]]) -> str:
    cleaned = _clean(text, limit=4000)
    if not cleaned:
        return cleaned
    sentences = _split_sentences(cleaned)
    kept: list[str] = []
    for sentence in sentences:
        refs = _sentence_refs(sentence)
        if not refs:
            kept.append(sentence)
            continue
        bare = re.sub(r"\[\d+\]", "", sentence)
        replacement = ""
        drop_sentence = False
        grounded = _NUMERIC_CLAIM_RE.search(bare) and _EFFECT_STYLE_RE.search(bare)
        for ref in refs:
            if not (1 <= ref <= len(source_bundle)):
                continue
            entry = source_bundle[ref - 1]
            role = str(entry.get("role") or "unknown")
            if role in {"published_results", "meta_analysis"}:
                effects = ((entry.get("extraction") or {}).get("effects") or [])
                if grounded and (role != "published_results" or _RESULT_MARKER_RE.search(bare)):
                    replacement = sentence
                    break
                if effects:
                    replacement = _numeric_effect_sentence(ref, entry)
                    break
                replacement = _excerpt_numeric_sentence(ref, entry)
                if replacement:
                    break
                if role == "meta_analysis":
                    drop_sentence = True
        if replacement == sentence:
            kept.append(sentence)
            continue
        if replacement:
            kept.append(replacement)
        elif not drop_sentence:
            kept.append(sentence)
    return " ".join(part for part in kept if part).strip()


def _clean_grounding_mashups(text: str, source_bundle: list[dict[str, Any]]) -> str:
    cleaned = _clean(text, limit=4000)
    if not cleaned:
        return cleaned
    sentences = _split_sentences(cleaned)
    kept: list[str] = []
    for idx, sentence in enumerate(sentences):
        next_sentence = sentences[idx + 1] if idx + 1 < len(sentences) else ""
        if sentence.rstrip().lower().endswith("vs.") and re.match(
            r"^(Published results \[\d+\] report|Meta-analysis \[\d+\] reported)",
            next_sentence,
        ):
            continue
        match = re.search(r"(Published results \[\d+\] report .*|Meta-analysis \[\d+\] reported .*)", sentence)
        if match and "vs." in sentence:
            kept.append(match.group(1).strip())
            continue
        refs = [int(m.group(1)) for m in _CITATION_TOKEN_RE.finditer(sentence)]
        roles = {
            str(source_bundle[ref - 1].get("role") or "unknown")
            for ref in refs
            if 1 <= ref <= len(source_bundle)
        }
        if "meta_analysis" in roles and not (_NUMERIC_CLAIM_RE.search(sentence) and _RESULT_MARKER_RE.search(sentence)):
            continue
        kept.append(sentence)
    return " ".join(part for part in kept if part).strip()


def _strip_unsupported_numeric_claims(text: str, source_bundle: list[dict[str, Any]]) -> str:
    cleaned = _clean(text, limit=4000)
    claims = set(_QUANT_LITERAL_RE.findall(cleaned.lower()))
    if not claims:
        return cleaned
    excerpts = [str(entry.get("excerpt") or "").lower() for entry in source_bundle]
    unsupported = {claim for claim in claims if not any(claim in excerpt for excerpt in excerpts)}
    if not unsupported:
        return cleaned
    sentences = _split_sentences(cleaned)
    kept = [sentence for sentence in sentences if not any(claim in sentence.lower() for claim in unsupported)]
    return " ".join(part for part in kept if part).strip()


def _has_quantitative_content(text: str) -> bool:
    cleaned = re.sub(r"\[\d+\]", "", _clean(text, limit=4000))
    return bool(_EFFECT_STYLE_RE.search(cleaned))


def _strip_citations(text: str, *, limit: int = 1200) -> str:
    cleaned = re.sub(r"\[\d+\]", "", text)
    cleaned = re.sub(r"\(\s*[;,]?\s*\)", "", cleaned)
    cleaned = re.sub(r"\bin\s*[,)]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"\s+\)", ")", cleaned)
    return _clean(cleaned, limit=limit)


def _leading_sentences(text: str, count: int = 2, *, limit: int = 700) -> str:
    sentences = _split_sentences(_strip_citations(text, limit=2000), limit=2000)
    return _clean(" ".join(sentences[:count]), limit=limit)


def _human_abstract(topic: str, domain_slug: str, sections: dict[str, str], source_bundle: list[dict[str, Any]]) -> str:
    opener = f"This rapid review evaluates {topic} in the {domain_slug} domain."
    strongest = ""
    if strongest_entry := _best_direct_result_entry(source_bundle):
        strongest = _entry_result_sentence(strongest_entry)
    findings = _leading_sentences(sections.get("Key Findings", ""), count=2, limit=700)
    limitation = _leading_sentences(sections.get("Limitations", ""), count=1, limit=320)
    abstract = _dedupe_repeated_sentences(
        _clean(" ".join(part for part in (opener, strongest, findings, limitation) if part), limit=1200)
    )
    return _complete_sentences(abstract, max_sentences=5, limit=1200)


def _postprocess_sections(
    sections: dict[str, str],
    *,
    source_bundle: list[dict[str, Any]],
    registered_refs: list[int],
    topic_tokens: list[str],
    has_effect_data: bool,
    first_effect_entry: tuple[int, dict[str, Any]] | None,
) -> dict[str, str]:
    polished = dict(sections)
    for heading in ("Search Summary", "Evidence Landscape", "Key Findings", "Limitations", "Conclusion"):
        if heading in polished:
            polished[heading] = _sanitize_published_result_language(polished[heading], source_bundle)
    for heading in ("Evidence Landscape", "Key Findings", "Conclusion"):
        if heading in polished:
            polished[heading] = _sanitize_registry_claims(polished[heading], registered_refs)
    for heading in ("Key Findings", "Conclusion"):
        if heading in polished:
            polished[heading] = _ground_required_numeric_sentences(polished[heading], source_bundle)
            polished[heading] = _clean_grounding_mashups(polished[heading], source_bundle)
            polished[heading] = _retarget_singular_trial_citations(polished[heading], source_bundle)
            polished[heading] = _trim_singular_mixed_citations(polished[heading], source_bundle)
            polished[heading] = _strip_offtopic_claims(polished[heading], source_bundle, topic_tokens)
            polished[heading] = _strip_unsupported_numeric_claims(polished[heading], source_bundle)
    if has_effect_data and not _has_quantitative_content(polished.get("Key Findings", "")) and first_effect_entry:
        polished["Key Findings"] = f"{polished['Key Findings']} {_numeric_effect_sentence(*first_effect_entry)}".strip()
    if not re.search(r"\b(no evidence|remains unsupported|not directly addressed|inconclusive|insufficient)\b", polished.get("Key Findings", ""), re.IGNORECASE):
        polished["Key Findings"] = (
            f"{polished['Key Findings']} No retained study directly addresses integrated healthspan in a general older-adult population."
        ).strip()
    for heading in ("Evidence Landscape", "Key Findings", "Conclusion"):
        if heading in polished:
            polished[heading] = _complete_sentences(_dedupe_repeated_sentences(polished[heading]), limit=4000)
    return polished


def _merge_usage(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        merged[key] = int(merged.get(key, 0) or 0) + int(extra.get(key, 0) or 0)
    return merged


def _editor_bundle_lines(source_bundle: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, entry in enumerate(source_bundle[:12], start=1):
        line = (
            f"[{idx}] tier={entry.get('evidence_tier', 'unknown')}; role={entry.get('role', 'unknown')}; "
            f"directness={entry.get('directness', 'indirect')}; year={entry.get('year', 'unknown')}; "
            f"title={entry.get('title', 'unknown')}"
        )
        result_sentence = _entry_result_sentence(entry)
        if result_sentence:
            line += f"; result={_clean(result_sentence, limit=220)}"
        lines.append(line)
    return "\n".join(lines)


def _candidate_summary_lines(candidates: list[dict[str, Any]], *, limit: int = 16) -> str:
    lines: list[str] = []
    for idx, entry in enumerate(candidates[:limit], start=1):
        card = entry.get("card") or {}
        line = (
            f"id={idx}; title={entry.get('title', 'unknown')}; year={entry.get('year', 'unknown')}; "
            f"evidence_type={entry.get('evidence_type', 'unknown')}; source_type={entry.get('source_type', 'unknown')}; "
            f"role={entry.get('role', 'unknown')}; directness={entry.get('directness', 'indirect')}; "
            f"tier={entry.get('evidence_tier', 'unknown')}; topic_fit_bucket={entry.get('topic_fit_bucket', 'drop')}; "
            f"relevance={entry.get('relevance', 0.0)}"
        )
        for field, label in (("population", "population"), ("intervention", "intervention"), ("outcomes", "outcomes"), ("context", "context")):
            if card.get(field):
                line += f"; {label}={_clean(card[field], limit=120)}"
        excerpt = _clean(entry.get("excerpt"), limit=220)
        if excerpt:
            line += f"; excerpt={excerpt}"
        lines.append(line)
    return "\n".join(lines)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _apply_mimo_rerank(candidates: list[dict[str, Any]], assessments: list[dict[str, Any]]) -> None:
    for assessment in assessments:
        idx = int(assessment.get("id") or 0)
        if idx < 1 or idx > len(candidates):
            continue
        entry = candidates[idx - 1]
        bucket = str(assessment.get("bucket") or "").strip().lower()
        score = max(0.0, min(1.0, _safe_float(assessment.get("relevance_score"), _safe_float(entry.get("relevance"), 0.0))))
        entry["llm_relevance"] = round(score, 2)
        entry["relevance"] = round((_safe_float(entry.get("deterministic_relevance"), _safe_float(entry.get("relevance"), 0.0)) * 0.35) + (score * 0.65), 2)
        if bucket in _VALID_TOPIC_FIT_BUCKETS:
            entry["llm_topic_fit_bucket"] = bucket
            entry["topic_fit_bucket"] = bucket


def _apply_mimo_labels(candidates: list[dict[str, Any]], labels: list[dict[str, Any]]) -> None:
    sticky_roles = {"off_domain_indirect", "animal_model"}
    for label in labels:
        idx = int(label.get("id") or 0)
        if idx < 1 or idx > len(candidates):
            continue
        entry = candidates[idx - 1]
        current_role = str(entry.get("role") or "unknown")
        role = str(label.get("role") or "").strip()
        if current_role not in sticky_roles and role in ROLE_ORDER:
            entry["llm_role"] = role
            entry["role"] = role
            if entry.get("card"):
                entry["card"]["role"] = role
        directness = str(label.get("directness") or "").strip().lower()
        if directness in _VALID_DIRECTNESS:
            if entry.get("role") in {"animal_model", "mechanistic"}:
                directness = "mechanistic"
            elif entry.get("role") in {"registered_pending", "published_protocol", "off_domain_indirect", "unknown"} and directness == "direct":
                directness = "indirect"
            entry["llm_directness"] = directness
            entry["directness"] = directness
            if entry.get("card"):
                entry["card"]["directness"] = directness
        tier = str(label.get("evidence_tier") or "").strip()
        if tier not in _VALID_EVIDENCE_TIERS:
            tier = _evidence_tier(
                {
                    "title": entry.get("title"),
                    "excerpt": entry.get("excerpt"),
                    "evidence_type": entry.get("evidence_type"),
                },
                entry.get("card") or {},
                role=str(entry.get("role") or "unknown"),
                directness=str(entry.get("directness") or "indirect"),
                topic_fit_bucket=str(entry.get("topic_fit_bucket") or "drop"),
                intervention_fit=str(entry.get("intervention_fit") or "none"),
            )
        entry["llm_evidence_tier"] = tier
        entry["evidence_tier"] = tier


def _entry_sort_key(entry: dict[str, Any]) -> tuple[int, int, int, int, float, float, int, int]:
    tier_rank = {
        _TIER_A1: 4,
        _TIER_A2: 3,
        _TIER_B: 2,
        _TIER_C: 1,
    }.get(str(entry.get("evidence_tier") or ""), 0)
    return (
        tier_rank,
        role_sort_priority(str(entry.get("role") or "unknown")),
        1 if entry.get("directness") == "direct" else 0,
        1 if entry.get("intervention_fit") == "exact" else 0,
        1 if entry.get("claim") else 0,
        float(entry.get("topic_fit") or 0.0),
        float(entry.get("relevance") or 0.0),
        int(entry.get("year") or 0),
        1 if entry.get("evidence_type") == "review" else 0,
    )


def _keep_bundle_entry(entry: dict[str, Any]) -> bool:
    role = str(entry.get("role") or "")
    if role in {"off_domain_indirect", "animal_model"}:
        return False
    if str(entry.get("intervention_fit") or "none") == "none":
        return False
    bucket = str(entry.get("topic_fit_bucket") or "drop")
    if bucket == "core":
        return True
    if bucket == "landscape":
        return str(entry.get("evidence_tier") or "") in {_TIER_A2, _TIER_B, _TIER_C}
    return False


def _select_prompt_entries(bundle_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    groups = (
        (_TIER_A1, 4),
        (_TIER_A2, 1),
        (_TIER_B, 1),
        (_TIER_C, 1),
    )
    for tier, limit in groups:
        for entry in bundle_candidates:
            if entry in selected or entry.get("evidence_tier") != tier:
                continue
            selected.append(entry)
            if len([item for item in selected if item.get("evidence_tier") == tier]) >= limit:
                break
            if len(selected) >= 6:
                return selected
    for entry in bundle_candidates:
        if entry in selected:
            continue
        selected.append(entry)
        if len(selected) >= 6:
            return selected
    return selected


def _select_source_bundle(bundle_candidates: list[dict[str, Any]], *, domain_slug: str) -> list[dict[str, Any]]:
    accepted_types = {"review", "primary", "interventional", "observational", "mechanism", "protocol"}
    candidates = [
        entry for entry in bundle_candidates
        if _keep_bundle_entry(entry)
        and entry.get("evidence_type") in accepted_types
        and float(entry.get("relevance") or 0.0) >= 0.25
    ]
    if (domain_slug or "").lower() not in {"longevity", "anti-aging", "anti aging"}:
        return candidates[:RESEARKA_MIN_SOURCES]
    candidates = [
        entry for entry in candidates
        if str(entry.get("evidence_tier") or "") == _TIER_C or _longevity_intent_signal(entry)
    ]
    targets = (
        (_TIER_A1, 4),
        (_TIER_A2, 3),
        (_TIER_B, 3),
        (_TIER_C, 2),
    )
    selected: list[dict[str, Any]] = []
    for tier, limit in targets:
        for entry in candidates:
            if entry in selected or str(entry.get("evidence_tier") or "") != tier:
                continue
            selected.append(entry)
            if len([item for item in selected if item.get("evidence_tier") == tier]) >= limit:
                break
    if len(selected) < RESEARKA_MIN_SOURCES:
        for entry in candidates:
            if entry in selected:
                continue
            selected.append(entry)
            if len(selected) >= RESEARKA_MIN_SOURCES:
                break
    return selected[:RESEARKA_MIN_SOURCES]


class RapidEvidenceDrafter:
    def __init__(self, *, provider: Any) -> None:
        self.provider = provider

    def _rerank_with_mimo(
        self,
        *,
        topic: str,
        domain_slug: str,
        criteria: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[bool, dict[str, Any] | None]:
        if not getattr(self.provider, "supports_reranking", False) or not candidates:
            return False, None
        system_prompt = (
            "You are a relevance judge for a biomedical evidence bundle. Return JSON only with key 'assessments'. "
            "Each assessment must contain: id, relevance_score, bucket. "
            "Use bucket from: core, landscape, drop. "
            "Judge whether each candidate directly helps answer the exact topic/domain/criteria question. "
            "Prefer human older-adult outcome evidence over tangential disease-context or generic reviews. "
            "Do not invent papers or IDs."
        )
        user_prompt = (
            f"Topic: {topic}\nDomain: {domain_slug}\nCriteria: {_clean(criteria, limit=240) or 'None'}\n\n"
            "Rank these candidates by actual usefulness for the question.\n"
            "core = belongs in the main retained bundle\n"
            "landscape = supporting context only\n"
            "drop = too weak, off-scope, or not decision-relevant\n\n"
            f"Candidates:\n{_candidate_summary_lines(candidates, limit=16)}"
        )
        result, _ = self.provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        result = {str(k).lower(): v for k, v in result.items()}
        assessments = result.get("assessments")
        if not isinstance(assessments, list):
            return False, result
        _apply_mimo_rerank(candidates, [item for item in assessments if isinstance(item, dict)])
        return True, result

    def _label_with_mimo(
        self,
        *,
        topic: str,
        domain_slug: str,
        criteria: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[bool, dict[str, Any] | None]:
        if not getattr(self.provider, "supports_labeling", False) or not candidates:
            return False, None
        system_prompt = (
            "You are a citation-role and evidence-tier classifier for a biomedical review. Return JSON only with key 'labels'. "
            "Each label must contain: id, role, directness, evidence_tier. "
            "Valid roles: " + ", ".join(ROLE_ORDER) + ". "
            "Valid directness: direct, indirect, mechanistic. "
            "Valid evidence_tier: Tier A1 direct aging evidence, Tier A2 disease-context human evidence, Tier B supporting human evidence, Tier C protocol/mechanistic support. "
            "Use Tier A1 for core direct aging/older-adult outcome evidence, Tier A2 for direct human disease-context evidence, Tier B for reviews, multi-drug syntheses, or broader supporting human evidence, and Tier C for protocols, registry-only records, mechanistic work, preclinical work, or other indirect support."
        )
        user_prompt = (
            f"Topic: {topic}\nDomain: {domain_slug}\nCriteria: {_clean(criteria, limit=240) or 'None'}\n\n"
            "Assign role, directness, and evidence tier for these retained candidates. "
            "Do not invent IDs or add explanation.\n\n"
            f"Candidates:\n{_candidate_summary_lines(candidates, limit=12)}"
        )
        result, _ = self.provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        result = {str(k).lower(): v for k, v in result.items()}
        labels = result.get("labels")
        if not isinstance(labels, list):
            return False, result
        _apply_mimo_labels(candidates, [item for item in labels if isinstance(item, dict)])
        return True, result

    def _refine_with_editor(
        self,
        *,
        topic: str,
        domain_slug: str,
        criteria: str,
        abstract: str,
        sections: dict[str, str],
        source_bundle: list[dict[str, Any]],
    ) -> tuple[dict[str, str], dict[str, Any] | None]:
        if not getattr(self.provider, "supports_refinement", False):
            return {}, None
        system_prompt = (
            "You are the final editor for a rapid evidence synthesis. Return JSON only with plain-string keys: "
            "abstract, landscape, findings, conclusion. Improve clarity without inventing facts or citations. "
            "Use only the cited evidence already in the draft. The Abstract must contain 4-5 complete sentences, "
            "lead with the overall direction, include the strongest direct result, and avoid truncated fragments. "
            "Do not repeat the same sentence verbatim in both the abstract and Key Findings. "
            "When broader human disease-context evidence appears, label it as Tier A2 disease-context human evidence rather than Tier A1 core aging evidence. "
            "Treat Tier A1 as direct aging evidence, Tier A2 as disease-context human evidence, Tier B as supporting human evidence, and Tier C as protocol/mechanistic support. "
            "Do not cite both a published paper and its preprint variant as parallel flagship evidence if one published version is already present."
        )
        user_prompt = (
            f"Topic: {topic}\nDomain: {domain_slug}\nCriteria: {_clean(criteria, limit=240) or 'None'}\n\n"
            f"Current abstract:\n{abstract}\n\n"
            f"Current Evidence Landscape:\n{sections.get('Evidence Landscape', '')}\n\n"
            f"Current Key Findings:\n{sections.get('Key Findings', '')}\n\n"
            f"Current Conclusion:\n{sections.get('Conclusion', '')}\n\n"
            f"Bundle summary:\n{_editor_bundle_lines(source_bundle)}"
        )
        result, _ = self.provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        result = {str(k).lower(): v for k, v in result.items()}
        updates = {
            "abstract": _clean(result.get("abstract"), limit=1600),
            "landscape": _clean(result.get("landscape"), limit=4000),
            "findings": _clean(result.get("findings"), limit=4000),
            "conclusion": _clean(result.get("conclusion"), limit=2000),
        }
        if not any(updates.values()):
            return {}, result
        return updates, result

    def draft(
        self,
        *,
        topic: str,
        domain_slug: str,
        criteria: str,
        queries: list[str],
        evidence: list[dict[str, Any]],
        all_evidence: list[dict[str, Any]] | None = None,
        topic_profile: dict[str, Any] | None = None,
        revision_feedback: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        topic_meta = _topic_profile(topic, topic_profile)
        topic_tokens = list(topic_meta.get("query_terms") or [])

        bundle_candidates = sorted(
            (_bundle_entry(e, topic_tokens, domain_slug, topic_meta=topic_meta) for e in _rank(all_evidence or evidence)),
            key=_entry_sort_key,
            reverse=True,
        )
        rerank_applied = False
        labeling_applied = False
        rerank_payload: dict[str, Any] | None = None
        label_payload: dict[str, Any] | None = None
        rerank_candidates = bundle_candidates[:16]
        rerank_applied, rerank_payload = self._rerank_with_mimo(
            topic=topic,
            domain_slug=domain_slug,
            criteria=criteria,
            candidates=rerank_candidates,
        )
        if rerank_applied:
            bundle_candidates = sorted(bundle_candidates, key=_entry_sort_key, reverse=True)
        label_candidates = [entry for entry in bundle_candidates if str(entry.get("topic_fit_bucket") or "drop") != "drop"][:12] or bundle_candidates[:12]
        labeling_applied, label_payload = self._label_with_mimo(
            topic=topic,
            domain_slug=domain_slug,
            criteria=criteria,
            candidates=label_candidates,
        )
        if labeling_applied:
            bundle_candidates = sorted(bundle_candidates, key=_entry_sort_key, reverse=True)
        kept_candidates = [entry for entry in bundle_candidates if _keep_bundle_entry(entry)]
        selected = _select_prompt_entries(kept_candidates)
        prompt_entries = [entry for entry in selected if _is_reported_finding(entry)] + [
            entry for entry in selected if not _is_reported_finding(entry)
        ]
        registered_refs = [i for i, entry in enumerate(prompt_entries, start=1) if not _is_reported_finding(entry)]
        first_effect_entry = next(
            (
                (i, entry)
                for i, entry in enumerate(prompt_entries, start=1)
                if _is_reported_finding(entry) and ((entry.get("extraction") or {}).get("effects") or [])
            ),
            None,
        )

        if len(selected) < 2:
            return (
                {
                    "error": "Insufficient evidence for synthesis (fewer than 2 relevant sources retained).",
                    "title": f"Rapid Evidence Synthesis: {_clean(topic, limit=120)}",
                    "sections": {},
                    "source_bundle": [],
                },
                None,
            )

        source_bundle = _select_source_bundle(bundle_candidates, domain_slug=domain_slug)

        rc = sum(1 for e in source_bundle if e.get("evidence_type") == "review")
        pc = sum(1 for e in source_bundle if e.get("evidence_type") in {"primary", "interventional", "observational", "mechanism"})
        direct_ct = sum(1 for e in source_bundle if e.get("directness") == "direct")
        indirect_ct = sum(1 for e in source_bundle if e.get("directness") == "indirect")
        mechanistic_ct = sum(1 for e in source_bundle if e.get("directness") == "mechanistic")

        has_effect_data = any((entry.get("extraction") or {}).get("effects") for entry in prompt_entries if _is_reported_finding(entry))
        system_prompt = (
            "You write cautious research drafts grounded in the supplied evidence. "
            "Return JSON only. Do not use placeholders or revision instructions. "
            "Cite sources inline using [1], [2], etc. to refer to the numbered evidence list. "
            "The Abstract must read like a journal abstract in plain language and must not mention pipeline statistics, receipt counts, or structured extraction counts. "
            "The evidence is grouped by citation role. "
            "Treat the retained bundle as an evidence pyramid: Tier A1 drives the answer, Tier A2 adds one clearly labeled human qualifier, Tier B gives context, and Tier C shows future or mechanistic support. "
            "For published results and meta-analyses, use past-tense outcome language and cite numbers when provided. "
            "Spend most of the Abstract, Key Findings, and Conclusion on Tier A1 direct evidence. "
            "When citing published results or meta-analyses, name the endpoint and include effect direction or numeric outcome, sample size, and duration when available. "
            "Key Findings must open with one synthesis sentence naming the overall direction of the evidence, group the evidence by conclusion rather than listing one study per sentence, and end with one sentence stating what remains unsupported. "
            "For registered or protocol studies, describe only the study design or aim. "
            "Do not say they found, showed, reported, demonstrated, improved, reduced, or increased outcomes. "
            "For animal-model evidence, explicitly hedge with 'in animal models' or 'preclinical'. "
            "For off-domain indirect evidence, name the different context such as oncology, pregnancy, pediatric, or burn care. "
            "For observational evidence, describe associations rather than causal proof. "
            "The 'question' field MUST be a full paragraph of at least 50 words. "
            "Example: 'What are the effects of [intervention] on [outcomes] in [population], "
            "compared to [comparator], as evaluated in [study types] with [time frame]?' "
            "Frame a specific, bounded research question with explicit scope, population, intervention, and outcome. "
            "Return exactly these JSON keys, each a plain string: "
            "question, search_summary, landscape, findings, limitations, gaps_identified, conclusion."
        )
        if has_effect_data:
            system_prompt += " In Key Findings, when Published findings include effect data, cite at least one numeric value from that effect data."
        if revision_feedback:
            system_prompt += " A previous draft had citation-role violations. You must correct every cited sentence to match the cited source role before returning JSON."
        grouped_lines: dict[str, list[str]] = {role: [] for role in ROLE_ORDER}
        for i, e in enumerate(prompt_entries, start=1):
            card = e["card"]
            parts = [f"title={e.get('title', 'unknown')}", f"cite={card.get('citation', 'unknown')}"]
            parts.append(f"role={e.get('role', 'unknown')}")
            parts.append(f"type={card.get('study_type', 'unknown')}")
            parts.append(f"grade={card.get('evidence_grade', 'L')}")
            parts.append(f"directness={e.get('directness', 'indirect')}")
            parts.append(f"tier={e.get('evidence_tier', 'unknown')}")
            if e.get("source_type") == "clinicaltrials":
                parts.append(f"trial_status={e.get('trial_status', 'registered')}")
            if card.get("quality_signal"):
                parts.append(f"quality={card['quality_signal']}")
            parts.append(f"year={e.get('year', 'unknown')}")
            if card.get("journal"):
                parts.append(f"journal={card['journal']}")
            if card.get("population"):
                parts.append(f"pop={card['population']}")
            if card.get("intervention"):
                parts.append(f"intervention={card['intervention']}")
            if card.get("outcomes"):
                parts.append(f"outcomes={card['outcomes']}")
            if card.get("context"):
                parts.append(f"context={card['context']}")
            if card.get("full_text_found"):
                parts.append(f"fulltext={card.get('full_text_source') or 'yes'}")
            if card.get("comparator"):
                parts.append(f"comparator={card['comparator']}")
            if card.get("methods_summary"):
                parts.append(f"methods={_clean(card['methods_summary'], limit=140)}")
            if card.get("risk_of_bias"):
                parts.append(f"bias={_clean(card['risk_of_bias'], limit=100)}")
            if card.get("effects"):
                parts.append(f"effect={_effect_brief(e.get('extraction') or {})}")
                top_span = _clean((e.get("extraction") or {}).get("effects", [{}])[0].get("source_span"), limit=220)
                if top_span:
                    parts.append(f"results_excerpt={top_span}")
            line = f"{i}. {'; '.join(parts)}"
            grouped_lines.setdefault(str(e.get("role") or "unknown"), []).append(line)
        evidence_blocks = []
        for role in ROLE_ORDER:
            lines = grouped_lines.get(role) or []
            if not lines:
                continue
            evidence_blocks.append(role_section_title(role))
            evidence_blocks.extend(lines)
        priority_refs = [
            str(i)
            for i, entry in enumerate(prompt_entries, start=1)
            if entry.get("role") == "published_results" and entry.get("directness") == "direct"
        ][:3]
        user_prompt = (
            f"Topic: {topic}\nDomain: {domain_slug}\nCriteria: {_clean(criteria, limit=240) or 'None'}\nQueries: {' | '.join(queries)}\n\n"
            "CRITICAL: The 'question' field must be at least 50 words. Write a full paragraph: "
            "'What are the effects of [topic] on healthspan outcomes in older adults, compared to placebo, "
            "as evaluated in randomized controlled trials with an intervention duration of at least 6 months, "
            "and what is the evidence for safety and efficacy?'\n"
            "The Abstract must sound like a real journal abstract, not a pipeline log.\n"
            "Key Findings must synthesize across sources, not list papers one by one.\n"
            "Only Tier A1 should drive the headline claim; Tier A2/B/C can qualify, contextualize, or show what comes next.\n\nEvidence:\n"
            + ("\n".join(evidence_blocks) or "No evidence receipts retained.")
        )
        if priority_refs:
            user_prompt += (
                f"\n\nKEY FINDINGS PRIORITY: focus mainly on direct published-results citations "
                f"[{'], ['.join(priority_refs)}]. Keep indirect context brief and explicitly labeled indirect."
            )
        if revision_feedback:
            user_prompt += f"\n\nREVISION FEEDBACK:\n{_clean(revision_feedback, limit=1200)}"
        result, raw_payload = self.provider.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        result = {str(k).lower(): v for k, v in result.items()}
        fb_ctx = {
            "topic": topic, "domain": domain_slug,
            "today": datetime.now(timezone.utc).date().isoformat(),
            "nq": str(len(queries)), "nr": str(len(source_bundle)),
            "rv": str(rc), "pr": str(pc),
            "titles": "; ".join(_clean(e.get("title"), limit=110) for e in source_bundle[:3]) or "the retained evidence bundle",
        }
        fallback_count = 0
        sections: dict[str, str] = {}
        for heading, field in SECTION_FIELDS:
            raw = result.get(field, "")
            fallback = _FALLBACKS.get(heading, _GENERIC_FALLBACK).format(**fb_ctx)
            c = _clean(raw, limit=4000)
            picked = fallback if not c or any(t in c.lower() for t in LEAKY_PHRASES) else c
            if picked == fallback:
                fallback_count += 1
            sections[heading] = picked

        sections = _postprocess_sections(
            sections,
            source_bundle=source_bundle,
            registered_refs=registered_refs,
            topic_tokens=topic_tokens,
            has_effect_data=has_effect_data,
            first_effect_entry=first_effect_entry,
        )

        if fallback_count >= 6:
            return (
                {"error": "Model contributed no usable content — all sections fell back to templates."},
                raw_payload,
            )

        # enforce RQ minimum word count for Researka intake
        rq_text = sections.get("Research Question", "")
        if len(rq_text.split()) < 50:
            scope_hint = f"for the {domain_slug} domain" if domain_slug != "general" else ""
            sections["Research Question"] = (
                f"{rq_text} This synthesis specifically examines the available public-index evidence {scope_hint}, "
                f"considering the quality, recency, and directness of the retained receipts, "
                f"to determine whether the current literature supports actionable conclusions for practitioners and researchers."
            ).strip()

        abstract = _human_abstract(topic, domain_slug, sections, source_bundle)
        editor_updates, editor_payload = self._refine_with_editor(
            topic=topic,
            domain_slug=domain_slug,
            criteria=criteria,
            abstract=abstract,
            sections=sections,
            source_bundle=source_bundle,
        )
        if editor_updates:
            if editor_updates.get("landscape"):
                sections["Evidence Landscape"] = editor_updates["landscape"]
            if editor_updates.get("findings"):
                sections["Key Findings"] = editor_updates["findings"]
            if editor_updates.get("conclusion"):
                sections["Conclusion"] = editor_updates["conclusion"]
            sections = _postprocess_sections(
                sections,
                source_bundle=source_bundle,
                registered_refs=registered_refs,
                topic_tokens=topic_tokens,
                has_effect_data=has_effect_data,
                first_effect_entry=first_effect_entry,
            )
            if editor_updates.get("abstract"):
                abstract = editor_updates["abstract"]
        abstract = _complete_sentences(_dedupe_repeated_sentences(abstract), max_sentences=5, limit=1200)
        if editor_updates:
            abstract = _drop_shared_sentences(abstract, sections.get("Key Findings", ""), limit=1200)
        if not abstract:
            abstract = _human_abstract(topic, domain_slug, sections, source_bundle)
        if editor_payload:
            result["usage"] = _merge_usage(result.get("usage", {}), editor_payload.get("usage", {}))
            result["estimated_cost_usd"] = float(result.get("estimated_cost_usd", 0.0) or 0.0) + float(editor_payload.get("estimated_cost_usd", 0.0) or 0.0)
            result["editor_refinement_applied"] = True
        if rerank_payload:
            result["usage"] = _merge_usage(result.get("usage", {}), rerank_payload.get("usage", {}))
            result["estimated_cost_usd"] = float(result.get("estimated_cost_usd", 0.0) or 0.0) + float(rerank_payload.get("estimated_cost_usd", 0.0) or 0.0)
        if label_payload:
            result["usage"] = _merge_usage(result.get("usage", {}), label_payload.get("usage", {}))
            result["estimated_cost_usd"] = float(result.get("estimated_cost_usd", 0.0) or 0.0) + float(label_payload.get("estimated_cost_usd", 0.0) or 0.0)

        if len(source_bundle) < RESEARKA_MIN_SOURCES and os.getenv("RESEARKA_URL"):
            return (
                {
                    "error": f"Insufficient relevant sources for submission ({len(source_bundle)}/{RESEARKA_MIN_SOURCES}).",
                    "source_bundle": source_bundle,
                    "rerank_applied": rerank_applied,
                    "labeling_applied": labeling_applied,
                    "editor_refinement_applied": bool(result.get("editor_refinement_applied")),
                },
                raw_payload,
            )
        artifact = {
            "title": f"Rapid Evidence Synthesis: {_clean(topic, limit=120)}",
            "abstract": abstract,
            "domain_slug": _clean(domain_slug, limit=48).lower() or "general",
            "sections": sections,
            "source_bundle": source_bundle,
            "bundle_profile": {
                "review_count": rc,
                "primary_count": pc,
                "direct_count": direct_ct,
                "indirect_count": indirect_ct,
                "mechanistic_count": mechanistic_ct,
            },
            "prompt_version": result.get("prompt_version", getattr(self.provider, "prompt_version", "unknown")),
            "usage": result.get("usage", {}),
            "estimated_cost_usd": float(result.get("estimated_cost_usd", 0.0) or 0.0),
            "model": result.get("model", getattr(self.provider, "model", "unknown")),
            "rerank_applied": rerank_applied,
            "labeling_applied": labeling_applied,
            "editor_refinement_applied": bool(result.get("editor_refinement_applied")),
        }
        artifact["citation_violations"] = validate_citations(artifact, source_bundle)
        artifact["high_severity_citation_count"] = sum(
            1 for violation in artifact["citation_violations"] if violation.get("severity") == "high"
        )
        return (artifact, raw_payload)
