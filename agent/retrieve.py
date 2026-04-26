"""Query plan + parallel source fanout + dedup.

Owns ONE shared httpx.AsyncClient that's passed into every adapter so TCP
connections and the polite User-Agent header are reused across the fan-out.
Adapters do not own clients; they receive one.

Pipeline:
  topic -> plan_queries() -> per-source query strings
  asyncio.gather(adapter.search(client, q) for adapter, q in plan)
  -> flat list[RawHit]
  -> dedup by DOI / PMID / NCT (incl. NCT-in-abstract) / normalized-title
  -> 1-indexed list[Source] + abstracts_by_ref + raw_signals_by_ref
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence

import httpx

from agent.sources._base import USER_AGENT, SourceClient
from agent.types import RawHit, Source

DEFAULT_LIMIT_PER_SOURCE = 8
TIMEOUT_SEC = 20.0

# NCT identifiers like "NCT04098874" found in PubMed / Europe PMC abstracts
# allow us to merge a literature paper with its CT.gov registry entry — the
# same trial would otherwise be cited as two independent sources.
_NCT_IN_ABSTRACT_RE = re.compile(r"\bNCT\d{7,9}\b")

logger = logging.getLogger(__name__)


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

    Adapter ordering matters: when two adapters return the same study (matched
    via DOI / PMID / NCT, including NCT-in-abstract), the FIRST adapter wins.
    Pass adapters in priority order — typically PubMed first (best abstracts),
    then OpenAlex, EuropePMC, ClinicalTrials.gov.
    """
    queries = plan_queries(topic, criteria)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    async def _run(c: httpx.AsyncClient) -> list[RawHit]:
        plan = [
            (adapter, q)
            for adapter in sources
            for q in queries
        ]
        results = await asyncio.gather(
            *(adapter.search(c, q, limit=limit_per_source) for adapter, q in plan),
            return_exceptions=True,
        )
        flat: list[RawHit] = []
        for (adapter, q), r in zip(plan, results, strict=True):
            if isinstance(r, Exception):
                logger.warning(
                    "source %s failed for query %r: %s",
                    adapter.name, q, type(r).__name__ + ": " + str(r),
                )
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
    """Deduplicate by all available identity keys, first hit wins.

    Each hit yields one or more identity keys (DOI, PMID, NCT explicit, NCT
    found in abstract, or normalized title). A hit is kept only if NONE of
    its keys have already been claimed by an earlier hit. This collapses the
    PubMed paper for an RCT and its CT.gov registry entry into one source
    when the abstract cites the NCT — preventing the same study from being
    cited twice as if it were independent corroboration.

    Returns (sources, abstracts_by_ref, raw_signals_by_ref). The raw signals
    are the original adapter `RawHit.raw` dicts, preserved so bundle.py can
    read adapter-specific signals (e.g. `has_results` from CT.gov).
    """
    claimed: set[str] = set()
    kept: list[RawHit] = []
    for hit in hits:
        keys = _identity_keys(hit)
        if not keys:
            continue
        if any(k in claimed for k in keys):
            continue
        kept.append(hit)
        claimed.update(keys)

    sources: list[Source] = []
    abstracts: dict[int, str] = {}
    raw_signals: dict[int, dict] = {}
    for ref, hit in enumerate(kept, start=1):
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


def _identity_keys(hit: RawHit) -> list[str]:
    """All identity keys this hit owns. First key is the canonical strongest."""
    keys: list[str] = []
    if hit.doi:
        keys.append(f"doi:{hit.doi.lower()}")
    if hit.pmid:
        keys.append(f"pmid:{hit.pmid.lstrip('0') or '0'}")
    if hit.nct:
        keys.append(f"nct:{hit.nct.upper()}")
    # Cross-source link: a literature paper that cites an NCT identifier in its
    # abstract is the same study as the CT.gov registry record for that NCT.
    for match in _NCT_IN_ABSTRACT_RE.finditer(hit.abstract or ""):
        keys.append(f"nct:{match.group(0).upper()}")
    if not keys:
        title = re.sub(r"[^a-z0-9]+", "", (hit.title or "").lower())
        if title:
            keys.append(f"title:{title}")
    return keys
