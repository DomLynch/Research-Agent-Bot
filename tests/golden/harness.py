from __future__ import annotations

import re
from typing import Any

"""Golden eval harness — VPS ONLY. Requires live PubMed/OpenAlex API access.

This is NOT a CI test. Run manually on the VPS to measure retrieval quality:
    ssh root@vps && cd /opt/research-agent-bot && .venv/bin/python tests/golden/harness.py

Metrics (retrieval):
    precision  = % of source bundle entries whose title contains >= 1 topic token
    recall     = % of topics that meet minimum source count (12+)
    breadth    = % of golden topics successfully covered
    cleanliness = % of sources without injection markers

Judge calibration (Step 6):
    judge_draft() rates draft quality on 4 axes (coherence, accuracy, readability, source_quality)
    using a standardized rubric. Calibration test compares against human expert ratings.
    Agreement target: weighted Cohen's kappa >= 0.60 on each axis.

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


# ---------------------------------------------------------------------------
# Step 6: Judge calibration
# ---------------------------------------------------------------------------

_JUDGE_RUBRIC = """You are a strict research quality judge. Rate the draft on exactly 4 axes.
Return ONLY valid JSON with keys: coherence, accuracy, readability, source_quality.
Each key MUST be an integer from 1 to 5.

CRITERIA — apply each axis independently:

COHERENCE (logical structure and flow):
  5 = Clear section headings (Introduction, Methods, Results, Conclusion or similar).
      Logical progression from background → evidence → conclusion.
  3 = Has some structure (headings or paragraphs) but transitions are weak.
      Ideas repeat or jump without clear progression.
  1 = No headings, no paragraphs, or random topic jumps within sentences.
      Stream-of-consciousness, no logical flow.

ACCURACY (evidence quality and factual claims):
  5 = Cites specific studies with author names or trial IDs.
      Claims include numbers (percentages, p-values, sample sizes).
      No obvious false claims.
  3 = Mentions specific drugs/topics correctly but lacks citations or numbers.
      Vague claims like "some studies suggest" without references.
  1 = Contains factual errors (wrong drug names, invented statistics).
      Purely speculative with no grounding in evidence.

READABILITY (clarity and grammar):
  5 = Professional writing, correct grammar, appropriate terminology,
      no spelling errors, well-organized paragraphs.
  3 = Mostly readable but has awkward phrasing, some repetition,
      or inconsistent tone. Minor grammar issues.
  1 = Difficult to follow, major grammar errors, run-on sentences,
      no paragraph structure, spelling mistakes throughout.

SOURCE_QUALITY (references and citations):
  5 = 3+ named citations (author, year, trial ID, or DOI).
      Mix of study types (trials, reviews, meta-analyses).
  3 = 1-2 vague references like "the TAME trial" or "some studies" without details.
  1 = Zero references or citations of any kind. No study names, no trial IDs."""

_JUDGE_AXES = ("coherence", "accuracy", "readability", "source_quality")


def judge_draft(draft: str, *, provider: Any | None = None) -> dict:
    """Rate a draft on 4 quality axes using MiMo as judge."""
    if provider is None:
        from agent.provider import MimoClient

        provider = MimoClient.from_env()
    result, _ = provider.complete_json(
        system_prompt=_JUDGE_RUBRIC,
        user_prompt=f"Rate this research draft:\n\n{draft}",
    )
    scores = {ax: int(result.get(ax, 3)) for ax in _JUDGE_AXES}
    return scores


def weighted_kappa(human: list[int], judge: list[int], k: int = 5) -> float:
    """Weighted Cohen's kappa between two rating vectors (same length)."""
    n = len(human)
    if n == 0:
        return 0.0
    obs = [[0] * k for _ in range(k)]
    for h, j in zip(human, judge):
        obs[h - 1][j - 1] += 1
    exp = [[0.0] * k for _ in range(k)]
    for i in range(k):
        row_s = sum(obs[i])
        col_s = sum(obs[j][i] for j in range(k))
        for j in range(k):
            exp[i][j] = row_s * col_s / n
    num = 0.0
    den = 0.0
    for i in range(k):
        for j in range(k):
            w = 1.0 - (i - j) ** 2 / (k - 1) ** 2
            num += w * (obs[i][j] - exp[i][j])
            den += w * exp[i][j]
    return num / den if den != 0 else 1.0


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

        results.append({
            "topic": g["topic"],
            "description": g["description"],
            "sources": len(source_bundle),
            "min_required": g["min_sources"],
            "title_precision": round(precision, 2),
            "cleanliness": round(cleanliness, 2),
            "meets_threshold": has_min and precision >= 0.70,
        })

    avg_precision = sum(r["title_precision"] for r in results) / len(results)
    recall = sum(1 for r in results if r["meets_threshold"]) / len(results)
    breadth = sum(1 for r in results if r["sources"] >= r["min_required"]) / len(results)
    avg_cleanliness = sum(r["cleanliness"] for r in results) / len(results)

    return {
        "topics": results,
        "avg_precision": round(avg_precision, 2),
        "recall": round(recall, 2),
        "breadth": round(breadth, 2),
        "avg_cleanliness": round(avg_cleanliness, 2),
        "pass": (
            avg_precision >= 0.70
            and avg_cleanliness >= 0.95
            and recall >= 0.80
            and breadth >= 0.80
        ),
    }


if __name__ == "__main__":
    import json
    report = run_eval()
    print(json.dumps(report, indent=2))
    print(f"\nPrecision: {report['avg_precision']:.0%}  Recall: {report['recall']:.0%}  "
          f"Breadth: {report['breadth']:.0%}  Cleanliness: {report['avg_cleanliness']:.0%}  "
          f"{'PASS' if report['pass'] else 'FAIL'}")
