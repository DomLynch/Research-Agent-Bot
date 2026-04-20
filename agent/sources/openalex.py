from __future__ import annotations

from typing import Any

import httpx


OPENALEX_WORKS_URL = "https://api.openalex.org/works"


def _clean_text(value: Any, *, limit: int = 1600) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _openalex_abstract(inverted_index: Any) -> str:
    if not isinstance(inverted_index, dict):
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            try:
                positions[int(index)] = str(word)
            except (TypeError, ValueError):
                continue
    return _clean_text(" ".join(positions[index] for index in sorted(positions)))


def _infer_evidence_type(title: str, abstract: str) -> str:
    haystack = f"{title} {abstract}".lower()
    review_tokens = ("systematic review", "meta-analysis", "umbrella review", "review")
    return "review" if any(token in haystack for token in review_tokens) else "primary"


class OpenAlexClient:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(timeout=timeout_sec, transport=transport, headers={"User-Agent": "researka-reference-agent/0.1"})

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        response = self.client.get(
            OPENALEX_WORKS_URL,
            params={
                "search": _clean_text(query, limit=240),
                "per-page": max(1, min(limit, 20)),
                "select": "id,doi,title,abstract_inverted_index,primary_location,publication_year",
            },
        )
        response.raise_for_status()
        entries: list[dict[str, Any]] = []
        for work in response.json().get("results", []):
            title = _clean_text(work.get("title"), limit=300)
            abstract = _openalex_abstract(work.get("abstract_inverted_index"))
            if not title or not abstract:
                continue
            location = work.get("primary_location") or {}
            doi = _clean_text(work.get("doi"), limit=256).removeprefix("https://doi.org/") or None
            entries.append(
                {
                    "id": work.get("id"),
                    "title": title,
                    "excerpt": abstract,
                    "url": location.get("landing_page_url") or work.get("id"),
                    "doi": doi,
                    "year": work.get("publication_year"),
                    "query": _clean_text(query, limit=240),
                    "source_type": "openalex",
                    "evidence_type": _infer_evidence_type(title, abstract),
                }
            )
        return entries
