"""bioRxiv / medRxiv adapter.

Endpoint: https://api.biorxiv.org/details/biorxiv/<doi> + search via
relate.bjresearch.com (or the official Europe-PMC overlay since
bioRxiv lacks a true keyword-search API).

bioRxiv has no native search endpoint — we use Europe PMC's preprint
filter as a free proxy. Returns RawHit shape compatible with the
agent.sources contract.

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
    """bioRxiv / medRxiv preprint search via Europe PMC's preprint
    filter. Returns RawHit-shaped records."""

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
        # Filter out non-preprint sources that slip through
        venue_raw = (record.get("journalTitle") or "").lower()
        if (
            "biorxiv" not in venue_raw
            and "medrxiv" not in venue_raw
            and "preprint" not in venue_raw
        ):
            # Still accept if DOI starts with bioRxiv prefix
            if not (doi or "").startswith("10.1101/"):
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
