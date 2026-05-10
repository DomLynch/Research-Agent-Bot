"""Private Researka Database source adapter."""
from __future__ import annotations

import os
import re
from typing import Any

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

DEFAULT_BASE_URL = "https://database.researka.org"
_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")
_RERANK_GENERIC_TERMS = frozenset({
    "adult",
    "adults",
    "age",
    "aged",
    "aging",
    "biology",
    "cell",
    "cells",
    "clinical",
    "disease",
    "health",
    "human",
    "humans",
    "intervention",
    "life",
    "lifespan",
    "longevity",
    "mice",
    "mortality",
    "mouse",
    "older",
    "study",
    "trial",
})


class ResearkaDatabaseClient:
    name = "researka_database"

    def _base_url(self) -> str:
        return os.environ.get("RESEARKA_DATABASE_URL", DEFAULT_BASE_URL).rstrip("/")

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        token = os.environ.get("RESEARKA_DATABASE_TOKEN", "").strip()
        if not token:
            return []
        k = max(1, min(limit, 50))
        lane_k = min(max(k * 3, 20), 50)
        payload = {
            "query": clean_text(query, limit=3000),
            "established_k": lane_k,
            "discovery_k": min(lane_k, 25),
            "semantic_k": lane_k,
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
        terms = _rerank_terms(query)
        by_lane: dict[str, list[RawHit]] = {}
        for lane in ("established", "discovery", "semantic"):
            rows = body.get(lane, [])
            if not isinstance(rows, list):
                continue
            by_lane[lane] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                hit = self._parse(row, lane=lane, query=query)
                if hit is None:
                    continue
                by_lane[lane].append(hit)
            by_lane[lane].sort(key=lambda hit: _lexical_score(hit, terms), reverse=True)

        hits: list[RawHit] = []
        seen: set[str] = set()
        max_lane_len = max((len(rows) for rows in by_lane.values()), default=0)
        for idx in range(max_lane_len):
            for lane in ("established", "discovery", "semantic"):
                rows = by_lane.get(lane, [])
                if idx >= len(rows):
                    continue
                hit = rows[idx]
                key = _dedupe_key(hit)
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
            url=(
                f"https://doi.org/{doi}" if doi else
                f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else
                self._base_url()
            ),
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


def _dedupe_key(hit: RawHit) -> str:
    if hit.doi:
        return f"doi:{hit.doi}"
    if hit.pmid:
        return f"pmid:{hit.pmid}"
    return f"title:{hit.title.casefold()}:{hit.year or ''}"


def _rerank_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in _TERM_RE.finditer(query):
        term = match.group(0).casefold()
        if term in seen:
            continue
        seen.add(term)
        if term not in _RERANK_GENERIC_TERMS:
            terms.append(term)
    if terms:
        return tuple(terms[:8])
    return tuple(list(seen)[:8])


def _lexical_score(hit: RawHit, terms: tuple[str, ...]) -> int:
    if not terms:
        return 0
    title = hit.title.casefold()
    abstract = hit.abstract.casefold()
    return sum(2 for term in terms if term in title) + sum(
        1 for term in terms if term in abstract
    )
