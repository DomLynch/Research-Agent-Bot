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
    Agreement target: Cohen's kappa >= 0.60 on each axis.

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
# Scoring functions for 3-tier eval corpus
# ---------------------------------------------------------------------------

_POSITIVE_KW = {
    "suggest", "suggests", "suggested", "could", "may", "might", "can",
    "demonstrate", "demonstrates", "demonstrated", "shows", "indicates",
    "support", "supports", "supported", "effective", "efficacy",
    "improved", "improvement", "reduces", "reducing", "reduction",
    "increases", "increasing", "beneficial", "benefit", "positive",
    "favorable", "associated", "implicated", "linked", "helps", "impact",
}
_NEGATIVE_PHRASES = {
    "no evidence", "no benefit", "no improvement", "no advantage",
    "ineffective", "harmful",
}
_CAVEAT_KW = {
    "limited", "preliminary", "preliminarily", "caution",
    "mixed", "heterogeneous", "inconsistent", "uncertain", "unclear",
    "insufficient", "needed", "required", "promising", "investigational", "varies",
}


def _normalize_doi(doi: str) -> str:
    """Strip https://doi.org/ prefix and lowercase."""
    doi = doi.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip()


def _classify_direction(text: str) -> str:
    """Classify text direction into one of 6 conclusion_direction values."""
    import re
    t = text.lower()
    words = set(re.sub(r"[^\w\s]", "", w) for w in t.split())
    pos_count = sum(1 for kw in _POSITIVE_KW if kw in words)
    neg_count = sum(1 for phrase in _NEGATIVE_PHRASES if phrase in t)
    caveat_count = sum(1 for kw in _CAVEAT_KW if kw in words)

    if pos_count > 0 and neg_count == 0 and caveat_count == 0:
        return "positive"
    if pos_count > 0 and caveat_count > 0:
        return "positive_with_caveats"
    if neg_count > 0 and pos_count == 0 and caveat_count == 0:
        return "negative"
    if neg_count > 0 and caveat_count > 0:
        return "negative_with_caveats"
    if pos_count > 0 and neg_count > 0:
        return "mixed"
    if caveat_count > 2:
        return "mixed"
    return "insufficient_evidence"


def _direction_distance(d1: str, d2: str) -> float:
    """0.0 = same, 0.5 = off-by-one-confidence-level, 1.0 = completely different."""
    order = [
        "negative",
        "negative_with_caveats",
        "insufficient_evidence",
        "mixed",
        "positive_with_caveats",
        "positive",
    ]
    try:
        i1, i2 = order.index(d1), order.index(d2)
        diff = abs(i1 - i2)
        if diff == 0:
            return 0.0
        if diff == 1:
            return 0.5
        return 1.0
    except ValueError:
        return 1.0


def study_overlap(draft: dict[str, Any], gold: dict[str, Any]) -> float:
    """Fraction of gold.included_dois that appear in draft.source_bundle.

    DOIs are normalized (strip https://doi.org/, lowercase) before comparison.
    Returns float in [0.0, 1.0]. Higher is better.
    """
    source_bundle = draft.get("source_bundle", [])
    draft_dois: set[str] = set()
    for entry in source_bundle:
        doi = entry.get("doi") or ""
        if doi:
            draft_dois.add(_normalize_doi(doi))

    if not draft_dois:
        return 0.0

    gold_dois = gold.get("included_dois", [])
    matched = sum(
        1 for gd in gold_dois
        if _normalize_doi(gd) in draft_dois
    )
    return matched / len(gold_dois) if gold_dois else 0.0


def direction_agreement(draft: dict[str, Any], gold: dict[str, Any]) -> float:
    """Classify draft Key Findings + Conclusion direction, compare to gold.conclusion_direction.

    Uses deterministic rule-based classifier with positive/negative/caveat keywords.
    Returns 1.0 if exact match, 0.5 if off-by-one-confidence-level, 0.0 otherwise.
    """
    sections = draft.get("sections", {})
    findings = sections.get("Key Findings", "") or ""
    conclusion = sections.get("Conclusion", "") or ""
    combined = f"{findings} {conclusion}"

    draft_dir = _classify_direction(combined)
    gold_dir = gold.get("conclusion_direction", "insufficient_evidence")

    dist = _direction_distance(draft_dir, gold_dir)
    return 1.0 - dist


def _jaccard_similarity(text1: str, text2: str) -> float:
    """Word-level similarity: fraction of text2 (gold) words that appear in text1 (draft).

    This is recall-oriented: we care about how many of the gold limitation's
    words the draft mentions, not how many extra words the draft has.
    """
    import re
    tokens1 = set(re.sub(r"[^\w\s]", "", w) for w in text1.lower().split())
    tokens2 = set(re.sub(r"[^\w\s]", "", w) for w in text2.lower().split())
    tokens1.discard("")
    tokens2.discard("")
    if not tokens2:
        return 0.0
    if not tokens1 and not tokens2:
        return 0.0
    overlap = len(tokens1 & tokens2)
    return overlap / len(tokens2)


def limitation_overlap(draft: dict[str, Any], gold: dict[str, Any]) -> float:
    """Bag-of-word Jaccard between draft Limitations and each gold limitation.

    Returns fraction of gold limitations with Jaccard similarity >= 0.4.
    Returns float in [0.0, 1.0]. Higher is better.
    """
    sections = draft.get("sections", {})
    draft_limitations = sections.get("Limitations", "") or ""

    gold_limitations = gold.get("limitations", [])
    if not gold_limitations:
        return 0.0

    matched = sum(
        1 for gl in gold_limitations
        if _jaccard_similarity(draft_limitations, gl) >= 0.4
    )
    return matched / len(gold_limitations)


_NUMERIC_CLAIM_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|ppm|mg|fold|x|years?|months?|days?|patients?|subjects?|participants?|kg|mg/kg|ug|L|mL|nM|uM|uL|mmHg|bpm)"
)


def _extract_numbers(text: str) -> set[str]:
    """Extract all numeric claim patterns from text as strings."""
    return set(_NUMERIC_CLAIM_RE.findall(text.lower()))


def _evidence_contains_number(evidence_excerpts: list[str], number_str: str) -> bool:
    """Check if any evidence excerpt contains the given number string."""
    for excerpt in evidence_excerpts:
        if number_str in excerpt.lower():
            return True
    return False


def quantitative_fidelity(draft: dict[str, Any], gold: dict[str, Any]) -> float:
    """Extract numeric claims from draft Key Findings, verify against evidence.

    Regex extracts numbers with units. Each extracted number must appear in
    at least one evidence excerpt from the source bundle. Returns fraction
    of numeric claims that are supported. Returns float in [0.0, 1.0].
    """
    sections = draft.get("sections", {})
    findings = sections.get("Key Findings", "") or ""

    numeric_claims = _extract_numbers(findings)
    if not numeric_claims:
        return 1.0

    source_bundle = draft.get("source_bundle", [])
    evidence_excerpts = [
        str(e.get("excerpt", "")) for e in source_bundle
    ]

    supported = sum(
        1 for num in numeric_claims
        if _evidence_contains_number(evidence_excerpts, num)
    )
    return supported / len(numeric_claims)


def composite_score(draft: dict[str, Any], gold: dict[str, Any]) -> float:
    """Weighted composite of 4 scoring functions.

    Weights: study_overlap=0.10, quantitative_fidelity=0.40,
             direction_agreement=0.30, limitation_overlap=0.20
    """
    return (
        0.10 * study_overlap(draft, gold)
        + 0.40 * quantitative_fidelity(draft, gold)
        + 0.30 * direction_agreement(draft, gold)
        + 0.20 * limitation_overlap(draft, gold)
    )


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

READABILITY (clarity and grammar — countable criteria):
  5 = Has paragraph breaks (blank lines). Average sentence length <= 30 words.
      No single sentence exceeds 50 words. Tone is consistently professional —
      NO filler language (e.g. "we need more data", "some people think"),
      NO awkward transitions, no mixing of casual and academic voice.
      Writing is polished and authoritative throughout.
  3 = Has paragraph breaks and short sentences, BUT tone is flat, generic,
      or mixes casual/formal language. Contains filler phrases like
      "more research is needed", "interesting but...", "some people think".
      Structurally adequate but not polished.
  1 = No paragraph breaks AND/OR majority of sentences exceed 40 words (run-on).
      Severe grammar issues (subject-verb disagreement, missing articles).
      Stream-of-consciousness with no sentence boundaries.

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


def cohen_kappa(human: list[int], judge: list[int], k: int = 5) -> float:
    """Unweighted Cohen's kappa between two rating vectors (same length)."""
    n = len(human)
    if n == 0:
        return 0.0
    obs = [[0] * k for _ in range(k)]
    for h, j in zip(human, judge):
        obs[h - 1][j - 1] += 1
    # Observed agreement
    p_o = sum(obs[i][i] for i in range(k)) / n
    # Expected agreement (marginal independence)
    p_e = 0.0
    for i in range(k):
        row_s = sum(obs[i])
        col_s = sum(obs[r][i] for r in range(k))
        p_e += row_s * col_s / n**2
    return (p_o - p_e) / (1 - p_e) if p_e != 1.0 else 1.0


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
            if e.get("evidence_type") in {"review", "primary", "interventional", "observational"}
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
