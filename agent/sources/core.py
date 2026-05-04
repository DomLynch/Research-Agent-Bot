"""CORE adapter — open-access aggregator (200M+ records).

Endpoint: https://api.core.ac.uk/v3/search/works
Free tier: 1000 requests/day with API key. Set CORE_API_KEY env var.

Without an API key, returns empty (CORE requires registration).
Sign up free at https://core.ac.uk/services/api.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

_CORE_URL = "https://api.core.ac.uk/v3/search/works"


class CoreClient:
    name = "core"

    def _headers(self) -> dict[str, str]:
        api_key = os.environ.get("CORE_API_KEY")
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {}

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        if not os.environ.get("CORE_API_KEY"):
            # Without auth, CORE returns 401. Skip silently.
            return []
        params = {
            "q": clean_text(query, limit=240),
            "limit": str(max(1, min(limit, 25))),
        }
        try:
            response = await client.get(
                _CORE_URL, params=params,
                headers=self._headers(), timeout=20.0,
            )
            if response.status_code in (401, 403, 429):
                return []
            response.raise_for_status()
        except httpx.HTTPError:
            return []
        results = response.json().get("results", [])
        return [
            hit for hit in (
                self._parse(r, query=query) for r in results
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
        doi = normalize_doi(record.get("doi"))
        year = record.get("yearPublished")
        if year is not None:
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None
        venue = clean_text(
            (record.get("publisher") or "")[:200], limit=200,
        ) or None
        url = (
            record.get("downloadUrl") or
            (f"https://doi.org/{doi}" if doi else
             record.get("sourceFulltextUrls", [None])[0])
            or "https://core.ac.uk/"
        )
        return RawHit(
            source=self.name,
            title=title,
            abstract=abstract,
            year=year,
            url=url,
            doi=doi,
            pmid=None,
            nct=None,
            venue=venue,
            raw=record,
        )
