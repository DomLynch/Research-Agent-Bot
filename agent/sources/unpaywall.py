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

import asyncio
import os
import re
from typing import Any
from urllib.parse import urlencode

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit


class UnpaywallClient:
    name = "unpaywall"
    max_concurrent_lookups = 8

    def _email(self) -> str:
        email = os.environ.get("UNPAYWALL_EMAIL", "").strip()
        if (
            not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
            or email.lower().endswith("@example.com")
        ):
            raise ValueError("UNPAYWALL_EMAIL must be a valid contact email")
        return email

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
        email = self._email()
        semaphore = asyncio.Semaphore(self.max_concurrent_lookups)

        async def resolve(doi: str) -> RawHit | None:
            doi_norm = normalize_doi(doi)
            if not doi_norm:
                return None
            url = (
                f"https://api.unpaywall.org/v2/{doi_norm}"
                f"?{urlencode({'email': email})}"
            )
            async with semaphore:
                try:
                    response = await client.get(url, timeout=10.0)
                    if response.status_code != 200:
                        return None
                    data = response.json()
                except (httpx.HTTPError, ValueError):
                    return None
            return self._parse(data, doi=doi_norm)

        resolved = await asyncio.gather(*(resolve(doi) for doi in dois))
        return [hit for hit in resolved if hit is not None]

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
        # Enrichment is useful only when Unpaywall supplies an OA location.
        oa_loc = record.get("best_oa_location")
        if not record.get("is_oa") or not isinstance(oa_loc, dict):
            return None
        url = oa_loc.get("url_for_pdf") or oa_loc.get("url")
        if not url:
            return None
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
