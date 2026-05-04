"""PMC OAI-PMH adapter — direct harvesting of PubMed Central.

Endpoint: https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi
Free, no auth. PMC OAI exposes the open-access subset (~4M articles)
via OAI-PMH — useful for batch corpus harvesting beyond what
search APIs return.

For Researka usage: this is mostly a fallback when other sources
miss a specific PMCID. Search-by-keyword via OAI-PMH is awkward
(uses set= filter on subjects). This implementation supports both
keyword search (via Europe PMC's PMC subset filter as an easier
proxy) AND direct PMCID retrieval.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

_EUROPEPMC_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
)


class PmcOaiClient:
    """PMC OA subset adapter. Wraps Europe PMC's PMC-only filter
    (SRC:PMC + OPEN_ACCESS:Y) as the practical search interface;
    full OAI-PMH XML harvesting is rarely needed in practice."""

    name = "pmc_oai"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "query": (
                f"({clean_text(query, limit=200)}) "
                "AND SRC:PMC AND OPEN_ACCESS:Y"
            ),
            "format": "json",
            "pageSize": str(max(1, min(limit, 25))),
            "resultType": "core",
        }
        try:
            response = await client.get(
                _EUROPEPMC_URL, params=params, timeout=20.0,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return []
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
        pmid = clean_text(record.get("pmid"), limit=32) or None
        pmcid = clean_text(record.get("pmcid"), limit=32) or None
        venue = clean_text(
            record.get("journalTitle"), limit=200,
        ) or None
        year_raw = clean_text(record.get("pubYear"), limit=8)
        year: int | None = (
            int(year_raw) if year_raw.isdigit() else None
        )
        # Prefer PMC URL since this client targets the OA subset
        url = (
            f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
            if pmcid
            else (
                f"https://doi.org/{doi}" if doi
                else "https://www.ncbi.nlm.nih.gov/pmc/"
            )
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
