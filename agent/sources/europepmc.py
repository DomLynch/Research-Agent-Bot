"""Europe PMC adapter.

Endpoint: https://www.ebi.ac.uk/europepmc/webservices/rest/search
Returns rich metadata for biomedical literature including PMID, PMCID,
DOI, journal, abstract, in one round-trip. No auth required.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class EuropePMCClient:
    name = "europepmc"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "query": clean_text(query, limit=240),
            "format": "json",
            "pageSize": str(max(1, min(limit, 25))),
            # 'core' is required to get abstractText. 'lite' omits it which
            # would cause every result to be silently dropped.
            "resultType": "core",
        }
        response = await client.get(EUROPEPMC_SEARCH_URL, params=params)
        response.raise_for_status()
        result_list = response.json().get("resultList") or {}
        records = result_list.get("result") or []
        return [hit for hit in (self._parse_record(r, query=query) for r in records) if hit]

    def _parse_record(self, record: dict[str, Any], *, query: str) -> RawHit | None:
        title = clean_text(record.get("title"), limit=300)
        abstract = clean_text(record.get("abstractText"))
        if not title or not abstract:
            return None
        doi = normalize_doi(record.get("doi"))
        pmid = clean_text(record.get("pmid"), limit=32) or None
        venue = clean_text(record.get("journalTitle"), limit=200) or None
        year_raw = clean_text(record.get("pubYear"), limit=8)
        year: int | None = int(year_raw) if year_raw.isdigit() else None
        # Prefer explicit DOI URL when available, else fall back to Europe PMC
        # article page so the link is always resolvable.
        ext_id = clean_text(record.get("id"), limit=64)
        ext_src = clean_text(record.get("source"), limit=16)
        if doi:
            url = f"https://doi.org/{doi}"
        elif ext_id and ext_src:
            url = f"https://europepmc.org/article/{ext_src}/{ext_id}"
        else:
            url = ""
        return RawHit(
            source="europepmc",
            title=title,
            abstract=abstract,
            year=year,
            url=url,
            doi=doi,
            pmid=pmid,
            venue=venue,
            raw={"query": clean_text(query, limit=240), "ext_id": ext_id, "ext_src": ext_src},
        )
