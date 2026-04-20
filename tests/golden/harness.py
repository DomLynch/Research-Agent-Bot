from __future__ import annotations

"""Golden eval harness. Run on VPS with real PubMed/OpenAlex to measure retrieval quality.

Usage:
    python tests/golden/harness.py

Metrics:
    precision = % of source bundle entries whose title contains >= 1 topic token
    coverage  = % of topics that meet minimum source count (12+)
    noise     = source entries with 0 topic tokens in title

Thresholds:
    precision >= 0.70
    coverage  >= 0.80
"""

import re
from agent.planner import QueryPlanner
from agent.sources.pubmed import PubMedClient
from agent.sources.openalex import OpenAlexClient
from agent.drafter import _rank, _relevance, _clean

_STOPWORDS = {"and", "in", "for", "of", "the", "with", "on", "to", "a", "an"}
_SYNONYMS = {"rapamycin": ["sirolimus"], "metformin": ["glucophage"]}

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


def run_eval(per_source_limit: int = 25) -> dict:
    planner = QueryPlanner()
    results = []

    for g in GOLDEN_TOPICS:
        plan = planner.build(topic=g["topic"], domain_slug=g["domain"])
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

        results.append({
            "topic": g["topic"],
            "description": g["description"],
            "sources": len(source_bundle),
            "min_required": g["min_sources"],
            "title_precision": round(precision, 2),
            "meets_threshold": has_min and precision >= 0.5,
        })

    avg_precision = sum(r["title_precision"] for r in results) / len(results)
    coverage = sum(1 for r in results if r["meets_threshold"]) / len(results)

    return {
        "topics": results,
        "avg_precision": round(avg_precision, 2),
        "coverage": round(coverage, 2),
        "pass": avg_precision >= 0.70 and coverage >= 0.80,
    }


if __name__ == "__main__":
    import json
    report = run_eval()
    print(json.dumps(report, indent=2))
    print(f"\nPrecision: {report['avg_precision']:.0%}  Coverage: {report['coverage']:.0%}  {'PASS' if report['pass'] else 'FAIL'}")
