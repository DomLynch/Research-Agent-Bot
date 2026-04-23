from __future__ import annotations

import html
import re
import xml.etree.ElementTree as et
from typing import Any

import httpx


PUBMED_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _clean_text(value: Any, *, limit: int = 1600) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()[:limit]


def _abstract_text(article: et.Element) -> str:
    parts: list[str] = []
    for node in article.findall(".//Abstract/AbstractText"):
        label = _clean_text(node.attrib.get("Label"), limit=40)
        text = _clean_text("".join(node.itertext()), limit=4000)
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)
    return _clean_text(" ".join(parts), limit=5000)


def _infer_evidence_type(title: str, abstract: str) -> str:
    haystack = f"{title} {abstract}".lower()
    review_tokens = ("systematic review", "meta-analysis", "umbrella review", "narrative review", "review")
    return "review" if any(token in haystack for token in review_tokens) else "primary"


def _year(article: et.Element) -> int | None:
    for xpath in (".//PubDate/Year", ".//ArticleDate/Year", ".//DateCompleted/Year", ".//DateRevised/Year"):
        text = _clean_text("".join(article.findtext(xpath, default="")))
        if text.isdigit():
            return int(text)
    return None


class PubMedClient:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.timeout_sec = timeout_sec
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers={
                "User-Agent": "researka-reference-agent/0.1 (+https://researka.org)",
                "Accept": "application/json, application/xml, text/xml;q=0.9, */*;q=0.8",
            },
        )

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        params = {"db": "pubmed", "retmode": "json", "retmax": max(limit * 4, limit), "sort": "relevance", "term": query}
        search_response = self.client.get(f"{PUBMED_EUTILS_BASE}/esearch.fcgi", params=params)
        search_response.raise_for_status()
        ids = [str(item) for item in search_response.json().get("esearchresult", {}).get("idlist", []) if str(item).strip()]
        if not ids:
            return []
        fetch_response = self.client.get(f"{PUBMED_EUTILS_BASE}/efetch.fcgi", params={"db": "pubmed", "retmode": "xml", "id": ",".join(ids)})
        fetch_response.raise_for_status()
        root = et.fromstring(fetch_response.text)
        entries: list[dict[str, Any]] = []
        for article in root.findall(".//PubmedArticle"):
            pmid = _clean_text(article.findtext(".//PMID"))
            title = _clean_text("".join(article.find(".//ArticleTitle").itertext()) if article.find(".//ArticleTitle") is not None else "")
            abstract = _abstract_text(article)
            if not pmid or not title or not abstract:
                continue
            doi = None
            for node in article.findall(".//ArticleId"):
                if str(node.attrib.get("IdType") or "").lower() == "doi":
                    doi = _clean_text(node.text, limit=256) or None
                    break
            journal = _clean_text(article.findtext(".//Journal/JournalTitle") or article.findtext(".//ISOAbbreviation"), limit=200) or None
            authors = []
            for author in article.findall(".//AuthorList/Author"):
                last = _clean_text(author.findtext("LastName"), limit=80)
                if last:
                    authors.append(last)
            entries.append(
                {
                    "id": pmid,
                    "title": title[:300],
                    "excerpt": abstract,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "doi": doi,
                    "year": _year(article),
                    "query": _clean_text(query, limit=240),
                    "source_type": "pubmed",
                    "evidence_type": _infer_evidence_type(title, abstract),
                    "journal": journal,
                    "authors": authors,
                }
            )
            if len(entries) >= limit:
                break
        return entries
