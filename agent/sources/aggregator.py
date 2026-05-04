"""SourceAggregator — fan-out across all wired source clients.

Used by `scripts/seed_topic_corpus.py --auto-corpus` to discover a
fresh corpus per topic without manual triage. The aggregator
queries every enabled source in parallel, dedupes by DOI / PMCID /
title, ranks by query-relevance + tier (clinical trial > journal
article > preprint), and returns the top-N hits.

No topic-specific logic. Reads the topic pack for query strings
+ alias whitelist; everything else is generic.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Iterable

import httpx

from agent.types import RawHit


# --- Source registry --------------------------------------------------
# Map: name → (client_class, default_enabled, requires_auth_env_var)
# Default-enabled set is the no-auth-required free APIs.

def _build_registry() -> dict:
    """Lazy import + register all source clients. Returns:
    {name: (client_instance, default_enabled, auth_env_var_or_None)}.
    """
    from agent.sources.pubmed import PubMedClient
    from agent.sources.europepmc import EuropePMCClient
    from agent.sources.openalex import OpenAlexClient
    from agent.sources.clinicaltrials import ClinicalTrialsClient
    from agent.sources.biorxiv import BioRxivClient
    from agent.sources.semantic_scholar import SemanticScholarClient
    from agent.sources.crossref import CrossrefClient
    from agent.sources.unpaywall import UnpaywallClient
    from agent.sources.core import CoreClient
    from agent.sources.doaj import DoajClient
    from agent.sources.openaire import OpenAireClient
    from agent.sources.pmc_oai import PmcOaiClient
    from agent.sources.chembl import ChemblClient
    return {
        # Tier 1: free, no auth, in default discovery set
        "pubmed": (PubMedClient(), True, None),
        "europepmc": (EuropePMCClient(), True, None),
        "openalex": (OpenAlexClient(), True, None),
        "clinicaltrials": (
            ClinicalTrialsClient(), True, None,
        ),
        "biorxiv": (BioRxivClient(), True, None),
        "semanticscholar": (
            SemanticScholarClient(), True, None,
        ),
        "crossref": (CrossrefClient(), True, None),
        "doaj": (DoajClient(), True, None),
        "openaire": (OpenAireClient(), True, None),
        "pmc_oai": (PmcOaiClient(), True, None),
        # Tier 2: free with API key (off by default unless key set)
        "core": (
            CoreClient(), False, "CORE_API_KEY",
        ),
        # Tier 3: supporting (drug pharmacology, opt-in)
        "chembl": (ChemblClient(), False, None),
        # Tier 4: lookup-only (DOI → OA URL, used post-hoc)
        "unpaywall": (
            UnpaywallClient(), False, None,
        ),
    }


def list_available_sources() -> list[dict]:
    """Public listing for status/audit. Returns name + auth_env_var
    + whether it's currently enabled."""
    out = []
    for name, (client, default_enabled, auth_env) in (
        _build_registry().items()
    ):
        is_enabled = default_enabled and (
            auth_env is None or os.environ.get(auth_env) is not None
        )
        out.append({
            "name": name,
            "default_enabled": default_enabled,
            "auth_env_var": auth_env,
            "currently_enabled": is_enabled,
        })
    return out


@dataclass(frozen=True, slots=True)
class AggregatedHit:
    """Deduplicated hit with provenance from each source that
    returned it. `sources` lists the source names that produced
    this paper; `n_sources` = how many independent sources had
    it (more sources = higher relevance signal)."""
    title: str
    abstract: str
    doi: str | None
    pmid: str | None
    nct: str | None
    year: int | None
    url: str
    venue: str | None
    sources: tuple[str, ...]
    n_sources: int


def _dedupe_key(hit: RawHit) -> str:
    """Pick a strong dedup key. DOI > PMID > NCT > title-prefix."""
    if hit.doi:
        return f"doi:{hit.doi}"
    if hit.pmid:
        return f"pmid:{hit.pmid}"
    if hit.nct:
        return f"nct:{hit.nct}"
    # Fall back to title (lowercased, first 80 chars)
    return f"title:{hit.title.lower()[:80]}"


async def discover(
    topic_keywords: str,
    *,
    enabled_sources: Iterable[str] | None = None,
    limit_per_source: int = 25,
    timeout: float = 60.0,
) -> list[AggregatedHit]:
    """Fan-out search across all enabled sources for the given
    keyword query. Returns deduplicated, source-merged hits.

    `topic_keywords` is a free-text query like 'rapamycin AND
    aging AND human'. `enabled_sources` overrides the default set;
    pass None to use registry defaults (filtered by env-var auth)."""
    registry = _build_registry()
    if enabled_sources is None:
        # Default: all default_enabled sources whose auth is met
        enabled_sources = [
            name for name, (_, default_en, auth_env)
            in registry.items()
            if default_en and (
                auth_env is None or os.environ.get(auth_env)
            )
        ]

    async def _safe_search(name: str, client) -> list[RawHit]:
        try:
            return await client.search(
                http, topic_keywords, limit=limit_per_source,
            )
        except (httpx.HTTPError, ValueError, OSError) as e:
            print(
                f"  ! source {name} failed: "
                f"{type(e).__name__}: {str(e)[:80]}",
            )
            return []

    async with httpx.AsyncClient(
        timeout=timeout,
        headers={
            "User-Agent": "researka/1.0 (multi-source discovery)",
        },
    ) as http:
        tasks = []
        for name in enabled_sources:
            if name not in registry:
                continue
            client, _, _ = registry[name]
            tasks.append(_safe_search(name, client))
        results = await asyncio.gather(
            *tasks, return_exceptions=False,
        )

    # Flatten + dedupe
    all_hits: list[RawHit] = []
    for r in results:
        all_hits.extend(r)
    grouped: dict[str, list[RawHit]] = {}
    for hit in all_hits:
        key = _dedupe_key(hit)
        grouped.setdefault(key, []).append(hit)

    out: list[AggregatedHit] = []
    for key, hits in grouped.items():
        # Pick best fields across sources (longest abstract wins,
        # any DOI, any PMID, etc.)
        best_abstract = max(
            (h.abstract for h in hits), key=len, default="",
        )
        best_title = max(
            (h.title for h in hits), key=len, default="",
        )
        doi = next((h.doi for h in hits if h.doi), None)
        pmid = next((h.pmid for h in hits if h.pmid), None)
        nct = next((h.nct for h in hits if h.nct), None)
        year = next(
            (h.year for h in hits if h.year is not None), None,
        )
        url = next(
            (h.url for h in hits if h.url and "doi.org" in h.url),
            hits[0].url,
        )
        venue = next(
            (h.venue for h in hits if h.venue), None,
        )
        source_names = tuple(sorted({h.source for h in hits}))
        out.append(AggregatedHit(
            title=best_title,
            abstract=best_abstract,
            doi=doi, pmid=pmid, nct=nct, year=year,
            url=url, venue=venue,
            sources=source_names,
            n_sources=len(source_names),
        ))

    # Rank: more sources = higher confidence
    out.sort(key=lambda h: (-h.n_sources, -(h.year or 0)))
    return out
