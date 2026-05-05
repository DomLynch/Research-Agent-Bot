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
            "keywords": clean_text(query, limit=3000),
            "size": str(max(1, min(limit, 100))),
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
            # Title may be: str, dict {"$": "..."}, or LIST of dicts
            # (real shape — multiple title types: main title,
            # alternative title, sub-title, etc., each as a dict).
            # Pre-fix the parser only handled str/dict; lists silently
            # raised AttributeError and the broad except swallowed
            # every OpenAIRE record. This fix handles all three.
            title = clean_text(
                _extract_string_field(entity.get("title", ""),
                                      prefer_classid="main title"),
                limit=300,
            )
            abstract = clean_text(
                _extract_string_field(entity.get("description", "")),
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
            # Year — same str/dict/list polymorphism as title
            date_str = _extract_string_field(
                entity.get("dateofacceptance", ""),
            )
            year = None
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


def _extract_string_field(field: Any, *, prefer_classid: str = "") -> str:
    """OpenAIRE wraps primitive values in {"$": "..."} dicts and
    sometimes returns a LIST of such dicts (e.g. multiple titles per
    record, classified by @classid="main title" / "alternative title").

    Returns the best-string for any of: str, dict {"$": ...}, or
    list of either. When `prefer_classid` is set and the input is a
    list, picks the entry whose @classid matches first."""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return str(field.get("$") or "")
    if isinstance(field, list):
        if prefer_classid:
            for item in field:
                if (
                    isinstance(item, dict)
                    and item.get("@classid") == prefer_classid
                ):
                    return str(item.get("$") or "")
        # Fall back to first usable string
        for item in field:
            if isinstance(item, str) and item:
                return item
            if isinstance(item, dict):
                v = item.get("$")
                if v:
                    return str(v)
    return ""
