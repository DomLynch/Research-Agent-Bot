"""OpenAlex adapter.

Endpoint: https://api.openalex.org/works?search=...&per-page=N
Polite pool: include `mailto=` param. Returns abstract as inverted index
(word -> [positions]); we reconstitute it.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
POLITE_MAILTO = "research-agent@domlynch.com"
SELECT_FIELDS = (
    "id,doi,title,abstract_inverted_index,primary_location,publication_year"
)


class OpenAlexClient:
    name = "openalex"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "search": clean_text(query, limit=240),
            "per-page": str(max(1, min(limit, 25))),
            "select": SELECT_FIELDS,
            "mailto": POLITE_MAILTO,
        }
        response = await client.get(OPENALEX_WORKS_URL, params=params)
        response.raise_for_status()
        works = response.json().get("results", []) or []
        return [hit for hit in (self._parse_work(w, query=query) for w in works) if hit]

    def _parse_work(self, work: dict[str, Any], *, query: str) -> RawHit | None:
        title = clean_text(work.get("title"), limit=300)
        abstract = self._reconstitute_abstract(work.get("abstract_inverted_index"))
        if not title or not abstract:
            return None
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        venue = clean_text(source.get("display_name"), limit=200) or None
        url = location.get("landing_page_url") or work.get("id") or ""
        return RawHit(
            source="openalex",
            title=title,
            abstract=abstract,
            year=work.get("publication_year"),
            url=str(url),
            doi=normalize_doi(work.get("doi")),
            venue=venue,
            raw={"query": clean_text(query, limit=240), "openalex_id": work.get("id")},
        )

    @staticmethod
    def _reconstitute_abstract(inverted: Any) -> str:
        if not isinstance(inverted, dict):
            return ""
        positions: dict[int, str] = {}
        for word, indexes in inverted.items():
            if not isinstance(indexes, list):
                continue
            for idx in indexes:
                try:
                    positions[int(idx)] = str(word)
                except (TypeError, ValueError):
                    continue
        return clean_text(
            " ".join(positions[i] for i in sorted(positions)),
            limit=4000,
        )
