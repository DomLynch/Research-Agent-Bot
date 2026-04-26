from __future__ import annotations

import html
import re
from typing import Any

import httpx


EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_RXIV_PUBLISHERS = {"biorxiv": "biorxiv", "medrxiv": "medrxiv"}


def _clean_text(value: Any, *, limit: int = 1600) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()[:limit]


def _infer_evidence_type(title: str, abstract: str) -> str:
    haystack = f"{title} {abstract}".lower()
    review_tokens = ("systematic review", "meta-analysis", "umbrella review", "narrative review", "review")
    return "review" if any(token in haystack for token in review_tokens) else "primary"


def _source_type(result: dict[str, Any]) -> str | None:
    details = result.get("bookOrReportDetails") or {}
    publisher = _clean_text(details.get("publisher"), limit=80).lower()
    return _RXIV_PUBLISHERS.get(publisher)


def _authors(result: dict[str, Any]) -> list[str]:
    out = []
    author_list = (result.get("authorList") or {}).get("author") or []
    for author in author_list:
        if isinstance(author, dict):
            last = _clean_text(author.get("lastName"), limit=80)
            if last:
                out.append(last)
    return out


def _url(result: dict[str, Any]) -> str:
    urls = (result.get("fullTextUrlList") or {}).get("fullTextUrl") or []
    for item in urls:
        if isinstance(item, dict):
            url = _clean_text(item.get("url"), limit=300)
            if url:
                return url
    item_id = _clean_text(result.get("id"), limit=80)
    return f"https://europepmc.org/article/PPR/{item_id}" if item_id else "https://europepmc.org/"


class RxivClient:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(timeout=timeout_sec, transport=transport, headers={"User-Agent": "researka-reference-agent/0.1"})

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        response = self.client.get(
            EUROPEPMC_SEARCH_URL,
            params={
                "query": f"{_clean_text(query, limit=240)} AND SRC:PPR",
                "format": "json",
                "pageSize": max(1, min(limit * 5, 50)),
                "resultType": "core",
            },
        )
        response.raise_for_status()
        entries: list[dict[str, Any]] = []
        for result in response.json().get("resultList", {}).get("result", []):
            source_type = _source_type(result)
            title = _clean_text(result.get("title"), limit=300)
            abstract = _clean_text(result.get("abstractText"))
            if not source_type or not title or not abstract:
                continue
            year = _clean_text(result.get("pubYear"), limit=8)
            entries.append(
                {
                    "id": _clean_text(result.get("id"), limit=80),
                    "title": title,
                    "excerpt": abstract,
                    "url": _url(result),
                    "doi": _clean_text(result.get("doi"), limit=256) or None,
                    "year": int(year) if year.isdigit() else None,
                    "query": _clean_text(query, limit=240),
                    "source_type": source_type,
                    "evidence_type": _infer_evidence_type(title, abstract),
                    "journal": source_type,
                    "authors": _authors(result),
                }
            )
            if len(entries) >= limit:
                break
        return entries
