"""DOAJ (Directory of Open Access Journals) adapter.

Endpoint: https://doaj.org/api/search/articles/<query>
Free, no auth. Returns articles from peer-reviewed OA journals only.
"""
from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi, safe_get_json
from agent.types import RawHit

_DOAJ_URL = "https://doaj.org/api/search/articles/"


class DoajClient:
    name = "doaj"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        q = urllib.parse.quote(clean_text(query, limit=3000))
        url = (
            f"{_DOAJ_URL}{q}"
            f"?pageSize={max(1, min(limit, 100))}"
        )
        data = await safe_get_json(client, url, timeout=15.0)
        if data is None:
            return []
        results = data.get("results", [])
        return [
            hit for hit in (
                self._parse(r, query=query) for r in results
            )
            if hit
        ]

    def _parse(
        self, record: dict[str, Any], *, query: str,
    ) -> RawHit | None:
        bib = record.get("bibjson", {})
        title = clean_text(bib.get("title"), limit=300)
        abstract = clean_text(bib.get("abstract"), limit=4000)
        if not title or not abstract:
            return None
        # Identifiers: list of {type, id}
        identifiers = bib.get("identifier", [])
        doi = None
        for ident in identifiers:
            if (ident.get("type") or "").lower() == "doi":
                doi = normalize_doi(ident.get("id"))
                break
        # Journal
        journal = bib.get("journal", {}).get("title", "")
        venue = clean_text(journal, limit=3000) or None
        # Year
        year = bib.get("year")
        if year is not None:
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None
        # URL: prefer fulltext
        url = None
        for link in bib.get("link", []):
            if (link.get("type") or "").lower() == "fulltext":
                url = link.get("url")
                break
        if not url:
            url = (
                f"https://doi.org/{doi}" if doi
                else "https://doaj.org/"
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
