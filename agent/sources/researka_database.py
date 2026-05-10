"""Researka Database adapter.

Private hot-index source for the synthesis bot. It calls
database.researka.org's three-lane `/api/v1/search` endpoint and converts
Established / Discovery / Semantic hits into the standard RawHit contract.

Opt-in via RESEARKA_DATABASE_TOKEN. Missing token returns [] without making a
network call so local tests and public runs do not fail on private infra.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

DEFAULT_BASE_URL = "https://database.researka.org"


class ResearkaDatabaseClient:
    name = "researka_database"

    def _base_url(self) -> str:
        return os.environ.get("RESEARKA_DATABASE_URL", DEFAULT_BASE_URL).rstrip("/")

    def _token(self) -> str:
        return os.environ.get("RESEARKA_DATABASE_TOKEN", "").strip()

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        token = self._token()
        if not token:
            return []
        k = max(1, min(limit, 50))
        payload = {
            "query": clean_text(query, limit=3000),
            "established_k": k,
            "discovery_k": max(0, min(k // 2, 25)),
            "semantic_k": k,
        }
        try:
            response = await client.post(
                f"{self._base_url()}/api/v1/search",
                json=payload,
                headers={"X-Researka-Token": token},
                timeout=20.0,
            )
        except httpx.HTTPError:
            return []
        if response.status_code in (401, 403, 429) or response.status_code >= 500:
            return []
        if response.status_code != 200:
            return []
        try:
            body = response.json()
        except ValueError:
            return []
        if not isinstance(body, dict):
            return []
        hits: list[RawHit] = []
        seen: set[tuple[str | None, str | None, str]] = set()
        for lane in ("established", "discovery", "semantic"):
            rows = body.get(lane, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                hit = self._parse(row, lane=lane, query=query)
                if hit is None:
                    continue
                key = (hit.doi, hit.pmid, hit.title.lower()[:120])
                if key in seen:
                    continue
                seen.add(key)
                hits.append(hit)
                if len(hits) >= k:
                    return hits
        return hits

    def _parse(self, row: dict[str, Any], *, lane: str, query: str) -> RawHit | None:
        title = clean_text(row.get("title"), limit=300)
        abstract = clean_text(row.get("abstract"), limit=4000)
        if not title or not abstract:
            return None
        doi = normalize_doi(row.get("doi"))
        pmid = clean_text(row.get("pmid"), limit=32) or None
        year = _int_or_none(row.get("publication_year") or row.get("year"))
        venue = clean_text(row.get("journal_name") or row.get("venue"), limit=200) or None
        return RawHit(
            source=self.name,
            title=title,
            abstract=abstract,
            year=year,
            url=_best_url(row, doi=doi, pmid=pmid, base_url=self._base_url()),
            doi=doi,
            pmid=pmid,
            nct=None,
            venue=venue,
            raw={
                "lane": lane,
                "query": clean_text(query, limit=3000),
                "researka_id": row.get("id"),
                "quality_score": row.get("quality_score"),
                "semantic_score": row.get("semantic_score"),
                "cited_by_count": row.get("cited_by_count"),
            },
        )


def _int_or_none(value: object) -> int | None:
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _best_url(
    row: dict[str, Any],
    *,
    doi: str | None,
    pmid: str | None,
    base_url: str,
) -> str:
    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    paper_id = clean_text(row.get("id"), limit=256)
    if paper_id:
        return f"{base_url}/api/v1/papers/{paper_id}"
    return base_url
