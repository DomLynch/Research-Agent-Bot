"""Researka tier-2 facts adapter (POST /api/v1/papers/topic).

Wraps the topic-papers endpoint of the internal researka-database API.
The full surface (13 endpoints) is documented at `/openapi.json` —
this adapter intentionally wires only the most synthesis-shaped one:
`POST /api/v1/papers/topic`, which returns `PaperHit` objects that
map cleanly to `RawHit` (title / abstract / year / doi / pmid /
journal / pmcid).

Auth: `X-Researka-Token` header from `RESEARKA_DATABASE_TOKEN` env var.
Fail-soft: returns `[]` when the token is absent, the call fails, or
the response is malformed (per existing adapter convention in
`_base.safe_get_json`).

Universal: the adapter extracts the first token of the query as the
researka `topic` slug. No per-topic logic, no domain assumptions —
works for biomedical, climate, materials, economics topics identically.
"""
from __future__ import annotations

import os
import re

import httpx

from agent.sources._base import USER_AGENT, clean_text, normalize_doi
from agent.types import RawHit

RESEARKA_BASE = "https://database.researka.org"
TOPIC_PAPERS_PATH = "/api/v1/papers/topic"
_TIMEOUT = 20.0


def _researka_token() -> str | None:
    """Return `RESEARKA_DATABASE_TOKEN` from env, stripped. None when
    unset → adapter fail-softs to zero hits."""
    tok = os.environ.get("RESEARKA_DATABASE_TOKEN")
    return tok.strip() if tok and tok.strip() else None


_FIRST_WORD_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_\-]+)")


def _topic_from_query(query: str) -> str:
    """Extract a topic slug from a free-form aggregator query.

    The aggregator passes topic-anchored queries like
    `"berberine AND randomized trial AND metabolic syndrome"`. Researka
    expects a single topic name in its `topic` field. We take the first
    alphabetic token. Universal — no per-topic mapping table.
    """
    m = _FIRST_WORD_RE.search(query)
    return m.group(1).lower() if m else clean_text(query, limit=64).lower()


def _build_url(doi: str | None, pmid: str | None, pmcid: str | None) -> str:
    """RawHit.url construction with deterministic fallbacks: prefer DOI,
    then PubMed, then PMC, else empty. Matches the EuropePMC adapter."""
    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if pmcid:
        pid = pmcid.lstrip("PMC").lstrip("pmc")
        if pid:
            return f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pid}/"
    return ""


def _hit_from_paper(record: dict, query: str) -> RawHit | None:
    """Normalize a researka PaperHit dict → RawHit. Returns None when the
    record lacks both a title and any identifier (defensive — bad data
    shouldn't pollute the aggregator)."""
    title = clean_text(record.get("title"), limit=400)
    if not title:
        return None
    abstract = clean_text(record.get("abstract"), limit=4000)
    year_raw = record.get("year")
    year: int | None = int(year_raw) if isinstance(year_raw, int) else None
    doi = normalize_doi(record.get("doi"))
    pmid_raw = record.get("pmid")
    pmid = str(pmid_raw).strip() if pmid_raw not in (None, "") else None
    pmcid_raw = record.get("pmcid")
    pmcid = str(pmcid_raw).strip() if pmcid_raw not in (None, "") else None
    venue = clean_text(record.get("journal"), limit=200)
    return RawHit(
        source="researka",
        title=title,
        abstract=abstract,
        year=year,
        url=_build_url(doi, pmid, pmcid),
        doi=doi,
        pmid=pmid,
        venue=venue or None,
        raw={
            "query": clean_text(query, limit=300),
            "pmcid": pmcid,
            "cited_by_count": record.get("cited_by_count"),
        },
    )


class ResearkaClient:
    """Tier-2 facts adapter for the internal researka-database API."""

    name = "researka"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        token = _researka_token()
        if not token:
            return []  # fail-soft when unauthenticated
        topic = _topic_from_query(query)
        if not topic:
            return []
        body = {
            "topic": topic,
            "limit": max(1, min(int(limit), 50)),
            "include_facts": False,
        }
        try:
            resp = await client.post(
                RESEARKA_BASE + TOPIC_PAPERS_PATH,
                json=body,
                headers={
                    "X-Researka-Token": token,
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        if not isinstance(data, list):
            return []
        hits: list[RawHit] = []
        for record in data:
            if not isinstance(record, dict):
                continue
            hit = _hit_from_paper(record, query)
            if hit is not None:
                hits.append(hit)
        return hits[:limit]
