"""Shared source-topic specificity checks for v3 corpus repair/seeding."""
from __future__ import annotations

import re
from collections.abc import Iterable

MIN_GENERATED_PACK_CANDIDATES = 10
MIN_GENERATED_PACK_TOKENS = 3

TOPIC_STOPWORDS = {
    "aging", "ageing", "longevity", "research", "synthesis", "paper",
    "effect", "effects", "therapy", "treatment", "evidence",
}

BIOMED_ANCHORS = {
    "adult", "aged", "animal", "biomarker", "cell", "clinical", "cohort",
    "disease", "health", "human", "inflammation", "intervention", "mice",
    "mouse", "patient", "randomized", "rat", "review", "trial",
}

DRIFT_RESCUE_ANCHORS = {
    "adult", "aged", "animal", "clinical", "cohort", "human", "intervention",
    "mice", "mouse", "patient", "randomized", "rat", "trial",
}

NON_BIOMED_DRIFT = {
    "alloy", "adsorption", "astrophys", "battery", "catalyst", "cheminform",
    "crop", "electrode", "fuel cell", "fruit", "geolog", "ionomer", "metal",
    "oxide", "photocatal", "plant", "semiconductor", "silicon",
    "supercapacitor", "trapping",
}


def topic_tokens(topic: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9]+", topic.replace("_", " ").lower())
        if len(token) > 3 and token not in TOPIC_STOPWORDS
    ]


def is_source_topic_specific(topic: str, text: str, *, aliases: Iterable[str] = ()) -> bool:
    haystack = " ".join(str(text or "").lower().split())
    tokens = topic_tokens(topic)
    if not haystack or not tokens:
        return True
    token_hits = sum(1 for token in tokens if token in haystack)
    alias_hit = any(str(alias or "").lower() in haystack for alias in aliases if str(alias or "").strip())
    biomed = any(anchor in haystack for anchor in BIOMED_ANCHORS)
    drift = any(term in haystack for term in NON_BIOMED_DRIFT)
    if drift and not any(anchor in haystack for anchor in DRIFT_RESCUE_ANCHORS):
        return False
    return alias_hit or token_hits == len(tokens) or (biomed and token_hits > 0)


def generated_pack_publishable(record: dict[str, object]) -> bool:
    """Generated packs need enough facts plus structurally specific terms."""
    pack_data = record.get("pack_data") if isinstance(record.get("pack_data"), dict) else record
    raw_count = record.get("candidate_count")
    candidate_count = raw_count if isinstance(raw_count, int) else 0
    raw_terms = list(pack_data.get("aliases", ())) if isinstance(pack_data, dict) else []
    retrieval = pack_data.get("retrieval") if isinstance(pack_data, dict) else {}
    if isinstance(retrieval, dict) and isinstance(retrieval.get("topic_terms"), list | tuple):
        raw_terms.extend(retrieval["topic_terms"])
    if candidate_count < MIN_GENERATED_PACK_CANDIDATES or not raw_terms:
        return False
    terms = {
        token
        for term in raw_terms
        for token in re.findall(r"[a-z0-9]+", str(term).lower())
        if token
    }
    entity_like = any(
        any(ch.isdigit() for ch in str(term))
        or any(ch.isupper() for ch in str(term)[1:])
        or "-" in str(term)
        for term in raw_terms
    )
    return len(terms) >= MIN_GENERATED_PACK_TOKENS or entity_like
