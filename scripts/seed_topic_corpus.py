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
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DISCOVERY_TIMEOUT_SECONDS = 30.0

from agent.sources.aggregator import (  # noqa: E402
    discover, list_available_sources,
)
from agent.topic_pack import (  # noqa: E402
    TopicPack, load_topic_pack,
)
from agent.topic_pack_store import load_generated_topic_pack  # noqa: E402
from agent.wave_retrieval import run_waves  # noqa: E402
from agent.retrieval_modes import GLOBAL_SAFETY_CAP, resolve_params  # noqa: E402
from agent.corpus_pipeline import (  # noqa: E402
    classify_and_filter, extraction_pools_for_pack, format_funnel_md,
    topic_aliases_for_classification,
)
import v3_optional_adapters as _optional_adapters  # noqa: E402
from source_topic_specificity import is_source_topic_specific, source_gate_aliases  # noqa: E402


def _manifest_entry_to_dict(entry) -> dict[str, Any]:
    return {
        "paper_id": entry.classification.paper_id,
        "doi": entry.hit.doi,
        "pmid": entry.hit.pmid,
        "title": entry.hit.title[:240],
        "year": entry.hit.year,
        "n_sources": entry.hit.n_sources,
        "sources": list(entry.hit.sources),
        "classification": entry.classification.classification,
        "score": entry.classification.score,
        "reason": entry.classification.reason,
        "pool": entry.pool,
        "keep_for_extraction": entry.keep_for_extraction,
    }


def _manifest_to_dict(manifest) -> dict[str, Any]:
    return {
        "topic": manifest.topic,
        "funnel": dict(manifest.funnel),
        "per_wave_stats": [dict(s) for s in manifest.per_wave_stats],
        "entries": [_manifest_entry_to_dict(e) for e in manifest.entries],
    }


def _topic_pack_path(topic: str) -> Path:
    return REPO / "topic_packs" / f"{topic}.toml"


def _load_topic_pack(topic: str) -> TopicPack:
    pack_path = _topic_pack_path(topic)
    if pack_path.exists():
        return load_topic_pack(pack_path)
    return load_generated_topic_pack(topic, REPO / "topic_packs_db")


def _discovery_timeout_seconds() -> float:
    raw = os.environ.get(
        "RESEARCH_AGENT_DISCOVERY_TIMEOUT_SECONDS",
        str(DISCOVERY_TIMEOUT_SECONDS),
    )
    try:
        return min(120.0, max(1.0, float(raw)))
    except ValueError:
        return DISCOVERY_TIMEOUT_SECONDS


def _corpus_paths(topic: str) -> tuple[Path, Path]:
    base = REPO / "docs" / "quality-reference" / topic
    return base / "quant_claims", base / "parsed"


def _paper_id_from_parsed_path(path: Path) -> str:
    return path.stem.replace(".paper_sections", "")


def _pmcid_from_parsed_path(path: Path) -> str | None:
    paper_id = _paper_id_from_parsed_path(path)
    prefix = paper_id.split("_", 1)[0]
    return prefix if prefix.startswith("PMC") else None


def _slug(text: str, *, limit: int = 60) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")[:limit]


def _paper_id_from_hit(hit) -> str:
    slug = _slug(hit.title or "untitled")
    if hit.pmid:
        return f"PMID{hit.pmid}_{slug}" if slug else f"PMID{hit.pmid}"
    if hit.doi:
        return f"DOI_{_slug(hit.doi, limit=80)}_{slug}".strip("_")
    return f"HIT_{slug}" if slug else "HIT_untitled"


def _hit_specific_to_topic(topic: str, pack: TopicPack, hit) -> bool:
    text = " ".join(str(getattr(hit, attr, "") or "") for attr in ("title", "abstract", "venue"))
    return is_source_topic_specific(topic, text, aliases=source_gate_aliases(topic, pack.aliases))


def _extraction_entry_rank(entry: Any) -> tuple[int, int, int, int, str]:
    pool_rank = {"core": 0, "adjacent": 1, "background": 2}.get(entry.pool, 3)
    hit = entry.hit
    return (
        pool_rank,
        -int(entry.classification.score),
        -int(hit.n_sources or 0),
        -int(hit.year or 0),
        str(hit.title or "").lower(),
    )


def _parsed_paths_for_pmcid(parsed_dir: Path, pmcid: str) -> list[Path]:
    return sorted(parsed_dir.glob(f"{pmcid}_*.paper_sections.json"))


def _authors_from_europepmc_result(result: dict[str, Any]) -> list[str]:
    raw = (result.get("authorString") or "").strip()
    if not raw:
        return []
    authors: list[str] = []
    for part in raw.split(","):
        clean = " ".join(part.strip().split())
        if not clean:
            continue
        tokens = clean.split()
        if len(tokens) >= 2 and re.fullmatch(r"[A-Z.]{1,8}", tokens[-1]):
            clean = " ".join([tokens[-1].replace(".", ""), *tokens[:-1]])
        authors.append(clean)
        if len(authors) >= 20:
            break
    return authors


def _write_abstract_fallback(
    hit, parsed_dir: Path, *, reason: str,
    resolved_meta: dict[str, Any] | None = None,
) -> str | None:
    resolved_meta = resolved_meta or {}
    paper_id = _paper_id_from_hit(hit)
    docling = _optional_adapters.write_docling_paper_sections(
        source_uri=hit.url or "",
        parsed_dir=parsed_dir,
        paper_id=paper_id,
        metadata={
            "title": hit.title or "",
            "authors": resolved_meta.get("authors") or [],
            "year": resolved_meta.get("year") or hit.year,
            "journal": resolved_meta.get("journal") or hit.venue or "",
            "doi": resolved_meta.get("doi") or hit.doi or "",
            "pmid": resolved_meta.get("pmid") or hit.pmid or "",
        },
        reason=reason,
    )
    if docling.get("status") == "passed":
        return str(docling.get("paper_id") or paper_id)
    abstract = (
        hit.abstract or resolved_meta.get("abstract") or ""
    ).strip()
    if not abstract:
        return None
    sections = {
        "abstract": abstract,
        "introduction": "",
        "methods": "",
        "results": "",
        "discussion": "",
        "limitations": "",
        "conclusion": "",
        "references": "",
    }
    doc = {
        "paper_id": paper_id,
        "source_pdf": hit.url or "",
        "title": hit.title or "",
        "authors": resolved_meta.get("authors") or [],
        "year": resolved_meta.get("year") or hit.year,
        "journal": resolved_meta.get("journal") or hit.venue or "",
        "doi": resolved_meta.get("doi") or hit.doi or "",
        "pmid": resolved_meta.get("pmid") or hit.pmid or "",
        "trial_ids": sorted(set(re.findall(r"\bNCT\d{8}\b", abstract))),
        "sections": sections,
        "tables": [],
        "figures": [],
        "extraction_quality": {
            "section_coverage": ["abstract"],
            "table_count": 0,
            "figure_count": 0,
            "reference_count": 0,
            "warnings": [f"abstract-fallback:{reason}"],
        },
    }
    (parsed_dir / f"{paper_id}.paper_sections.json").write_text(
        json.dumps(doc, indent=2),
    )
    return paper_id


async def _resolve_pmcid(
    aggregated_hit, *, http,
) -> tuple[str | None, dict[str, Any]]:
    """Resolve a discovered hit (with DOI/PMID) to a PMCID for
    full-text fetch via Europe PMC."""
    if not (aggregated_hit.doi or aggregated_hit.pmid):
        return None, {}
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
            return None, {}
        data = r.json()
    except Exception:
        return None, {}
    hits = data.get("resultList", {}).get("result", [])
    if not hits:
        return None, {}
    hit = hits[0]
    meta = {
        "authors": _authors_from_europepmc_result(hit),
        "abstract": hit.get("abstractText") or "",
        "doi": hit.get("doi") or aggregated_hit.doi,
        "pmid": hit.get("pmid") or aggregated_hit.pmid,
        "journal": hit.get("journalTitle")
        or hit.get("journalInfo", {}).get("journal", {}).get("title", ""),
        "year": int(hit["pubYear"]) if hit.get("pubYear") else aggregated_hit.year,
    }
    return hit.get("pmcid"), meta


async def _do_seed(
    topic: str,
    *,
    limit: int,
    max_per_source: int,
    sources: list[str] | None,
    force_extract: bool = False,
) -> dict[str, Any]:
    try:
        pack: TopicPack = _load_topic_pack(topic)
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(
            f"Topic pack not found for {topic!r}. Create topic_packs/{topic}.toml "
            f"or topic_packs_db/{topic}/latest.json."
        ) from exc

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
        wave_report = await run_waves(
            pack.retrieval,
            params=params,
            enabled_sources=sources,
            timeout=_discovery_timeout_seconds(),
        )
        manifest = classify_and_filter(
            wave_report, topic=topic,
            topic_aliases=topic_aliases_for_classification(pack),
            expected_slots=pack.expected_evidence_slots,
            exclude_terms=(
                pack.retrieval.exclude_terms if pack.retrieval else ()
            ),
        )
        # Write the corpus manifest for the dashboard / funnel
        manifest_path = (
            REPO / "docs/quality-reference" / topic
            / "corpus_manifest.json"
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(_manifest_to_dict(manifest), indent=2))
        (REPO / "docs/quality-reference" / topic
         / "corpus_manifest.md").write_text(
            format_funnel_md(manifest),
        )
        kept = manifest.kept()
        print(
            f"  → retrieved={manifest.funnel.get('retrieved', 0)} "
            f"keep={len(kept)} "
            f"core={manifest.funnel.get('extractable_core', 0)} "
            f"bg={manifest.funnel.get('extractable_background', 0)} "
            f"adj={manifest.funnel.get('extractable_adjacent', 0)}",
            file=sys.stderr,
        )
        active_pools = extraction_pools_for_pack(pack)
        candidates = [
            e for e in manifest.entries
            if e.keep_for_extraction and e.pool in active_pools
            and _hit_specific_to_topic(topic, pack, e.hit)
        ]
        selected = [e.hit for e in sorted(candidates, key=_extraction_entry_rank)[:limit]]
        print(
            f"=== Selecting top {len(selected)} "
            f"{'/'.join(sorted(active_pools))} hits for fetch "
            f"(limit={limit}) ===",
            file=sys.stderr,
        )
    else:
        if not pack.corpus_search_queries:
            raise ValueError(
                f"Topic pack {topic!r} has no [retrieval] block "
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
        selected = [h for h in deduped if _hit_specific_to_topic(topic, pack, h)][:limit]
        print(
            f"=== Selecting top {len(selected)} for fetch ===",
            file=sys.stderr,
        )

    # 2. Resolve PMCIDs (for full-text fetch)
    import httpx
    pmcids: list[str] = []
    paper_id_map: dict[str, dict] = {}
    pmcid_hit_map: dict[str, Any] = {}
    failures: list[dict] = []
    fallback_paper_ids: list[str] = []
    print("\n=== Resolving PMCIDs ===", file=sys.stderr)
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": "researka/1.0"},
    ) as http:
        for h in selected:
            pmcid, resolved_meta = await _resolve_pmcid(h, http=http)
            if pmcid:
                pmcids.append(pmcid)
                pmcid_hit_map[pmcid] = h
                paper_id_map[pmcid] = {
                    "title": h.title,
                    "doi": resolved_meta.get("doi") or h.doi,
                    "pmid": resolved_meta.get("pmid") or h.pmid,
                    "year": resolved_meta.get("year") or h.year,
                    "venue": resolved_meta.get("journal") or h.venue,
                    "authors": resolved_meta.get("authors") or [],
                    "sources": list(h.sources),
                }
                pmcid_hit_map[f"{pmcid}:meta"] = resolved_meta
                print(f"  ✓ {pmcid}: {h.title[:70]}", file=sys.stderr)
            else:
                failures.append({
                    "title": h.title[:80],
                    "doi": h.doi, "pmid": h.pmid,
                    "reason": "no PMCID (closed-access or unindexed)",
                })
                fallback_id = _write_abstract_fallback(
                    h, parsed_dir, reason="no_pmcid",
                    resolved_meta=resolved_meta,
                )
                if fallback_id:
                    fallback_paper_ids.append(fallback_id)

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
        for pmcid in pmcids:
            if _parsed_paths_for_pmcid(parsed_dir, pmcid):
                continue
            fallback_id = _write_abstract_fallback(
                pmcid_hit_map[pmcid], parsed_dir,
                reason="fulltext_unavailable",
                resolved_meta=pmcid_hit_map.get(f"{pmcid}:meta"),
            )
            if fallback_id:
                fallback_paper_ids.append(fallback_id)

    # 4. Extract quant claims
    print(
        "\n=== Extracting quant claims ===",
        file=sys.stderr,
    )
    n_extracted = 0
    selected_pmcids = set(pmcids)
    fallback_id_set = set(fallback_paper_ids)
    active_paper_ids: list[str] = []
    parsed_files = [
        pf for pf in parsed_dir.glob("*.paper_sections.json")
        if (
            _pmcid_from_parsed_path(pf) in selected_pmcids
            or _paper_id_from_parsed_path(pf) in fallback_id_set
        )
    ]
    for pf in parsed_files:
        paper_id = _paper_id_from_parsed_path(pf)
        active_paper_ids.append(paper_id)
        target = quant_dir / (
            paper_id + ".quant_claims.json"
        )
        if target.exists() and not force_extract:
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
                env={**os.environ, "TOPIC_DOMAIN": topic},
            )
            n_extracted += 1
        except subprocess.CalledProcessError as e:
            print(
                f"  ! extract failed for {pf.name}: {e}",
                file=sys.stderr,
            )

    # Write report. `deduped` only exists on the legacy path; the
    # calibrated path uses run_waves and writes its own corpus_manifest
    # (see Slice 6 step 4d). Use locals() to fall back to len(selected)
    # when running on the calibrated branch.
    n_unique = len(deduped) if "deduped" in locals() else len(selected)
    n_queries = len(pack.corpus_search_queries) if (
        pack.corpus_search_queries
    ) else 0
    report = {
        "topic": topic,
        "retrieval_mode": (
            "calibrated" if pack.retrieval is not None else "legacy"
        ),
        "n_queries": n_queries,
        "n_unique_candidates": n_unique,
        "n_selected_for_fetch": len(selected),
        "n_pmcid_resolved": len(pmcids),
        "n_abstract_fallback": len(fallback_id_set),
        "n_extracted": n_extracted,
        "active_pools": sorted(active_pools)
        if pack.retrieval is not None else ["legacy"],
        "active_pmcids": sorted(selected_pmcids),
        "active_paper_ids": sorted(set(active_paper_ids)),
        "abstract_fallback_paper_ids": sorted(fallback_id_set),
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
        f"Abstract fallbacks:    {report.get('n_abstract_fallback', 0)}\n"
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
        "--limit", type=int, default=GLOBAL_SAFETY_CAP,
        help=(
            "Universal fetch safety cap per topic "
            f"(default: {GLOBAL_SAFETY_CAP}; circuit breaker, not target)."
        ),
    )
    parser.add_argument(
        "--max-per-source", type=int, default=GLOBAL_SAFETY_CAP,
        help=(
            "Universal source safety cap per query "
            f"(default: {GLOBAL_SAFETY_CAP}; legacy fallback only)."
        ),
    )
    parser.add_argument(
        "--sources", nargs="+",
        help="Override default source set. Pass space-separated "
             "names (e.g. pubmed europepmc openalex).",
    )
    parser.add_argument(
        "--force-extract", action="store_true",
        help="Rebuild selected quant_claims even if output files exist.",
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
            force_extract=args.force_extract,
        ))
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
