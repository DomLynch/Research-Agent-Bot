"""Semantic Scholar adapter.

Endpoint: https://api.semanticscholar.org/graph/v1/paper/search
Free tier (no auth): 100 requests / 5min. Optional API key for
higher rate limits — set SEMANTIC_SCHOLAR_API_KEY env var.

Returns rich citation graph + abstract + open-access PDFs.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

_SEMANTIC_SCHOLAR_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/search"
)
_FIELDS = (
    "paperId,title,abstract,year,authors,venue,externalIds,"
    "openAccessPdf,citationCount"
)


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
            "query": clean_text(query, limit=240),
            "limit": str(max(1, min(limit, 25))),
            "fields": _FIELDS,
        }
        response = await client.get(
            _SEMANTIC_SCHOLAR_URL, params=params,
            headers=self._headers(),
        )
        if response.status_code == 429:
            # Rate-limited — return empty rather than raising
            return []
        response.raise_for_status()
        data = response.json().get("data", [])
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
