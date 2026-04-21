from __future__ import annotations

import re

"""Golden eval harness — VPS ONLY. Requires live PubMed/OpenAlex API access.

This is NOT a CI test. Run manually on the VPS to measure retrieval quality:
    ssh root@vps && cd /opt/research-agent-bot && .venv/bin/python tests/golden/harness.py

Metrics:
    precision  = % of source bundle entries whose title contains >= 1 topic token
    recall     = % of topics that meet minimum source count (12+)
    breadth    = % of golden topics successfully covered
    cleanliness = % of sources without injection markers
    tone       = keyword-based rating (avg tone_rating across bundle)

Thresholds:
    precision  >= 0.70
    cleanliness >= 0.95
    recall, breadth, tone >= 0.80

For CI, use tests/test_golden.py which validates the harness logic with mock data.
"""

from agent.planner import QueryPlanner  # noqa: E402
from agent.sources.pubmed import PubMedClient  # noqa: E402
from agent.sources.openalex import OpenAlexClient  # noqa: E402
from agent.drafter import _rank, _relevance, _clean  # noqa: E402

_STOPWORDS = {"and", "in", "for", "of", "the", "with", "on", "to", "a", "an"}
_SYNONYMS = {"rapamycin": ["sirolimus"], "metformin": ["glucophage"]}

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

_TONE_POSITIVE = {"promising", "robust", "significant", "effective", "novel", "validated", "strong"}
_TONE_NEGATIVE = {"limited", "small", "inconclusive", "unclear", "weak", "insufficient", "heterogeneous"}

GOLDEN_TOPICS = [
    {"topic": "rapamycin and aging", "domain": "longevity", "min_sources": 12, "description": "Core geroprotector topic"},
    {"topic": "metformin and longevity", "domain": "longevity", "min_sources": 10, "description": "Diabetes drug repurposed for aging"},
    {"topic": "caloric restriction and lifespan", "domain": "longevity", "min_sources": 10, "description": "Classic dietary intervention"},
    {"topic": "senolytics and healthspan", "domain": "longevity", "min_sources": 10, "description": "Senescent cell clearance"},
    {"topic": "NAD precursors and aging", "domain": "longevity", "min_sources": 8, "description": "NAD+ metabolism"},
    {"topic": "exercise and biological aging", "domain": "longevity", "min_sources": 12, "description": "Physical activity and aging"},
    {"topic": "intermittent fasting and health", "domain": "longevity", "min_sources": 10, "description": "Time-restricted eating"},
    {"topic": "stem cells and aging", "domain": "longevity", "min_sources": 8, "description": "Regenerative medicine"},
    {"topic": "epigenetic clocks and longevity", "domain": "longevity", "min_sources": 8, "description": "Biological age measurement"},
    {"topic": "gut microbiome and aging", "domain": "longevity", "min_sources": 10, "description": "Microbiome and age-related disease"},
]


def _expand_tokens(topic: str) -> list[str]:
    tokens = [t for t in _clean(topic).lower().split() if t not in _STOPWORDS]
    expanded = list(tokens)
    for tok in tokens:
        expanded.extend(_SYNONYMS.get(tok, []))
    return expanded


def _has_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))


def _tone_rating(text: str) -> float:
    lower = text.lower()
    pos = sum(1 for w in _TONE_POSITIVE if w in lower)
    neg = sum(1 for w in _TONE_NEGATIVE if w in lower)
    total = pos + neg
    if total == 0:
        return 0.5
    return round(pos / total, 2)


def run_eval(per_source_limit: int = 25) -> dict:
    planner = QueryPlanner()
    results = []
    all_domains = set()

    for g in GOLDEN_TOPICS:
        plan = planner.build(topic=g["topic"], domain_slug=g["domain"])
        all_domains.add(g["domain"])
        evidence = []
        sources = (("pubmed", PubMedClient()), ("openalex", OpenAlexClient()))
        for query in plan.primary_queries():
            for _name, client in sources:
                try:
                    evidence.extend(client.search(query, limit=per_source_limit))
                except Exception:
                    pass

        ranked = _rank(evidence)
        bundle = ranked[:20]
        topic_tokens = _expand_tokens(g["topic"])

        source_bundle = [
            e for e in bundle
            if e.get("evidence_type") in {"review", "primary"}
            and _relevance(e, topic_tokens) >= 0.3
        ][:12]

        title_hits = sum(
            1 for e in source_bundle
            if any(t in str(e.get("title") or "").lower() for t in topic_tokens)
        )
        precision = title_hits / len(source_bundle) if source_bundle else 0
        has_min = len(source_bundle) >= g["min_sources"]

        # Cleanliness: % of sources without injection markers
        clean_count = sum(
            1 for e in source_bundle
            if not _has_injection(str(e.get("title") or ""))
            and not _has_injection(str(e.get("excerpt") or ""))
        )
        cleanliness = clean_count / len(source_bundle) if source_bundle else 1.0

        # Tone: average tone rating across bundle
        tone_ratings = [
            _tone_rating(str(e.get("excerpt") or "") + " " + str(e.get("title") or ""))
            for e in source_bundle
        ]
        tone = round(sum(tone_ratings) / len(tone_ratings), 2) if tone_ratings else 0.5

        results.append({
            "topic": g["topic"],
            "description": g["description"],
            "sources": len(source_bundle),
            "min_required": g["min_sources"],
            "title_precision": round(precision, 2),
            "cleanliness": round(cleanliness, 2),
            "tone": tone,
            "meets_threshold": has_min and precision >= 0.70,
        })

    avg_precision = sum(r["title_precision"] for r in results) / len(results)
    recall = sum(1 for r in results if r["meets_threshold"]) / len(results)
    breadth = sum(1 for r in results if r["sources"] >= r["min_required"]) / len(results)
    avg_cleanliness = sum(r["cleanliness"] for r in results) / len(results)
    avg_tone = sum(r["tone"] for r in results) / len(results)

    return {
        "topics": results,
        "avg_precision": round(avg_precision, 2),
        "recall": round(recall, 2),
        "breadth": round(breadth, 2),
        "avg_cleanliness": round(avg_cleanliness, 2),
        "avg_tone": round(avg_tone, 2),
        "pass": (
            avg_precision >= 0.70
            and avg_cleanliness >= 0.95
            and recall >= 0.80
            and breadth >= 0.80
            and avg_tone >= 0.80
        ),
    }


if __name__ == "__main__":
    import json
    report = run_eval()
    print(json.dumps(report, indent=2))
    print(f"\nPrecision: {report['avg_precision']:.0%}  Recall: {report['recall']:.0%}  "
          f"Breadth: {report['breadth']:.0%}  Cleanliness: {report['avg_cleanliness']:.0%}  "
          f"Tone: {report['avg_tone']:.0%}  {'PASS' if report['pass'] else 'FAIL'}")
