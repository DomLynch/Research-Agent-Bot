"""Crossref adapter.

Endpoint: https://api.crossref.org/works
Free, no auth. Optional polite-pool email via env CROSSREF_POLITE_EMAIL
gives faster + more reliable responses.

Returns DOI metadata + abstract (when available — many publishers
withhold abstracts from Crossref).
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi, safe_get_json
from agent.types import RawHit

_CROSSREF_URL = "https://api.crossref.org/works"


class CrossrefClient:
    name = "crossref"

    def _headers(self) -> dict[str, str]:
        email = os.environ.get("CROSSREF_POLITE_EMAIL")
        if email:
            return {"User-Agent": f"researka/1.0 (mailto:{email})"}
        return {"User-Agent": "researka/1.0"}

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[RawHit]:
        """Slice 8 step A: `offset` enables Crossref's native offset
        pagination. Default 0 keeps back-compat with non-paginated
        callers."""
        params = {
            "query": clean_text(query, limit=3000),
            "rows": str(max(1, min(limit, 1000))),
            "offset": str(max(0, offset)),
            "filter": "type:journal-article,has-abstract:true",
            "select": "DOI,title,abstract,issued,container-title,author",
        }
        data = await safe_get_json(
            client, _CROSSREF_URL,
            params=params, headers=self._headers(),
        )
        if data is None:
            return []
        items = data.get("message", {}).get("items", [])
        return [
            hit for hit in (
                self._parse(r, query=query) for r in items
            )
            if hit
        ]

    def _parse(
        self, record: dict[str, Any], *, query: str,
    ) -> RawHit | None:
        title_list = record.get("title") or []
        title = clean_text(
            title_list[0] if title_list else "", limit=300,
        )
        # Crossref abstracts often have JATS XML wrapping
        abstract = clean_text(record.get("abstract"), limit=4000)
        if not title or not abstract:
            return None
        doi = normalize_doi(record.get("DOI"))
        venue_list = record.get("container-title") or []
        venue = clean_text(
            venue_list[0] if venue_list else "", limit=200,
        ) or None
        # Issued date: { "date-parts": [[year, month, day]] }
        issued = record.get("issued", {}).get("date-parts", [[]])
        year = None
        if issued and issued[0]:
            try:
                year = int(issued[0][0])
            except (ValueError, TypeError):
                pass
        url = (
            f"https://doi.org/{doi}" if doi
            else "https://www.crossref.org/"
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
