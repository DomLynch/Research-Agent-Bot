"""OpenAlex adapter.

Endpoint: https://api.openalex.org/works?search=...&per-page=N

Refactor 2026-05-04: OpenAlex changed auth as of 2026-02-13. Per
developers.openalex.org/how-to-use-the-api/rate-limits-and-authentication
(fetched 2026-05-04), API keys are now the primary auth path:
  - Sign-up: free at openalex.org/settings/api
  - Daily $1 free tier (singleton lookups unlimited; 10k list/filter
    calls; 1k search; 100 content downloads)
  - 100 req/s rate limit when a key is presented
  - The legacy `mailto=` polite-pool param is no longer documented as
    the recommended path (still tolerated for backward compat)

This adapter prefers OPENALEX_API_KEY (sent as ?api_key= query param),
falls back to CROSSREF_POLITE_EMAIL for the mailto (since both are
"please be polite to my requests" identifiers and the user's polite
email is already configured), and finally to no-auth (~10k calls/day
unkeyed).

Returns abstract as inverted index (word → [positions]); we reconstitute.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi, safe_get_json
from agent.types import RawHit

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
SELECT_FIELDS = (
    "id,doi,title,abstract_inverted_index,primary_location,publication_year"
)


class OpenAlexClient:
    name = "openalex"

    def _auth_params(self) -> dict[str, str]:
        """Pick the strongest available auth signal:
        1. OPENALEX_API_KEY (2026 preferred — query param api_key=...)
        2. CROSSREF_POLITE_EMAIL (legacy polite-pool mailto)
        3. nothing (anonymous tier)
        """
        api_key = os.environ.get("OPENALEX_API_KEY")
        if api_key:
            return {"api_key": api_key}
        # Reuse the polite email user already set (same intent).
        email = os.environ.get("CROSSREF_POLITE_EMAIL")
        if email:
            return {"mailto": email}
        return {}

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "search": clean_text(query, limit=3000),
            "per-page": str(max(1, min(limit, 200))),
            "select": SELECT_FIELDS,
        }
        params.update(self._auth_params())
        # 429 (daily-budget exhausted), 401/403 (bad key), 5xx → fail soft;
        # aggregator continues with the other 14 sources.
        data = await safe_get_json(
            client, OPENALEX_WORKS_URL, params=params,
        )
        if data is None:
            return []
        works = data.get("results", []) or []
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
            raw={"query": clean_text(query, limit=3000), "openalex_id": work.get("id")},
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
