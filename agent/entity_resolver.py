from __future__ import annotations

from difflib import SequenceMatcher, get_close_matches
import re
from typing import Any


_GENERIC_TOKENS = {
    "and", "or", "anti", "aging", "anti-aging", "longevity", "healthspan", "effects", "effect",
    "outcomes", "outcome", "clinical", "trial", "trials", "adults", "adult", "human", "humans",
    "studies", "study", "relevance", "evidence", "older", "patients", "patient",
}
_COMPOUND_SUFFIXES = ("mab", "nib", "mycin", "imus", "formin", "glutide", "statin")
_KNOWN_COMPOUNDS = {
    "rapamycin", "sirolimus", "everolimus", "metformin", "acarbose", "resveratrol",
    "spermidine", "semaglutide", "tirzepatide", "glp1", "nmn", "nr", "omega3", "epa", "dha",
    "senolytic", "senolytics", "taurine", "urolithina",
}
_ALIASES = {
    "evrolimus": "everolimus",
    "sirolimus": "rapamycin",
    "glucophage": "metformin",
    "sglt2": "sglt2",
    "sglt2i": "sglt2",
    "sglt": "sglt2",
    "glp1": "glp1",
    "glp1ra": "glp1",
    "glp": "glp1",
    "omega3": "omega3",
    "epa": "omega3",
    "dha": "omega3",
    "senolytics": "senolytic",
    "d+q": "senolytic",
    "urolithin": "urolithina",
    "donanemab": "donanemab",
    "lecanemab": "donanemab",
    "aducanumab": "donanemab",
}
_CANONICAL_ALIASES = {
    "rapamycin": ["sirolimus"],
    "everolimus": [],
    "metformin": ["glucophage"],
    "senolytic": ["senolytics", "d+q", "dasatinib", "quercetin", "fisetin", "navitoclax"],
    "nmn": ["nicotinamide mononucleotide"],
    "nr": ["nicotinamide riboside"],
    "omega3": ["omega-3", "epa", "dha", "fish oil"],
    "taurine": [],
    "urolithina": ["urolithin a"],
}
_CLASS_TERMS = {
    "rapamycin": ["mtor inhibitor", "mtor inhibitors", "rapalog", "rapalogs"],
    "everolimus": ["mtor inhibitor", "mtor inhibitors", "rapalog", "rapalogs"],
    "metformin": ["biguanide", "biguanides", "glucose-lowering medication", "glucose lowering medication"],
    "senolytic": ["senolytic", "senolytics", "senolytic therapy", "senolytic therapies"],
    "nmn": ["nad precursor", "nad precursors"],
    "nr": ["nad precursor", "nad precursors"],
    "glp1": ["glp-1 agonist", "glp-1 agonists", "glp1 agonist", "glp1 agonists", "incretin"],
    "sglt2": ["sglt2 inhibitor", "sglt2 inhibitors", "gliflozin"],
    "omega3": ["polyunsaturated fatty acid", "omega-3 fatty acid", "omega-3 fatty acids"],
}
_COMPOUND_CLASS_MEMBERS = {
    "donanemab": ["lecanemab", "aducanumab", "bapineuzumab", "solanezumab", "gantenerumab",
                  "anti-amyloid", "anti-amyloid antibody", "anti-amyloid therapy", "amyloid antibody",
                  "amyloid"],
    "glp1": ["semaglutide", "liraglutide", "dulaglutide", "exenatide", "tirzepatide",
             "glp-1 agonist", "glp1 agonist", "glp-1 agonists", "glp1 agonists",
             "glp-1 receptor agonist", "glp1 receptor agonist",
             "glp-1 receptor agonists", "glp1 receptor agonists",
             "glucagon-like peptide", "glucagon-like peptide-1",
             "glp1ras", "gip/glp", "gip-glp",
             "incretin", "incretin therapy", "incretin-based"],
    "sglt2": ["empagliflozin", "dapagliflozin", "canagliflozin",
              "sglt2 inhibitor", "gliflozin", "sodium-glucose cotransporter-2"],
    "omega3": ["omega-3", "eicosapentaenoic acid", "docosahexaenoic acid", "epa", "dha", "fish oil"],
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _tokens(text: str) -> list[str]:
    raw_tokens = [tok for tok in re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split() if tok]
    combined: list[str] = []
    i = 0
    while i < len(raw_tokens):
        current = raw_tokens[i]
        nxt = raw_tokens[i + 1] if i + 1 < len(raw_tokens) else ""
        if (current, nxt) in {("glp", "1"), ("omega", "3"), ("sglt", "2")}:
            combined.append(f"{current}{nxt}")
            i += 2
            continue
        combined.append(current)
        i += 1
    return combined


def _compound_focus(topic: str) -> str | None:
    tokens = [tok for tok in _tokens(topic) if tok not in _GENERIC_TOKENS]
    if not tokens:
        return None
    for tok in tokens:
        if tok.isdigit():
            continue
        if tok in _ALIASES or tok in _KNOWN_COMPOUNDS or tok.endswith(_COMPOUND_SUFFIXES) or any(ch.isdigit() for ch in tok):
            return tok
    return None


def _replace_focus(topic: str, old: str, new: str) -> str:
    return re.sub(rf"\b{re.escape(old)}\b", new, topic, count=1, flags=re.IGNORECASE)


def resolve_topic(topic: str, *, chembl_client: Any | None = None) -> dict[str, Any]:
    raw = " ".join(str(topic or "").split()).strip()
    focus = _compound_focus(raw)
    resolution = {
        "raw_topic": raw,
        "canonical_topic": raw,
        "canonical_term": focus or raw,
        "did_you_mean": None,
        "confidence": 1.0 if raw else 0.0,
        "entity_type": "general",
        "resolver_source": "identity",
        "aliases": [],
        "class_terms": [],
        "blocked": False,
    }
    if not raw or not focus:
        return resolution

    resolution["entity_type"] = "compound"
    alias_hit = _ALIASES.get(_normalize(focus))
    if alias_hit:
        canonical_topic = _replace_focus(raw, focus, alias_hit)
        aliases = list(dict.fromkeys([a for a in ([focus] if focus != alias_hit else []) + _CANONICAL_ALIASES.get(alias_hit, []) if a != alias_hit]))
        resolution.update(
            {
                "canonical_topic": canonical_topic,
                "canonical_term": alias_hit,
                "did_you_mean": canonical_topic if canonical_topic.lower() != raw.lower() else None,
                "confidence": 0.99,
                "resolver_source": "alias_map",
                "aliases": aliases,
                "class_terms": list(dict.fromkeys(_CLASS_TERMS.get(alias_hit, []) + _COMPOUND_CLASS_MEMBERS.get(alias_hit, []))),
            }
        )
        return resolution

    if _normalize(focus) in _KNOWN_COMPOUNDS:
        canonical = _normalize(focus)
        aliases = list(dict.fromkeys(_CANONICAL_ALIASES.get(canonical, [])))
        resolution.update(
            {
                "canonical_topic": raw,
                "canonical_term": canonical,
                "did_you_mean": None,
                "confidence": 0.95,
                "resolver_source": "known_compound",
                "aliases": aliases,
                "class_terms": list(dict.fromkeys(_CLASS_TERMS.get(canonical, []) + _COMPOUND_CLASS_MEMBERS.get(canonical, []))),
            }
        )
        return resolution

    if chembl_client and hasattr(chembl_client, "resolve"):
        match = chembl_client.resolve(focus)
        if match:
            canonical = str(match.get("canonical_name") or focus).lower()
            canonical_topic = _replace_focus(raw, focus, canonical)
            aliases = list(dict.fromkeys(([focus] if canonical != focus else []) + _CANONICAL_ALIASES.get(canonical, [])))
            resolution.update(
                {
                    "canonical_topic": canonical_topic,
                    "canonical_term": canonical,
                    "did_you_mean": canonical_topic if canonical_topic.lower() != raw.lower() else None,
                    "confidence": float(match.get("confidence") or 0.0),
                    "resolver_source": "chembl",
                    "aliases": aliases,
                    "class_terms": list(dict.fromkeys(_CLASS_TERMS.get(canonical, []) + _COMPOUND_CLASS_MEMBERS.get(canonical, []))),
                }
            )
            return resolution

    known = sorted(set(_ALIASES) | set(_ALIASES.values()))
    close = get_close_matches(_normalize(focus), known, n=1, cutoff=0.86)
    if close:
        canonical = _ALIASES.get(close[0], close[0])
        canonical_topic = _replace_focus(raw, focus, canonical)
        aliases = list(dict.fromkeys([focus] + _CANONICAL_ALIASES.get(canonical, [])))
        resolution.update(
            {
                "canonical_topic": canonical_topic,
                "canonical_term": canonical,
                "did_you_mean": canonical_topic,
                "confidence": round(SequenceMatcher(None, _normalize(focus), _normalize(canonical)).ratio(), 3),
                "resolver_source": "fuzzy_alias",
                "aliases": aliases,
                "class_terms": list(dict.fromkeys(_CLASS_TERMS.get(canonical, []) + _COMPOUND_CLASS_MEMBERS.get(canonical, []))),
            }
        )
        return resolution

    resolution.update(
        {
            "confidence": 0.0,
            "resolver_source": "unresolved",
            "blocked": True,
        }
    )
    return resolution


def topic_match_ratio(entries: list[dict[str, Any]], *, canonical_term: str, aliases: list[str] | None = None) -> float:
    terms = {_normalize(canonical_term)}
    for alias in aliases or []:
        normalized = _normalize(alias)
        if normalized:
            terms.add(normalized)
    if not terms or not entries:
        return 0.0
    hits = 0
    for entry in entries:
        text = _normalize(f"{entry.get('title', '')} {entry.get('excerpt', '')}")
        if any(term and term in text for term in terms):
            hits += 1
    return round(hits / len(entries), 3)
