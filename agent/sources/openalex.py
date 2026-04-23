from __future__ import annotations

import html
import re
from typing import Any

import httpx


OPENALEX_WORKS_URL = "https://api.openalex.org/works"


def _clean_text(value: Any, *, limit: int = 1600) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()[:limit]


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
    if any(token in haystack for token in review_tokens):
        return "review"
    if any(token in haystack for token in ("protocol", "trial design", "study design", "design and rationale", "rationale and design")):
        return "protocol"
    return "primary"


def _topics(work: dict[str, Any]) -> list[str]:
    topics = []
    for topic in work.get("topics") or []:
        name = _clean_text(topic.get("display_name"), limit=80)
        if name:
            topics.append(name)
    return topics[:6]


def _mesh_terms(work: dict[str, Any]) -> list[str]:
    mesh: list[str] = []
    for item in work.get("mesh") or []:
        descriptor = item.get("descriptor_name")
        if isinstance(descriptor, str):
            mesh.append(_clean_text(descriptor, limit=80))
        elif isinstance(descriptor, dict):
            mesh.append(_clean_text(descriptor.get("display_name") or descriptor.get("descriptor_name"), limit=80))
    return [term for term in mesh if term][:8]


def _authors(work: dict[str, Any]) -> list[str]:
    names = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = _clean_text(author.get("display_name"), limit=120)
        if name:
            names.append(name)
    return names[:6]


class OpenAlexClient:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(timeout=timeout_sec, transport=transport, headers={"User-Agent": "researka-reference-agent/0.1"})

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        response = self.client.get(
            OPENALEX_WORKS_URL,
            params={
                "search": _clean_text(query, limit=240),
                "per-page": max(1, min(limit, 20)),
                "select": "id,doi,title,abstract_inverted_index,primary_location,publication_year,topics,mesh,referenced_works,related_works,open_access,cited_by_count,authorships",
            },
        )
        response.raise_for_status()
        entries: list[dict[str, Any]] = []
        for work in response.json().get("results", []):
            title = _clean_text(work.get("title"), limit=300)
            abstract = _openalex_abstract(work.get("abstract_inverted_index"))
            topic_terms = _topics(work)
            mesh_terms = _mesh_terms(work)
            if not title:
                continue
            if not abstract:
                abstract = _clean_text("; ".join([*topic_terms[:3], *mesh_terms[:3]]), limit=600)
            if not abstract:
                continue
            location = work.get("primary_location") or {}
            doi = _clean_text(work.get("doi"), limit=256).removeprefix("https://doi.org/") or None
            source = location.get("source") or {}
            journal = _clean_text(source.get("display_name"), limit=200) or None
            open_access = work.get("open_access") or {}
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
                    "journal": journal,
                    "authors": _authors(work),
                    "topic_terms": topic_terms,
                    "mesh_terms": mesh_terms,
                    "referenced_works": work.get("referenced_works") or [],
                    "related_works": work.get("related_works") or [],
                    "oa_url": _clean_text(open_access.get("oa_url"), limit=600) or None,
                    "cited_by_count": int(work.get("cited_by_count") or 0),
                }
            )
        return entries
