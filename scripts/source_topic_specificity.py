"""Shared source-topic specificity checks for v3 corpus repair/seeding."""
from __future__ import annotations

import re
from collections.abc import Iterable

TOPIC_STOPWORDS = {
    "aging", "ageing", "longevity", "research", "synthesis", "paper",
    "effect", "effects", "therapy", "treatment", "evidence",
}

BIOMED_ANCHORS = {
    "adult", "aged", "animal", "biomarker", "cell", "clinical", "cohort",
    "disease", "health", "human", "inflammation", "intervention", "mice",
    "mouse", "patient", "randomized", "rat", "review", "trial",
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
    if drift and not biomed:
        return False
    return alias_hit or token_hits == len(tokens) or (biomed and token_hits > 0)
