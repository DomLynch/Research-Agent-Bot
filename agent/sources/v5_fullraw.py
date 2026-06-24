"""V5 fullraw corpus adapter.

Routes v3 discovery into the 5TB-backed fullraw search service without making
that service a hard dependency: no URL/token means disabled, transport/coverage
failures mean zero hits, and the rest of the source fan-out continues.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.sources._base import USER_AGENT, clean_text, normalize_doi
from agent.types import RawHit

DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_TIMEOUT_SECONDS = 300.0
YEAR_MIN = 1900
YEAR_MAX = 2100


def _fullraw_url() -> str:
    return os.environ.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "").strip()


def _fullraw_token() -> str:
    return os.environ.get("V5_MEMO_FULL_RAW_CORPUS_TOKEN", "").strip()


def _timeout_seconds() -> float:
    raw = os.environ.get("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "").strip()
    try:
        requested = max(1.0, float(raw)) if raw else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        requested = DEFAULT_TIMEOUT_SECONDS
    return min(requested, MAX_TIMEOUT_SECONDS)


def _build_url(doi: str | None, pmid: str | None, url: object) -> str:
    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return clean_text(url, limit=500)


def _year(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _shard_receipt(data: Any) -> dict[str, object]:
    meta = data.get("meta") if isinstance(data, dict) else None
    receipt = meta.get("shard_receipt") if isinstance(meta, dict) else None
    return dict(receipt) if isinstance(receipt, dict) else {}


def _parse_hit(item: dict[str, Any], query: str, receipt: dict[str, object]) -> RawHit | None:
    title = clean_text(item.get("title"), limit=400)
    if not title:
        return None
    doi = normalize_doi(item.get("doi"))
    pmid_raw = item.get("pmid")
    pmid = str(pmid_raw).strip() if pmid_raw not in (None, "") else None
    abstract = clean_text(item.get("abstract"), limit=5000)
    source = clean_text(item.get("source"), limit=80) or "fullraw"
    return RawHit(
        source="v5_fullraw",
        title=title,
        abstract=abstract,
        year=_year(item.get("year")),
        url=_build_url(doi, pmid, item.get("url")),
        doi=doi,
        pmid=pmid,
        venue=clean_text(item.get("journal"), limit=200) or None,
        raw={
            "query": clean_text(query, limit=300),
            "lane": "v5_fullraw",
            "fullraw_source": source,
            "openalex_id": item.get("openalex_id"),
            "semantic_scholar_id": item.get("semantic_scholar_id"),
            "cited_by_count": item.get("cited_by_count"),
            "shard_receipt": receipt,
        },
    )


class V5FullRawClient:
    name = "v5_fullraw"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        url = _fullraw_url()
        token = _fullraw_token()
        if not url or not token:
            return []
        payload = {
            "query": clean_text(query, limit=1024),
            "limit": max(1, min(limit, 50)),
            "top_k": max(1, min(limit, 50)),
            "year_min": YEAR_MIN,
            "year_max": YEAR_MAX,
            "corpus": "full_raw_450m_plus",
            "search_pass": "focused",
            "rank_mode": "relevance",
            "timeout_seconds": _timeout_seconds(),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=_timeout_seconds())
        except httpx.HTTPError:
            return []
        if response.status_code != 200:
            return []
        try:
            data = response.json()
        except ValueError:
            return []
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return []
        receipt = _shard_receipt(data)
        return [
            hit
            for item in results
            if isinstance(item, dict)
            for hit in [_parse_hit(item, query, receipt)]
            if hit
        ]
