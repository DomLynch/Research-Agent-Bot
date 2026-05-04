"""medRxiv adapter — clinical/health-sciences preprints.

medRxiv has a separate operational identity from bioRxiv (clinical vs
basic biology) but shares Cold Spring Harbor's infrastructure. Per
medRxiv's API documentation (api.medrxiv.org, fetched 2026-05-04), the
official medRxiv API is **detail/lookup only — no keyword search**:

    /details/medrxiv/[start_date]/[end_date]/[cursor]/[format]
    /details/medrxiv/[DOI]

For corpus discovery (which needs keyword search), we use Europe PMC's
preprint overlay — same path bioRxiv uses — and filter records down to
medRxiv-only. This keeps medRxiv as a distinct source in the registry
(provenance shows up cleanly) while reusing the working search path.

No auth required. Rate limit: gentle (Europe PMC ~10 rps).
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

# Same Europe PMC endpoint as biorxiv.py — preprint-only filter.
_PREPRINT_SEARCH_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
)


class MedRxivClient:
    """medRxiv preprint search via Europe PMC's preprint filter, with
    venue-based filter to medRxiv-only records. Returns RawHit-shaped
    records tagged with source='medrxiv' (vs 'biorxiv' for sister
    server). Both clients hit the same Europe PMC endpoint but the
    aggregator dedupes by DOI/title so duplicate cost is just one
    extra HTTP call per discovery cycle, not duplicate corpus bloat."""

    name = "medrxiv"

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
        try:
            response = await client.get(
                _PREPRINT_SEARCH_URL, params=params, timeout=20.0,
            )
        except httpx.HTTPError:
            return []
        if response.status_code != 200:
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
        venue_raw = (record.get("journalTitle") or "").lower()
        # medRxiv-only filter: must be tagged as medRxiv via venue OR
        # via Europe PMC's bookOrReportDetails (some records lack
        # journalTitle but identify medRxiv elsewhere).
        is_medrxiv = "medrxiv" in venue_raw
        if not is_medrxiv:
            # Fall through: also check bookOrReportDetails if present
            book = record.get("bookOrReportDetails") or {}
            pub = (book.get("publisher") or "").lower()
            is_medrxiv = "medrxiv" in pub
        if not is_medrxiv:
            return None
        year_raw = clean_text(record.get("pubYear"), limit=8)
        year: int | None = (
            int(year_raw) if year_raw.isdigit() else None
        )
        url = (
            f"https://doi.org/{doi}" if doi
            else "https://www.medrxiv.org/"
        )
        venue = clean_text(
            record.get("journalTitle"), limit=200,
        ) or "medRxiv preprint"
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
