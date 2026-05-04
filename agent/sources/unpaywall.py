"""Unpaywall adapter — DOI-only OA-version lookup.

Endpoint: https://api.unpaywall.org/v2/<doi>?email=<email>
Email is REQUIRED (no API key — but they want a contact email).
Set env: UNPAYWALL_EMAIL.

Unpaywall doesn't have a search endpoint — it's a lookup service.
The aggregator uses it to upgrade closed-DOI hits from other
sources to OA-PDF URLs when available. So this client's `search()`
method takes a list of DOIs (passed as comma-separated query) and
resolves each one. Sub-optimal but matches the SourceClient
contract.

For corpus-discovery use: pass DOIs from prior search results.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit


class UnpaywallClient:
    name = "unpaywall"

    def _email(self) -> str:
        return (
            os.environ.get("UNPAYWALL_EMAIL")
            or "researka@example.com"
        )

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        # `query` here = comma-separated DOIs (not free-text).
        # Caller is the aggregator after primary search.
        dois = [
            d.strip() for d in query.split(",") if d.strip()
        ][:limit]
        out: list[RawHit] = []
        email = self._email()
        for doi in dois:
            doi_norm = normalize_doi(doi)
            if not doi_norm:
                continue
            url = (
                f"https://api.unpaywall.org/v2/{doi_norm}"
                f"?email={email}"
            )
            try:
                r = await client.get(url, timeout=10.0)
                if r.status_code != 200:
                    continue
                data = r.json()
            except (httpx.HTTPError, ValueError):
                continue
            hit = self._parse(data, doi=doi_norm)
            if hit:
                out.append(hit)
        return out

    def _parse(
        self, record: dict[str, Any], *, doi: str,
    ) -> RawHit | None:
        title = clean_text(record.get("title"), limit=300)
        if not title:
            return None
        # Unpaywall has no abstract — use a placeholder so RawHit
        # contract holds. Real abstract comes from upstream sources.
        abstract = clean_text(
            f"OA lookup for {doi}; no abstract field — see "
            "primary source.",
            limit=4000,
        )
        venue = clean_text(
            record.get("journal_name"), limit=200,
        ) or None
        year = record.get("year")
        if year is not None:
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None
        # Best OA URL — prefer best_oa_location.url_for_pdf
        oa_loc = record.get("best_oa_location") or {}
        url = (
            oa_loc.get("url_for_pdf") or oa_loc.get("url")
            or f"https://doi.org/{doi}"
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
