"""Shared source-topic specificity checks for v3 corpus repair/seeding."""
from __future__ import annotations

import re
import json
import tomllib
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIN_GENERATED_PACK_CANDIDATES = 10
MIN_SPECIFIC_GENERATED_PACK_CANDIDATES = 3
MIN_GENERATED_PACK_TOKENS = 2

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


def topic_aliases(
    topic: str, *, root: Path | None = None, include_generated_terms: bool = True,
) -> tuple[str, ...]:
    """Load local/generated topic aliases without making specificity topic-specific."""
    base = root or ROOT
    out: list[str] = [topic, topic.replace("_", " ")]
    try:
        pack = tomllib.loads((base / "topic_packs" / f"{topic}.toml").read_text(encoding="utf-8"))
        out.extend(alias for alias in pack.get("aliases", []) if isinstance(alias, str))
    except (OSError, tomllib.TOMLDecodeError):
        pass
    if include_generated_terms:
        try:
            record = json.loads((base / "topic_packs_db" / topic / "latest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            record = {}
        pack_data = record.get("pack_data") if isinstance(record.get("pack_data"), dict) else {}
        if isinstance(pack_data, dict):
            out.extend(alias for alias in pack_data.get("aliases", []) if isinstance(alias, str))
            retrieval = pack_data.get("retrieval")
            if isinstance(retrieval, dict):
                out.extend(term for term in retrieval.get("topic_terms", []) if isinstance(term, str))
    seen: set[str] = set()
    aliases: list[str] = []
    for alias in (item.strip().lower() for item in out):
        if alias and alias not in seen:
            seen.add(alias)
            aliases.append(alias)
    return tuple(aliases)


def source_gate_aliases(topic: str, aliases: Iterable[str]) -> tuple[str, ...]:
    """Keep aliases that name the topic, not broad retrieval axes.

    Generated packs often carry helpful retrieval terms such as "blood pressure"
    or "sleep". Those improve search breadth but are too broad for source
    admission. A source-gate alias must overlap the topic text itself.
    """
    topic_text = " ".join(topic.replace("_", " ").replace("-", " ").lower().split())
    topic_raw_tokens = {
        token for token in re.findall(r"[a-z0-9]+", topic_text)
        if len(token) > 2 and token not in TOPIC_STOPWORDS
    }
    out: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        norm = " ".join(str(alias or "").replace("_", " ").replace("-", " ").lower().split())
        if not norm:
            continue
        alias_tokens = {
            token for token in re.findall(r"[a-z0-9]+", norm)
            if len(token) > 2 and token not in TOPIC_STOPWORDS
        }
        if norm in topic_text or topic_text in norm or topic_raw_tokens & alias_tokens:
            if norm not in seen:
                seen.add(norm)
                out.append(str(alias))
    return tuple(out)


def is_source_topic_specific(topic: str, text: str, *, aliases: Iterable[str] = ()) -> bool:
    haystack = " ".join(str(text or "").replace("_", " ").replace("-", " ").lower().split())
    tokens = topic_tokens(topic)
    if not haystack or not tokens:
        return True
    token_hits = sum(1 for token in tokens if token in haystack)
    alias_hit = any(
        " ".join(str(alias or "").replace("_", " ").replace("-", " ").lower().split()) in haystack
        for alias in aliases
        if str(alias or "").strip()
    )
    biomed = any(anchor in haystack for anchor in BIOMED_ANCHORS)
    drift = any(term in haystack for term in NON_BIOMED_DRIFT)
    if drift and not any(anchor in haystack for anchor in DRIFT_RESCUE_ANCHORS):
        return False
    if alias_hit or token_hits == len(tokens):
        return True
    specific_hits = [token for token in tokens if token in haystack and token not in BIOMED_ANCHORS]
    missing_tokens = [token for token in tokens if token not in haystack]
    if specific_hits and all(token in BIOMED_ANCHORS for token in missing_tokens):
        return True
    # Single-token topics can be specific with a biomedical anchor. Multi-token
    # topics need more than one generic biomedical word; otherwise broad source
    # bundles like "inflammation" swamp named interventions such as naltrexone.
    return biomed and len(tokens) == 1 and token_hits > 0


def generated_pack_publishable(
    record: dict[str, object],
    *,
    peer_records: Sequence[dict[str, object]] = (),
) -> bool:
    """Generated packs need fact support plus peer-relative specificity."""
    pack_data = record.get("pack_data") if isinstance(record.get("pack_data"), dict) else record
    raw_count = record.get("candidate_count")
    candidate_count = raw_count if isinstance(raw_count, int) else 0
    topic = str(pack_data.get("topic") or "") if isinstance(pack_data, dict) else ""
    if _generic_fallback_topic(topic):
        return False
    raw_terms = list(pack_data.get("aliases", ())) if isinstance(pack_data, dict) else []
    retrieval = pack_data.get("retrieval") if isinstance(pack_data, dict) else {}
    if isinstance(retrieval, dict) and isinstance(retrieval.get("topic_terms"), list | tuple):
        raw_terms.extend(retrieval["topic_terms"])
    if not raw_terms:
        return False
    terms = _pack_tokens(raw_terms)
    scope_terms = _pack_tokens(retrieval.get("scope_terms", ())) if isinstance(retrieval, dict) else set()
    entity_like = any(
        any(ch.isdigit() for ch in str(term))
        or any(ch.isupper() for ch in str(term)[1:])
        or "-" in str(term)
        for term in raw_terms
    )
    rare_terms = _peer_rare_tokens(terms, peer_records) - scope_terms - BIOMED_ANCHORS
    structurally_specific = bool(
        entity_like
        or rare_terms
        or (not peer_records and len(terms - scope_terms) >= MIN_GENERATED_PACK_TOKENS)
    )
    floor = (
        MIN_SPECIFIC_GENERATED_PACK_CANDIDATES
        if structurally_specific
        else MIN_GENERATED_PACK_CANDIDATES
    )
    enough_terms = len(terms) >= MIN_GENERATED_PACK_TOKENS or (
        structurally_specific and candidate_count >= MIN_GENERATED_PACK_CANDIDATES
    )
    return candidate_count >= floor and enough_terms and structurally_specific


def _generic_fallback_topic(topic: str) -> bool:
    return topic.endswith("_aging_evidence") or topic.endswith(" aging evidence")


def _pack_tokens(raw_terms: Iterable[object]) -> set[str]:
    return {
        _normalize_pack_token(token)
        for term in raw_terms
        for token in re.findall(r"[a-z0-9]+", str(term).lower())
        if len(token) > 2 and token not in TOPIC_STOPWORDS
    }


def _normalize_pack_token(token: str) -> str:
    """Collapse simple plural variants so scope/peer checks stay structural."""
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
        return token[:-1]
    return token


def _peer_rare_tokens(terms: set[str], peer_records: Sequence[dict[str, object]]) -> set[str]:
    if not peer_records:
        return set()
    counts: Counter[str] = Counter()
    for record in peer_records:
        pack_data = record.get("pack_data") if isinstance(record.get("pack_data"), dict) else record
        raw_terms = list(pack_data.get("aliases", ())) if isinstance(pack_data, dict) else []
        retrieval = pack_data.get("retrieval") if isinstance(pack_data, dict) else {}
        if isinstance(retrieval, dict) and isinstance(retrieval.get("topic_terms"), list | tuple):
            raw_terms.extend(retrieval["topic_terms"])
        counts.update(_pack_tokens(raw_terms))
    common_cutoff = max(3, int(len(peer_records) * 0.12))
    return {token for token in terms if counts[token] <= common_cutoff}
