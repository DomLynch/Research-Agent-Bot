"""Generic topic corpus seeder — works for ANY topic.

Replaces scripts/seed_rapamycin_corpus.py (which was topic-hardcoded).
This script works for metformin, rapamycin, GLP-1, statins, or any
new topic with a topic_packs/<topic>.toml file. Zero code changes
needed to add a new topic — just write the TOML.

Pipeline:
  1. Load topic_packs/<topic>.toml — search queries + aliases
  2. SourceAggregator fan-out across all wired databases
     (PubMed + Europe PMC + OpenAlex + ClinicalTrials.gov + bioRxiv +
      Semantic Scholar + Crossref + DOAJ + OpenAIRE + PMC-OAI;
      optional CORE + ChEMBL with API keys)
  3. Dedupe by DOI/PMID/title
  4. Resolve PMCIDs for full-text fetch
  5. Download JATS XML via fetch_oa_corpus.py (free Europe PMC)
  6. Extract quant claims via quant_claim_extract.py (deterministic)
  7. Write to docs/quality-reference/<topic>/{quant_claims,parsed}/

All free — no LLM cost. Adds ~$0.04 only when synthesis runs.

Usage:
  python scripts/seed_topic_corpus.py --topic rapamycin
  python scripts/seed_topic_corpus.py --topic GLP-1 --limit 30
  python scripts/seed_topic_corpus.py --topic statins --max-per-source 25
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agent.sources.aggregator import (  # noqa: E402
    discover, list_available_sources,
)
from agent.topic_pack import (  # noqa: E402
    TopicPack, load_topic_pack,
)
from agent.wave_retrieval import run_waves  # noqa: E402
from agent.retrieval_modes import resolve_params  # noqa: E402
from agent.corpus_pipeline import (  # noqa: E402
    classify_and_filter, format_funnel_md,
)


def _topic_pack_path(topic: str) -> Path:
    return REPO / "topic_packs" / f"{topic}.toml"


def _corpus_paths(topic: str) -> tuple[Path, Path]:
    base = REPO / "docs" / "quality-reference" / topic
    return base / "quant_claims", base / "parsed"


async def _resolve_pmcid(
    aggregated_hit, *, http,
) -> str | None:
    """Resolve a discovered hit (with DOI/PMID) to a PMCID for
    full-text fetch via Europe PMC."""
    if not (aggregated_hit.doi or aggregated_hit.pmid):
        return None
    parts = []
    if aggregated_hit.doi:
        parts.append(f"DOI:{aggregated_hit.doi}")
    if aggregated_hit.pmid:
        parts.append(f"EXT_ID:{aggregated_hit.pmid}")
    query = " OR ".join(parts)
    url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
        f"query={urllib.parse.quote(query)}&format=json&pageSize=1"
    )
    try:
        r = await http.get(url, timeout=15.0)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None
    hits = data.get("resultList", {}).get("result", [])
    if not hits:
        return None
    return hits[0].get("pmcid")


async def _do_seed(
    topic: str,
    *,
    limit: int,
    max_per_source: int,
    sources: list[str] | None,
) -> dict[str, Any]:
    pack_path = _topic_pack_path(topic)
    if not pack_path.exists():
        raise FileNotFoundError(
            f"Topic pack not found: {pack_path}. Create the TOML "
            "first (use topic_packs/metformin.toml as template)."
        )
    pack: TopicPack = load_topic_pack(pack_path)

    quant_dir, parsed_dir = _corpus_paths(topic)
    parsed_dir.mkdir(parents=True, exist_ok=True)
    quant_dir.mkdir(parents=True, exist_ok=True)

    # ===== Slice 7 step 3: dispatch on calibrated [retrieval] block =====
    # If the pack has a [retrieval] block, run the wave-based
    # calibrated retrieval + classify-before-extract gate. Only
    # kept (core/background/adjacent) hits proceed to PMCID
    # resolution + JATS fetch + extract. Drops 50-70% of CPU on
    # papers that would have been classified out anyway.
    #
    # Legacy fallback: pack with only corpus_search_queries strings
    # uses the old single-query loop (back-compat for unmigrated
    # packs).

    if pack.retrieval is not None:
        print(
            f"=== Calibrated retrieval for topic={topic} ===\n"
            f"  topic_terms     : {len(pack.retrieval.topic_terms)}\n"
            f"  scope_terms     : {len(pack.retrieval.scope_terms)}\n"
            f"  evidence_types  : {len(pack.retrieval.evidence_types)}\n"
            f"  exclude_terms   : {len(pack.retrieval.exclude_terms)}\n"
            f"  background_allow: "
            f"{len(pack.retrieval.background_allow)}",
            file=sys.stderr,
        )
        params = resolve_params("calibrated")
        report = await run_waves(pack.retrieval, params=params)
        manifest = classify_and_filter(
            report, topic=topic,
            topic_aliases=tuple(pack.aliases_display),
            expected_slots=pack.expected_evidence_slots,
        )
        # Write the corpus manifest for the dashboard / funnel
        manifest_path = (
            REPO / "docs/quality-reference" / topic
            / "corpus_manifest.json"
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "topic": manifest.topic,
            "funnel": dict(manifest.funnel),
            "per_wave_stats": [
                dict(s) for s in manifest.per_wave_stats
            ],
            "n_kept": len(manifest.kept()),
        }, indent=2))
        (REPO / "docs/quality-reference" / topic
         / "corpus_manifest.md").write_text(
            format_funnel_md(manifest),
        )
        kept = manifest.kept()
        print(
            f"  → retrieved={manifest.funnel.get('retrieved', 0)} "
            f"keep={len(kept)} "
            f"core={manifest.funnel.get('extractable_core', 0)} "
            f"bg={manifest.funnel.get('extractable_background', 0)}",
            file=sys.stderr,
        )
        # Truncate to user-supplied --limit (caller can still bound
        # extraction CPU). 200K+ extraction is impractical without
        # parallelism that's not built yet.
        selected = [e.hit for e in kept][:limit]
        print(
            f"=== Selecting top {len(selected)} kept hits for "
            f"fetch (limit={limit}) ===",
            file=sys.stderr,
        )
    else:
        if not pack.corpus_search_queries:
            raise ValueError(
                f"Topic pack {pack_path} has no [retrieval] block "
                f"AND no corpus_search_queries. Add one of them."
            )
        # 1. Fan-out search across all enabled sources (legacy path)
        print(
            f"=== Discovering corpus for topic={topic} (legacy) ===\n"
            f"Search queries: {len(pack.corpus_search_queries)}\n"
            f"Active sources: see --list-sources",
            file=sys.stderr,
        )
        all_hits = []
        for query in pack.corpus_search_queries:
            print(f"\n[query] {query}", file=sys.stderr)
            hits = await discover(
                query,
                enabled_sources=sources,
                limit_per_source=max_per_source,
            )
            print(
                f"  → {len(hits)} unique hits (after cross-source dedupe)",
                file=sys.stderr,
            )
            all_hits.extend(hits)

        # Dedupe across queries (by DOI/PMID/title)
        seen: set[str] = set()
        deduped = []
        for h in all_hits:
            key = (
                f"doi:{h.doi}" if h.doi
                else f"pmid:{h.pmid}" if h.pmid
                else f"title:{h.title.lower()[:80]}"
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(h)
        print(
            f"\n=== {len(deduped)} unique candidates after cross-query "
            "dedupe ===",
            file=sys.stderr,
        )

        # Rank: more sources first, then year desc
        deduped.sort(
            key=lambda h: (-h.n_sources, -(h.year or 0)),
        )
        selected = deduped[:limit]
        print(
            f"=== Selecting top {len(selected)} for fetch ===",
            file=sys.stderr,
        )

    # 2. Resolve PMCIDs (for full-text fetch)
    import httpx
    pmcids: list[str] = []
    paper_id_map: dict[str, dict] = {}
    failures: list[dict] = []
    print("\n=== Resolving PMCIDs ===", file=sys.stderr)
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": "researka/1.0"},
    ) as http:
        for h in selected:
            pmcid = await _resolve_pmcid(h, http=http)
            if pmcid:
                pmcids.append(pmcid)
                paper_id_map[pmcid] = {
                    "title": h.title,
                    "doi": h.doi, "pmid": h.pmid,
                    "year": h.year, "venue": h.venue,
                    "sources": list(h.sources),
                }
                print(f"  ✓ {pmcid}: {h.title[:70]}", file=sys.stderr)
            else:
                failures.append({
                    "title": h.title[:80],
                    "doi": h.doi, "pmid": h.pmid,
                    "reason": "no PMCID (closed-access or unindexed)",
                })

    # 3. Fetch full text via fetch_oa_corpus.py
    if pmcids:
        print(
            f"\n=== Fetching {len(pmcids)} papers ===",
            file=sys.stderr,
        )
        cmd = [
            "python3", str(REPO / "scripts/fetch_oa_corpus.py"),
            "--pmcids", ",".join(pmcids),
            "--out-dir", str(parsed_dir),
        ]
        try:
            subprocess.run(cmd, check=True, cwd=REPO)
        except subprocess.CalledProcessError as e:
            print(
                f"  ! fetch_oa_corpus exited {e.returncode}",
                file=sys.stderr,
            )

    # 4. Extract quant claims
    print(
        "\n=== Extracting quant claims ===",
        file=sys.stderr,
    )
    n_extracted = 0
    for pf in parsed_dir.glob("*.paper_sections.json"):
        target = quant_dir / (
            pf.stem.replace(".paper_sections", "")
            + ".quant_claims.json"
        )
        if target.exists():
            n_extracted += 1
            continue
        cmd = [
            "python3",
            str(REPO / "scripts/quant_claim_extract.py"),
            str(pf), "--out", str(target),
        ]
        try:
            subprocess.run(
                cmd, check=True, cwd=REPO,
                capture_output=True,
            )
            n_extracted += 1
        except subprocess.CalledProcessError as e:
            print(
                f"  ! extract failed for {pf.name}: {e}",
                file=sys.stderr,
            )

    # Write report
    report = {
        "topic": topic,
        "n_queries": len(pack.corpus_search_queries),
        "n_unique_candidates": len(deduped),
        "n_selected_for_fetch": len(selected),
        "n_pmcid_resolved": len(pmcids),
        "n_extracted": n_extracted,
        "failures": failures,
        "papers_resolved": paper_id_map,
    }
    report_path = (
        REPO / "docs/quality-reference" / topic
        / "_extract_report.json"
    )
    report_path.write_text(json.dumps(report, indent=2))
    return report


def _print_report(report: dict[str, Any]) -> None:
    print(
        f"\n=== Corpus Seeding Summary — topic={report['topic']} ===\n"
        f"Search queries:        {report['n_queries']}\n"
        f"Unique candidates:     {report['n_unique_candidates']}\n"
        f"Selected for fetch:    {report['n_selected_for_fetch']}\n"
        f"PMCID resolved:        {report['n_pmcid_resolved']}\n"
        f"Quant claims extracted: {report['n_extracted']}\n"
        f"Failures:              {len(report['failures'])}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generic topic corpus seeder. Works for ANY topic with "
            "a topic_packs/<topic>.toml file. No code changes needed "
            "to add a new topic."
        ),
    )
    parser.add_argument(
        "--topic", required=False,
        help="Topic name matching a topic_packs/<topic>.toml file "
             "(e.g. metformin, rapamycin, GLP-1, statins).",
    )
    parser.add_argument(
        "--limit", type=int, default=500,
        help="Max papers to fetch per topic (default: 30).",
    )
    parser.add_argument(
        "--max-per-source", type=int, default=200,
        help="Max hits per source per query (default: 15).",
    )
    parser.add_argument(
        "--sources", nargs="+",
        help="Override default source set. Pass space-separated "
             "names (e.g. pubmed europepmc openalex).",
    )
    parser.add_argument(
        "--list-sources", action="store_true",
        help="Print all available sources + their auth status.",
    )
    args = parser.parse_args(argv)

    if args.list_sources:
        print("\n=== Available Sources ===\n", file=sys.stderr)
        print(
            f"{'name':<20} {'default-on':<12} "
            f"{'auth env var':<25} enabled-now",
            file=sys.stderr,
        )
        print("-" * 80, file=sys.stderr)
        for s in list_available_sources():
            print(
                f"{s['name']:<20} "
                f"{str(s['default_enabled']):<12} "
                f"{str(s['auth_env_var'] or '—'):<25} "
                f"{s['currently_enabled']}",
                file=sys.stderr,
            )
        return 0

    if not args.topic:
        parser.error("--topic required (or --list-sources)")

    try:
        report = asyncio.run(_do_seed(
            args.topic,
            limit=args.limit,
            max_per_source=args.max_per_source,
            sources=args.sources,
        ))
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
