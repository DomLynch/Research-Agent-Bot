"""PubMed adapter via NCBI E-utilities.

Endpoints:
  esearch.fcgi  — returns PMID list for a query (JSON)
  efetch.fcgi   — returns full article XML for a PMID list

Two calls per search. Polite pool: no API key, ≤3 req/s.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from agent.sources._base import clean_text, normalize_doi
from agent.types import RawHit

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


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
            "term": clean_text(query, limit=240),
        }
        response = await client.get(f"{EUTILS_BASE}/esearch.fcgi", params=params)
        response.raise_for_status()
        payload = response.json().get("esearchresult", {})
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
        response = await client.get(f"{EUTILS_BASE}/efetch.fcgi", params=params)
        response.raise_for_status()
        root = ET.fromstring(response.text)
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
        abstract = clean_text(abstract_text)
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
            raw={"query": clean_text(query, limit=240)},
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
