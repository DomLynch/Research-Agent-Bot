"""Semantic Scholar adapter.

Endpoint: https://api.semanticscholar.org/graph/v1/paper/search
Authenticated (with SEMANTIC_SCHOLAR_API_KEY): 1 req/s cumulative
across all endpoints. Without key: ~100 req/5min public tier.

Refactor 2026-05-04: added a class-level async rate limit (1 req/s)
to keep the SourceAggregator's parallel fan-out below threshold.
The user's S2 key (s2k-...) was approved with the standard 1 rps
limit — exceeding that gets 429 + the key gets temporarily blocked.

Returns rich citation graph + abstract + open-access PDFs.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi, safe_get_json
from agent.types import RawHit

_SEMANTIC_SCHOLAR_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
)
_FIELDS = (
    "paperId,title,abstract,year,authors,venue,externalIds,"
    "openAccessPdf,citationCount"
)

# Global rate-limit guard: at most 1 request every 1.1 seconds
# (slight buffer above the 1 rps cumulative limit). Async-safe lock
# protects last-call timestamp across concurrent SourceAggregator
# fan-outs.
_RATE_LIMIT_SEC = 1.1
_rate_lock = asyncio.Lock()
_last_call_ts: float = 0.0


async def _await_rate_limit() -> None:
    """Async-safe rate limiter: ensures at most 1 call per
    _RATE_LIMIT_SEC seconds, cumulative across all instances."""
    global _last_call_ts
    async with _rate_lock:
        now = time.monotonic()
        wait = _RATE_LIMIT_SEC - (now - _last_call_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_ts = time.monotonic()


class SemanticScholarClient:
    name = "semanticscholar"

    def _headers(self) -> dict[str, str]:
        api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        if api_key:
            return {"x-api-key": api_key}
        return {}

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "query": clean_text(query, limit=3000),
            "limit": str(max(1, min(limit, 100))),
            "fields": _FIELDS,
        }
        # Rate-limit gate (1 req per 1.1s cumulative)
        await _await_rate_limit()
        payload = await safe_get_json(
            client, _SEMANTIC_SCHOLAR_URL,
            params=params, headers=self._headers(),
        )
        if payload is None:
            return []
        data = payload.get("data", [])
        return [
            hit for hit in (
                self._parse(r, query=query) for r in data
            )
            if hit
        ]

    def _parse(
        self, record: dict[str, Any], *, query: str,
    ) -> RawHit | None:
        title = clean_text(record.get("title"), limit=300)
        abstract = clean_text(record.get("abstract"), limit=4000)
        if not title or not abstract:
            return None
        ext = record.get("externalIds") or {}
        doi = normalize_doi(ext.get("DOI"))
        pmid = clean_text(ext.get("PubMed"), limit=32) or None
        venue = clean_text(record.get("venue"), limit=200) or None
        year = record.get("year")
        if year is not None:
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None
        oa = record.get("openAccessPdf") or {}
        url = (
            oa.get("url") or
            (f"https://doi.org/{doi}" if doi else
             f"https://www.semanticscholar.org/paper/"
             f"{record.get('paperId', '')}")
        )
        return RawHit(
            source=self.name,
            title=title,
            abstract=abstract,
            year=year,
            url=url,
            doi=doi,
            pmid=pmid,
            nct=None,
            venue=venue,
            raw=record,
        )
