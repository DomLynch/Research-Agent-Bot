"""Query plan + parallel source fanout + dedup.

Owns ONE shared httpx.AsyncClient that's passed into every adapter so TCP
connections and the polite User-Agent header are reused across the fan-out.
Adapters do not own clients; they receive one.

Pipeline:
  topic + criteria -> plan_queries() -> per-source query strings
  asyncio.gather(adapter.search(client, q) for adapter, q in plan)
  -> flat list[RawHit]
  -> dedup by DOI / PMID / NCT / normalized-title
  -> 1-indexed list[Source] + abstracts_by_ref dict
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence

import httpx

from agent.sources._base import USER_AGENT, SourceClient
from agent.types import RawHit, Source

DEFAULT_LIMIT_PER_SOURCE = 8
TIMEOUT_SEC = 20.0


def plan_queries(topic: str, criteria: str) -> list[str]:
    """Translate (topic, criteria) into one or more retrieval query strings.

    Mental model:
      `topic`    = terms that should appear in real paper / trial text (sent
                   to source adapters).
      `criteria` = downstream filters interpreted by bundle.py (year cutoff,
                   strict-eligibility rules, directness checks). NOT joined
                   into the retrieval query because filter words like "RCT"
                   match poorly in some indexes (e.g. ClinicalTrials.gov).

    V1 intentionally keeps this simple: one query, just the topic.
    """
    base = topic.strip()
    return [base] if base else []


async def retrieve(
    topic: str,
    domain: str,
    criteria: str,
    *,
    sources: Sequence[SourceClient],
    limit_per_source: int = DEFAULT_LIMIT_PER_SOURCE,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[Source], dict[int, str], dict[int, dict]]:
    """Run the fanout and return (sources, abstracts_by_ref, raw_signals_by_ref).

    `raw_signals_by_ref` carries the surviving RawHit.raw dict for each
    deduped source — bundle.py reads `has_results` from CT.gov entries via
    this channel, and downstream stages can use it without re-fetching.

    `client` is exposed for tests/scripts that want to inject a custom transport
    (mock, captured-fixture replay, custom timeout). When None, a fresh
    AsyncClient is created and torn down.
    """
    queries = plan_queries(topic, criteria)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    async def _run(c: httpx.AsyncClient) -> list[RawHit]:
        tasks = [
            adapter.search(c, q, limit=limit_per_source)
            for adapter in sources
            for q in queries
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        flat: list[RawHit] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            flat.extend(r)
        return flat

    if client is not None:
        raw = await _run(client)
    else:
        async with httpx.AsyncClient(timeout=TIMEOUT_SEC, headers=headers) as fresh:
            raw = await _run(fresh)

    return normalize_and_dedup(raw)


def normalize_and_dedup(
    hits: Sequence[RawHit],
) -> tuple[list[Source], dict[int, str], dict[int, dict]]:
    """Deduplicate by strongest available identity key, then assign refs.

    Identity-key precedence (strongest first):
      DOI  > PMID > NCT > normalized-title (lowercased, alphanumeric only)

    Returns (sources, abstracts_by_ref, raw_signals_by_ref). The raw signals
    are the original adapter `RawHit.raw` dicts, preserved so bundle.py can
    read adapter-specific signals (e.g. `has_results` from CT.gov).
    """
    seen: dict[str, RawHit] = {}
    for hit in hits:
        key = _identity_key(hit)
        if not key or key in seen:
            continue
        seen[key] = hit

    sources: list[Source] = []
    abstracts: dict[int, str] = {}
    raw_signals: dict[int, dict] = {}
    for ref, hit in enumerate(seen.values(), start=1):
        sources.append(
            Source(
                ref=ref,
                title=hit.title,
                year=hit.year,
                url=hit.url,
                source=hit.source,
                doi=hit.doi,
                pmid=hit.pmid,
                nct=hit.nct,
                venue=hit.venue,
            )
        )
        abstracts[ref] = hit.abstract
        raw_signals[ref] = dict(hit.raw)
    return sources, abstracts, raw_signals


def _identity_key(hit: RawHit) -> str:
    if hit.doi:
        return f"doi:{hit.doi.lower()}"
    if hit.pmid:
        return f"pmid:{hit.pmid}"
    if hit.nct:
        return f"nct:{hit.nct.upper()}"
    title = re.sub(r"[^a-z0-9]+", "", (hit.title or "").lower())
    return f"title:{title}" if title else ""
