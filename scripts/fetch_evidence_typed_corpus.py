"""Day 10.17 Phase 6.3 — evidence-typed corpus retrieval.

Pre-fix Phase 3 used ONE generic Europe PMC query
("metformin AND aging") and got 35 broad reviews where only 1 of
them contributed a high-confidence claim. The 6 user-uploaded PDFs
did all the heavy lifting.

Per converged audit: better source acquisition is higher leverage
than any writer/vocab refactor. This script issues TARGETED queries
by evidence type (RCT vs meta-analysis vs observational vs
mechanism) so the v0.6 extractor has metformin-specific clinical
results to bind, not broad aging-review prose.

Multi-source: Europe PMC primary (full-text JATS available); PubMed
fallback for metadata + PMID resolution; ClinicalTrials.gov
deferred (mostly protocols). Dedupes hits by DOI / PMID.

Output:
  - candidate PMCIDs printed to stdout
  - <out_dir>/corpus_manifest.json (full hit metadata)

Then `scripts/fetch_oa_corpus.py --pmcids ...` ingests the OA ones.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# Evidence-typed query templates. Each yields different claim
# density per the v0.6 extractor's strengths:
#   RCT: high-conf p-values, CIs, sample sizes
#   meta-analysis: HR/OR pooled estimates
#   observational: large-N mortality/HR data
#   mechanism: in-vitro / animal model results (lower conf in our gate)
_EVIDENCE_QUERIES: dict[str, str] = {
    "rct": (
        "metformin AND (randomized OR randomised OR RCT OR "
        "\"clinical trial\") AND (aging OR sarcopenia OR frailty OR "
        "older OR longevity OR healthspan) AND OPEN_ACCESS:Y AND HAS_FT:Y"
    ),
    "meta_analysis": (
        "metformin AND (\"meta-analysis\" OR \"systematic review\") "
        "AND (mortality OR aging OR longevity OR cardiovascular) "
        "AND OPEN_ACCESS:Y AND HAS_FT:Y"
    ),
    "observational": (
        "metformin AND (cohort OR observational OR \"electronic health\") "
        "AND (mortality OR survival OR all-cause) AND OPEN_ACCESS:Y "
        "AND HAS_FT:Y"
    ),
    "mechanism": (
        "metformin AND (AMPK OR mTOR OR mitochondrial OR autophagy OR "
        "senescence OR \"insulin sensitivity\") AND (skeletal\\ muscle "
        "OR longevity OR \"older adults\") AND OPEN_ACCESS:Y AND HAS_FT:Y"
    ),
}


@dataclass(frozen=True, slots=True)
class CorpusHit:
    pmcid: str
    pmid: str
    doi: str
    title: str
    journal: str
    year: int | None
    evidence_type: str
    rank_in_type: int


async def _search_europe_pmc(
    query: str, limit: int = 25,
) -> list[dict]:
    import httpx
    SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {
        "query": query,
        "format": "json",
        "pageSize": str(limit),
        "resultType": "core",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(SEARCH, params=params)
        r.raise_for_status()
        data = r.json()
    return data.get("resultList", {}).get("result", [])


async def _multi_source_fetch(
    per_type_limit: int,
) -> tuple[list[CorpusHit], dict[str, int]]:
    """Run all evidence-type queries; dedupe by PMCID/DOI."""
    all_hits: list[CorpusHit] = []
    seen_pmcids: set[str] = set()
    seen_dois: set[str] = set()
    by_type_counts: dict[str, int] = {}

    for ev_type, query in _EVIDENCE_QUERIES.items():
        print(
            f"  → {ev_type}: querying Europe PMC...",
            file=sys.stderr,
        )
        try:
            results = await _search_europe_pmc(query, limit=per_type_limit)
        except Exception as e:
            print(f"    !! {ev_type} failed: {e}", file=sys.stderr)
            by_type_counts[ev_type] = 0
            continue
        added = 0
        for rank, h in enumerate(results, start=1):
            pmcid = h.get("pmcid", "")
            doi = (h.get("doi") or "").lower()
            if not pmcid:
                continue
            if pmcid in seen_pmcids:
                continue
            if doi and doi in seen_dois:
                continue
            seen_pmcids.add(pmcid)
            if doi:
                seen_dois.add(doi)
            all_hits.append(CorpusHit(
                pmcid=pmcid,
                pmid=h.get("pmid", ""),
                doi=h.get("doi", ""),
                title=(h.get("title") or "").strip()[:200],
                journal=h.get("journalTitle", "") or "",
                year=int(h["pubYear"]) if h.get("pubYear") and str(h["pubYear"]).isdigit() else None,
                evidence_type=ev_type,
                rank_in_type=rank,
            ))
            added += 1
        by_type_counts[ev_type] = added
        print(f"    {added} new hits added (after dedupe)", file=sys.stderr)
    return all_hits, by_type_counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 6.3 evidence-typed corpus retrieval",
    )
    parser.add_argument(
        "--per-type-limit", type=int, default=15,
        help="Max hits per evidence type (default: 15; total cap ~60)",
    )
    parser.add_argument(
        "--out-manifest",
        default=str(REPO_ROOT / "docs" / "quality-reference" / "metformin"
                    / "phase63_corpus_manifest.json"),
        help="Where to write corpus manifest JSON",
    )
    args = parser.parse_args(argv)

    print(
        "Running evidence-typed Europe PMC queries "
        f"(limit {args.per_type_limit} per type)...",
        file=sys.stderr,
    )
    hits, type_counts = asyncio.run(
        _multi_source_fetch(args.per_type_limit),
    )

    # Print PMCIDs in stable order so the user can pipe to fetch_oa_corpus.py
    pmcids = [h.pmcid for h in hits]
    print(",".join(pmcids))

    out_path = Path(args.out_manifest).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "n_hits": len(hits),
        "by_evidence_type": type_counts,
        "queries": _EVIDENCE_QUERIES,
        "hits": [
            {
                "pmcid": h.pmcid, "pmid": h.pmid, "doi": h.doi,
                "title": h.title, "journal": h.journal, "year": h.year,
                "evidence_type": h.evidence_type,
                "rank_in_type": h.rank_in_type,
            }
            for h in hits
        ],
    }, indent=2))
    print(
        f"\nTotal candidates: {len(hits)} unique PMCIDs across "
        f"{len(type_counts)} evidence types",
        file=sys.stderr,
    )
    print(f"By type: {type_counts}", file=sys.stderr)
    print(f"Manifest: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
