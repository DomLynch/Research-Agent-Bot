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
DEFAULT_MIN_SHARDS_SEARCHED = 1525
DEFAULT_MIN_SOURCES_SEARCHED = 5


def _fullraw_url() -> str:
    return os.environ.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "").strip()


def _fullraw_token() -> str:
    return os.environ.get("V5_MEMO_FULL_RAW_CORPUS_TOKEN", "").strip()


def _timeout_seconds() -> float:
    raw = (
        os.environ.get("V5_MEMO_FULL_RAW_QUERY_TIMEOUT", "").strip()
        or os.environ.get("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "").strip()
    )
    try:
        requested = max(1.0, float(raw)) if raw else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        requested = DEFAULT_TIMEOUT_SECONDS
    return min(requested, MAX_TIMEOUT_SECONDS)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _truthy_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _build_url(doi: str | None, pmid: str | None, url: object) -> str:
    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return clean_text(url, limit=500)


def _year(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _shard_receipt(data: Any) -> dict[str, object]:
    if not isinstance(data, dict):
        return {}
    for key in ("receipt", "shard_receipt"):
        receipt = data.get(key)
        if isinstance(receipt, dict):
            return dict(receipt)
    meta = data.get("meta") if isinstance(data, dict) else None
    receipt = meta.get("shard_receipt") if isinstance(meta, dict) else None
    return dict(receipt) if isinstance(receipt, dict) else {}


def _source_count(value: object) -> int:
    if isinstance(value, dict):
        return len([key for key in value if str(key).strip()])
    if isinstance(value, list | tuple | set):
        return len([item for item in value if str(item).strip()])
    if isinstance(value, str):
        return len([part for part in value.split(",") if part.strip()])
    return 0


def _receipt_complete(receipt: dict[str, object]) -> bool:
    if not _truthy_env("V5_MEMO_FULL_RAW_REQUIRE_COMPLETE_SEARCH", True):
        return True
    shards = _int_value(receipt.get("shards_searched"))
    min_shards = _int_env("V5_MEMO_FULL_RAW_MIN_SHARDS_SEARCHED", DEFAULT_MIN_SHARDS_SEARCHED)
    min_sources = _int_env("V5_MEMO_FULL_RAW_MIN_SOURCES_SEARCHED", DEFAULT_MIN_SOURCES_SEARCHED)
    partial = receipt.get("partial_shard_search")
    if partial is None:
        partial = receipt.get("partial")
    failed = _int_value(receipt.get("sweep_failed_shards") or receipt.get("failed_shards"))
    return (
        shards >= min_shards
        and partial is not True
        and failed == 0
        and _source_count(receipt.get("sources_searched")) >= min_sources
    )


def _int_value(value: object) -> int:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            return int(value)
    except (TypeError, ValueError):
        return 0
    return 0


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
            "rank_mode": "relevance",
            "cache_only": True,
            "queue_if_missing": True,
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
        if not _receipt_complete(receipt):
            return []
        return [
            hit
            for item in results
            if isinstance(item, dict)
            for hit in [_parse_hit(item, query, receipt)]
            if hit
        ]
