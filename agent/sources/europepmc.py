"""Europe PMC adapter.

Endpoint: https://www.ebi.ac.uk/europepmc/webservices/rest/search
Returns rich metadata for biomedical literature including PMID, PMCID,
DOI, journal, abstract, in one round-trip. No auth required.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi, safe_get_json
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
            "query": clean_text(query, limit=3000),
            "format": "json",
            # Europe PMC pageSize ceiling is 1000 per call (verified
            # in their API docs). Bumped from 25 (Slice 6 step 5
            # validation found this was capping retrieval at 25
            # per source even when caller asked for 1000).
            "pageSize": str(max(1, min(limit, 1000))),
            # 'core' is required to get abstractText. 'lite' omits it which
            # would cause every result to be silently dropped.
            "resultType": "core",
        }
        data = await safe_get_json(client, EUROPEPMC_SEARCH_URL, params=params)
        if data is None:
            return []
        records = (data.get("resultList") or {}).get("result") or []
        return [hit for hit in (self._parse_record(r, query=query) for r in records) if hit]

    def _parse_record(self, record: dict[str, Any], *, query: str) -> RawHit | None:
        title = clean_text(record.get("title"), limit=300)
        # 4000-char window keeps result sections intact (was 1600; clipped 47%
        # of abstracts mid-methodology and forced real RCTs into mechanistic).
        abstract = clean_text(record.get("abstractText"), limit=4000)
        if not title or not abstract:
            return None
        doi = normalize_doi(record.get("doi"))
        pmid = clean_text(record.get("pmid"), limit=32) or None
        venue = clean_text(record.get("journalTitle"), limit=200) or None
        # pubYear is most reliable but missing on some ahead-of-print and
        # preprint records — fall back to firstPublicationDate (YYYY-MM-DD).
        year_raw = clean_text(record.get("pubYear"), limit=8)
        if not year_raw.isdigit():
            year_raw = clean_text(record.get("firstPublicationDate"), limit=10)[:4]
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
            raw={"query": clean_text(query, limit=3000), "ext_id": ext_id, "ext_src": ext_src},
        )
