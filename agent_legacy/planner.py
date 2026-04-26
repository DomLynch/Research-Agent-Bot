from __future__ import annotations

import re
from typing import Any


DOMAIN_HINTS = {
    "longevity": ("aging", "healthspan", "older adults"),
    "oncology": ("cancer", "clinical outcomes", "patients"),
    "metabolic": ("metabolic disease", "cardiometabolic", "adults"),
    "general": ("evidence", "outcomes", "adults"),
}
_HUMAN = ("human", "humans", "patient", "patients", "adult", "adults", "clinical")
_ANIMAL = (
    "animal", "animals", "mouse", "mice", "murine", "rat", "rats",
    "c. elegans", "c elegans", "caenorhabditis", "drosophila", "zebrafish",
)
_TITLE_NON_HUMAN_RE = re.compile(
    r"\b(?:c\.?\s*elegans|caenorhabditis|mouse|mice|murine|rat|rats|drosophila|zebrafish)\b",
    re.IGNORECASE,
)

_BASE_NEGATIVE = [
    "cooking", "cook", "recipe", "recipes",
    "sports", "football", "basketball",
    "engineering", "automotive", "fashion",
    "gaming", "real estate", "agriculture", "construction",
    "case law", "court ruling", "judicial", "statute", "legislation",
    "patent law", "tort", "legal precedent",
]

DOMAIN_NEGATIVE_FILTERS: dict[str, list[str]] = {
    "longevity": list(_BASE_NEGATIVE),
    "oncology": list(_BASE_NEGATIVE),
    "metabolic": list(_BASE_NEGATIVE),
    "general": list(_BASE_NEGATIVE),
}


def _should_filter_entry(entry: dict[str, Any], domain_slug: str) -> bool:
    filters = DOMAIN_NEGATIVE_FILTERS.get(domain_slug, DOMAIN_NEGATIVE_FILTERS["general"])
    text = " ".join(str(entry.get(k) or "") for k in ("title", "excerpt")).lower()
    return any(f in text for f in filters)


def _clean(value: Any, limit: int = 160) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


_STOPWORDS = {"and", "in", "for", "of", "the", "with", "on", "to", "a", "an"}


def _parse_scope(text: str) -> dict[str, Any]:
    t = _clean(text, limit=200).lower()
    ym = re.search(
        r"(?:\b(20\d{2})(?:\+|\s*onward(?:s)?)|"
        r"\b(?:since|after|from)\s+(20\d{2})\b|"
        r"\bpost[-\s]?(20\d{2})\b|"
        r"(?:≥|>=)\s*(20\d{2})\b)",
        t,
    )
    year_min = next((int(g) for g in ym.groups() if g), None) if ym else None
    scope: dict[str, Any] = {
        "year_min": year_min,
        "human_only": any(w in t for w in ("human", "humans", "clinical", "patient", "patients", "adult", "adults")),
        "review_only": any(w in t for w in ("systematic review", "meta-analysis", "review only", "reviews only")),
        "primary_only": any(w in t for w in ("primary", "trial", "cohort", "rct", "randomized", "randomised")),
        "safety_focus": any(w in t for w in ("safety", "adverse", "toxicity", "risk", "risks")),
        "mechanism_focus": any(w in t for w in ("mechanism", "mechanistic", "pathway", "pathways")),
    }
    if scope["review_only"] and scope["primary_only"]:
        scope["review_only"] = False
        scope["primary_only"] = False
    return scope


def _scope_signals(scope: dict[str, Any]) -> list[str]:
    out = []
    if scope["year_min"]:
        out.append(f"year>={scope['year_min']}")
    for key in ("human_only", "review_only", "primary_only", "safety_focus", "mechanism_focus"):
        if scope[key]:
            out.append(key)
    return out


def _score(item: dict[str, Any], scope: dict[str, Any], topic_tokens: list[str] | None = None) -> int:
    text = " ".join(str(item.get(k) or "") for k in ("title", "excerpt", "query")).lower()
    year = int(item.get("year") or 0)
    s = 0
    if topic_tokens:
        matched = sum(1 for t in topic_tokens if t in text)
        if matched == len(topic_tokens):
            s += 3
        elif matched > 0:
            s += 1
    if scope["year_min"] and year >= scope["year_min"]:
        s += 4
    if scope["human_only"]:
        if not any(t in text for t in ("without human", "no human", "animal-only", "animal only")):
            if any(t in text for t in _HUMAN) or not any(t in text for t in _ANIMAL):
                s += 3
    if scope["review_only"] and item.get("evidence_type") == "review":
        s += 2
    if scope["primary_only"] and item.get("evidence_type") == "primary":
        s += 2
    if scope["safety_focus"] and any(t in text for t in ("safety", "adverse", "toxicity", "risk", "risks")):
        s += 2
    if scope["mechanism_focus"] and any(t in text for t in ("mechanism", "mechanistic", "pathway", "pathways")):
        s += 2
    return s


def _human_ok(item: dict[str, Any]) -> bool:
    title = str(item.get("title") or "").lower()
    text = " ".join(str(item.get(k) or "") for k in ("title", "excerpt")).lower()
    if any(t in text for t in ("without human", "no human", "animal-only", "animal only")):
        return False
    if _TITLE_NON_HUMAN_RE.search(title):
        return False
    has_human = any(t in text for t in _HUMAN)
    has_animal = any(t in text for t in _ANIMAL)
    if has_animal and not has_human:
        return False
    return has_human or not has_animal


def _filter_evidence(scope: dict[str, Any], evidence: list[dict[str, Any]], topic_tokens: list[str] | None = None, domain_slug: str = "general") -> list[dict[str, Any]]:
    if not evidence:
        return evidence
    scoped = list(evidence)
    scoped = [e for e in scoped if not _should_filter_entry(e, domain_slug)]
    if scope["review_only"] != scope["primary_only"]:
        wanted = "review" if scope["review_only"] else "primary"
        scoped = [e for e in scoped if e.get("evidence_type") == wanted]
    if scope["year_min"]:
        scoped = [e for e in scoped if isinstance(e.get("year"), int) and e["year"] >= scope["year_min"]]
    if scope["human_only"]:
        scoped = [e for e in scoped if _human_ok(e)]
    return sorted(scoped, key=lambda e: (_score(e, scope, topic_tokens), int(e.get("year") or 0)), reverse=True)


class QueryPlan:
    def __init__(self, topic: str, domain_slug: str, criteria: str, scope: dict[str, Any], queries: list[str], topic_tokens: list[str] | None = None) -> None:
        self.topic = topic
        self.domain_slug = domain_slug
        self.criteria = criteria
        self.scope = scope
        self.queries = queries
        self.topic_tokens = topic_tokens or []

    def primary_queries(self) -> list[str]:
        return self.queries

    def filter_evidence(self, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _filter_evidence(self.scope, evidence, self.topic_tokens, self.domain_slug)

    def scope_signals(self) -> list[str]:
        return _scope_signals(self.scope)


class QueryPlanner:
    def build(self, *, topic: str, domain_slug: str, criteria: str = "") -> QueryPlan:
        clean_topic = _clean(topic)
        clean_domain = _clean(domain_slug or "general", limit=48).lower() or "general"
        clean_criteria = _clean(criteria, limit=120)
        scope = _parse_scope(clean_criteria)
        hints = DOMAIN_HINTS.get(clean_domain, DOMAIN_HINTS["general"])
        tokens = [t for t in clean_topic.lower().split() if t not in _STOPWORDS]
        queries: list[str] = []
        if clean_criteria and any(scope.values()):
            queries.append(f"{clean_topic} {clean_criteria}")
        else:
            queries.append(f"{clean_topic} systematic review {hints[0]}")
        queries.append(f"{clean_topic} {hints[0]} health outcomes")
        safety_net = f"{clean_topic} clinical trial {hints[2]}"
        if "outcomes" not in safety_net.lower():
            safety_net = f"{safety_net} outcomes"
        queries.append(safety_net)
        return QueryPlan(clean_topic, clean_domain, clean_criteria, scope, queries, tokens)
