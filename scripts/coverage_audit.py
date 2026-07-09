"""Coverage audit: measure what % of gold included_dois are retrievable.

Uses the agent's real QueryPlanner + source clients to determine the
retrieval ceiling for each gold topic. No LLM calls, no cost.

Usage:
    python scripts/coverage_audit.py [--topic SLUG]
"""
# ruff: noqa: E402

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.planner import QueryPlanner
from agent.sources.clinicaltrials import ClinicalTrialsClient
from agent.sources.openalex import OpenAlexClient
from agent.sources.pubmed import PubMedClient
from agent.sources.rxiv import RxivClient

_TOPICS_DIR = _REPO_ROOT / "tests" / "golden" / "topics"
_RUNS_DIR = _REPO_ROOT / "runs"


def normalize_doi(doi: str) -> str:
    doi = doi.lower().strip()
    if doi.startswith("https://doi.org/"):
        doi = doi[16:]
    return doi


def load_gold_topics() -> list[tuple[str, dict]]:
    topics = []
    for path in sorted(_TOPICS_DIR.glob("*.json")):
        with open(path) as f:
            topics.append((path.stem, json.load(f)))
    return topics


def collect_retrieved_dois(
    topic: str,
    domain_slug: str,
    criteria: str,
    *,
    limit: int = 10,
) -> set[str]:
    if os.getenv("COVERAGE_AUDIT_OFFLINE") == "1":
        return set()
    plan = QueryPlanner().build(topic=topic, domain_slug=domain_slug, criteria=criteria)
    queries = plan.primary_queries()
    clients = [PubMedClient(), OpenAlexClient(), RxivClient(), ClinicalTrialsClient()]
    dois: set[str] = set()
    for query in queries:
        for client in clients:
            try:
                results = client.search(query, limit=limit)
            except Exception:
                continue
            for entry in results:
                doi = entry.get("doi")
                if doi:
                    dois.add(normalize_doi(doi))
    return dois


def audit_topic(
    slug: str,
    gold: dict,
    *,
    limit: int = 10,
) -> dict:
    topic = gold.get("title", slug.replace("_", " "))
    domain = gold.get("domain", "general")
    criteria = gold.get("criteria", "")
    gold_dois = {normalize_doi(d) for d in gold.get("included_dois", []) if d}
    retrieved = collect_retrieved_dois(topic, domain, criteria, limit=limit)
    matched = retrieved & gold_dois
    missing = sorted(gold_dois - retrieved)[:5]
    match_rate = len(matched) / len(gold_dois) if gold_dois else 0.0
    return {
        "slug": slug,
        "retrieved_count": len(retrieved),
        "gold_count": len(gold_dois),
        "matched_count": len(matched),
        "match_rate": round(match_rate, 4),
        "missing_sample": missing,
    }


def _write_results(results: list[dict]) -> None:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_RUNS_DIR / "coverage-audit.json", "w") as f:
        json.dump(results, f, indent=2)

    lines = ["# Coverage Audit\n"]
    lines.append("| Topic | Gold | Retrieved | Matched | Rate |")
    lines.append("|-------|------|-----------|---------|------|")
    for r in results:
        tag = " [CEILING]" if r["match_rate"] < 0.30 else ""
        lines.append(
            f"| {r['slug']} | {r['gold_count']} | {r['retrieved_count']} | "
            f"{r['matched_count']} | {r['match_rate']:.1%}{tag} |"
        )
    if len(results) > 1:
        mean_rate = sum(r["match_rate"] for r in results) / len(results)
        flag = " [CEILING]" if mean_rate < 0.30 else ""
        lines.append(f"| **MEAN** | | | | **{mean_rate:.1%}**{flag} |")

    lines.append("")
    for r in results:
        if r["missing_sample"]:
            lines.append(f"## {r['slug']} — missing DOIs (sample)")
            for d in r["missing_sample"]:
                lines.append(f"- {d}")
            lines.append("")

    with open(_RUNS_DIR / "coverage-audit.md", "w") as f:
        f.write("\n".join(lines) + "\n")


def run_audit(*, topic: str | None = None, limit: int = 10) -> list[dict]:
    topics = load_gold_topics()
    if topic:
        topics = [(s, g) for s, g in topics if s == topic]
        if not topics:
            print(f"Unknown topic slug: {topic}", file=sys.stderr)
            sys.exit(1)
    results = []
    for slug, gold in topics:
        result = audit_topic(slug, gold, limit=limit)
        results.append(result)
        tag = "  [CEILING]" if result["match_rate"] < 0.30 else ""
        print(
            f"  {slug:30s}  gold={result['gold_count']:2d}  "
            f"retrieved={result['retrieved_count']:3d}  "
            f"matched={result['matched_count']:2d}  "
            f"rate={result['match_rate']:.1%}{tag}"
        )
        if result["missing_sample"]:
            for d in result["missing_sample"]:
                print(f"    missing: {d}")
    if len(results) > 1:
        mean_rate = sum(r["match_rate"] for r in results) / len(results)
        flag = "  [CEILING]" if mean_rate < 0.30 else ""
        print(f"  {'MEAN':30s}  rate={mean_rate:.1%}{flag}")
    _write_results(results)
    return results


if __name__ == "__main__":
    target = None
    if len(sys.argv) > 2 and sys.argv[1] == "--topic":
        target = sys.argv[2]
    run_audit(topic=target)
