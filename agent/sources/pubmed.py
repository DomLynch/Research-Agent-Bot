"""PubMed adapter via NCBI E-utilities.

Endpoints:
  esearch.fcgi  — returns PMID list for a query (JSON)
  efetch.fcgi   — returns full article XML for a PMID list

Two calls per search. Polite pool: no API key, ≤3 req/s.
With NCBI_API_KEY env var: 10 req/s (free key, register at
https://account.ncbi.nlm.nih.gov/settings/).
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import httpx

from agent.sources._base import (
    clean_text,
    normalize_doi,
    safe_get_json,
    safe_get_text,
)
from agent.types import RawHit

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _ncbi_key() -> str | None:
    """Return NCBI API key from env. None = polite-pool (3 req/s).
    Set: NCBI_API_KEY=<your-key>.
    Register at https://account.ncbi.nlm.nih.gov/settings/."""
    key = os.environ.get("NCBI_API_KEY")
    return key.strip() if key else None


class PubMedClient:
    name = "pubmed"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        ids = await self._esearch(client, query, limit=limit)
        if not ids:
            return []
        return await self._efetch(client, ids, query=query, limit=limit)

    async def _esearch(self, client: httpx.AsyncClient, query: str, *, limit: int) -> list[str]:
        params = {
            "db": "pubmed",
            "retmode": "json",
            # Earlier code over-fetched 3x as a "buffer" that was then discarded
            # in _efetch, wasting bandwidth and quota for no benefit.
            "retmax": str(max(1, limit)),
            "sort": "relevance",
            "term": clean_text(query, limit=3000),
        }
        # Add NCBI API key if available (3 req/s → 10 req/s)
        key = _ncbi_key()
        if key:
            params["api_key"] = key
        data = await safe_get_json(
            client, f"{EUTILS_BASE}/esearch.fcgi", params=params,
        )
        if data is None:
            return []
        payload = data.get("esearchresult", {})
        return [str(item) for item in payload.get("idlist", []) if str(item).strip()]

    async def _efetch(
        self,
        client: httpx.AsyncClient,
        ids: list[str],
        *,
        query: str,
        limit: int,
    ) -> list[RawHit]:
        params = {"db": "pubmed", "retmode": "xml", "id": ",".join(ids)}
        # NCBI key bumps rate limit from 3/s → 10/s
        key = _ncbi_key()
        if key:
            params["api_key"] = key
        text = await safe_get_text(
            client, f"{EUTILS_BASE}/efetch.fcgi", params=params,
        )
        if text is None:
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        hits: list[RawHit] = []
        for article in root.findall(".//PubmedArticle"):
            hit = self._parse_article(article, query=query)
            if hit is None:
                continue
            hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    def _parse_article(self, article: ET.Element, *, query: str) -> RawHit | None:
        pmid = clean_text(article.findtext(".//PMID"))
        if not pmid:
            return None
        title_node = article.find(".//ArticleTitle")
        title = clean_text("".join(title_node.itertext()) if title_node is not None else "", limit=300)
        abstract_text = " ".join(
            "".join(node.itertext())
            for node in article.findall(".//Abstract/AbstractText")
        )
        # 4000 char window keeps the results section intact for classification.
        # Earlier 1600 cap clipped 47% of abstracts mid-methodology, hiding
        # outcome markers and forcing real RCTs into the mechanistic default.
        abstract = clean_text(abstract_text, limit=4000)
        if not title or not abstract:
            return None
        doi: str | None = None
        for node in article.findall(".//ArticleId"):
            if str(node.attrib.get("IdType") or "").lower() == "doi":
                doi = normalize_doi(node.text)
                break
        venue = clean_text(
            article.findtext(".//Journal/JournalTitle")
            or article.findtext(".//Journal/ISOAbbreviation"),
            limit=200,
        ) or None
        year = self._extract_year(article)
        return RawHit(
            source="pubmed",
            title=title,
            abstract=abstract,
            year=year,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            doi=doi,
            pmid=pmid,
            venue=venue,
            raw={"query": clean_text(query, limit=3000)},
        )

    @staticmethod
    def _extract_year(article: ET.Element) -> int | None:
        for xpath in (
            ".//PubDate/Year",
            ".//ArticleDate/Year",
            ".//DateCompleted/Year",
            ".//DateRevised/Year",
        ):
            text = clean_text(article.findtext(xpath, default=""))
            if text.isdigit():
                return int(text)
        return None
