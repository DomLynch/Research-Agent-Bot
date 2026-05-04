"""bioRxiv adapter — biology preprints.

bioRxiv has no native keyword-search endpoint (their official API at
api.biorxiv.org is detail/lookup only). We use Europe PMC's preprint
overlay (SRC:PPR + PUB_TYPE:Preprint) as a search proxy. medRxiv
preprints flow through the same Europe PMC overlay but are exposed via
agent/sources/medrxiv.py with venue-based filtering. THIS adapter
filters down to bioRxiv-only records so the two sources have clean
non-overlapping provenance.

No auth required. Rate limit: gentle, ~10 rps.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

# Europe PMC's preprint-only filter is the canonical way to search
# bioRxiv programmatically (bioRxiv's own API is detail-only, no
# search). SRC:PPR limits to preprint sources.
_BIORXIV_SEARCH_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
)


class BioRxivClient:
    """bioRxiv preprint search via Europe PMC's preprint filter.
    Filters to bioRxiv-only records (medRxiv is exposed by
    agent.sources.medrxiv.MedRxivClient). Returns RawHit-shaped records."""

    name = "biorxiv"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "query": (
                f"({clean_text(query, limit=200)}) AND SRC:PPR "
                "AND (PUB_TYPE:Preprint)"
            ),
            "format": "json",
            "pageSize": str(max(1, min(limit, 25))),
            "resultType": "core",
        }
        response = await client.get(_BIORXIV_SEARCH_URL, params=params)
        response.raise_for_status()
        records = (
            response.json().get("resultList", {}).get("result", [])
        )
        return [
            hit for hit in (
                self._parse(r, query=query) for r in records
            )
            if hit
        ]

    def _parse(
        self, record: dict[str, Any], *, query: str,
    ) -> RawHit | None:
        title = clean_text(record.get("title"), limit=300)
        abstract = clean_text(
            record.get("abstractText"), limit=4000,
        )
        if not title or not abstract:
            return None
        doi = normalize_doi(record.get("doi"))
        # bioRxiv-only filter (medRxiv is exposed by MedRxivClient).
        venue_raw = (record.get("journalTitle") or "").lower()
        is_biorxiv = "biorxiv" in venue_raw
        if not is_biorxiv:
            book = record.get("bookOrReportDetails") or {}
            pub = (book.get("publisher") or "").lower()
            is_biorxiv = "biorxiv" in pub
        if not is_biorxiv:
            return None
        year_raw = clean_text(record.get("pubYear"), limit=8)
        year: int | None = (
            int(year_raw) if year_raw.isdigit() else None
        )
        url = (
            f"https://doi.org/{doi}" if doi
            else "https://www.biorxiv.org/"
        )
        venue = clean_text(
            record.get("journalTitle"), limit=200,
        ) or "bioRxiv preprint"
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
