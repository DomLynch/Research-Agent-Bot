"""OpenAIRE adapter — EU open-science aggregator.

Endpoint: https://api.openaire.eu/search/publications
Free, no auth (rate-limited to ~5 rps for unauthenticated).
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi, safe_get_json
from agent.types import RawHit

_OPENAIRE_URL = "https://api.openaire.eu/search/publications"
_NS = {
    "oaf": "http://namespace.openaire.eu/oaf",
}


class OpenAireClient:
    name = "openaire"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "keywords": clean_text(query, limit=240),
            "size": str(max(1, min(limit, 25))),
            "format": "json",
        }
        data = await safe_get_json(client, _OPENAIRE_URL, params=params)
        if data is None:
            return []
        # OpenAIRE response structure:
        # response.results.result[].metadata.entity.result
        results = (
            data.get("response", {})
            .get("results", {})
            .get("result", [])
        )
        if isinstance(results, dict):
            results = [results]
        return [
            hit for hit in (
                self._parse(r, query=query) for r in results
            )
            if hit
        ]

    def _parse(
        self, record: dict[str, Any], *, query: str,
    ) -> RawHit | None:
        try:
            entity = (
                record.get("metadata", {})
                .get("oaf:entity", {})
                .get("oaf:result", {})
            )
            if not entity:
                return None
            # Title may be string or list
            title_field = entity.get("title", "")
            title = clean_text(
                title_field if isinstance(title_field, str)
                else (title_field.get("$") or ""),
                limit=300,
            )
            desc_field = entity.get("description", "")
            abstract = clean_text(
                desc_field if isinstance(desc_field, str)
                else (desc_field.get("$") or ""),
                limit=4000,
            )
            if not title or not abstract:
                return None
            # PIDs
            pid_field = entity.get("pid", [])
            if isinstance(pid_field, dict):
                pid_field = [pid_field]
            doi = None
            for p in pid_field:
                if isinstance(p, dict) and (
                    p.get("@classid") == "doi"
                    or p.get("@scheme") == "doi"
                ):
                    doi = normalize_doi(
                        p.get("$") or p.get("@value")
                    )
                    if doi:
                        break
            # Year
            date_field = entity.get("dateofacceptance", "")
            year = None
            date_str = (
                date_field if isinstance(date_field, str)
                else (date_field.get("$") or "")
            )
            if date_str and date_str[:4].isdigit():
                year = int(date_str[:4])
            url = (
                f"https://doi.org/{doi}" if doi
                else "https://www.openaire.eu/"
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
                venue=None,
                raw=record,
            )
        except (KeyError, AttributeError, TypeError):
            return None
