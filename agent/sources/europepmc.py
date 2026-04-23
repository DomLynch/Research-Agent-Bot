from __future__ import annotations

import html
import re
from typing import Any

import httpx


EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _clean_text(value: Any, *, limit: int = 1600) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()[:limit]


def _infer_evidence_type(title: str, abstract: str) -> str:
    haystack = f"{title} {abstract}".lower()
    if any(token in haystack for token in ("systematic review", "meta-analysis", "umbrella review", "narrative review", "review")):
        return "review"
    if any(token in haystack for token in ("protocol", "trial design", "study design", "design and rationale", "rationale and design")):
        return "protocol"
    return "primary"


def _authors(author_string: Any) -> list[str]:
    text = _clean_text(author_string, limit=400)
    if not text:
        return []
    return [part.strip() for part in re.split(r",|;|\band\b", text) if part.strip()][:6]


class EuropePMCClient:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers={"User-Agent": "researka-reference-agent/0.1 (+https://researka.org)"},
        )

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        response = self.client.get(
            EUROPE_PMC_SEARCH_URL,
            params={
                "query": _clean_text(query, limit=240),
                "format": "json",
                "resultType": "core",
                "pageSize": max(1, min(limit, 25)),
            },
        )
        response.raise_for_status()
        entries: list[dict[str, Any]] = []
        for result in ((response.json().get("resultList") or {}).get("result") or []):
            title = _clean_text(result.get("title"), limit=300)
            abstract = _clean_text(result.get("abstractText"), limit=5000)
            pmcid = _clean_text(result.get("pmcid"), limit=64) or None
            metadata_excerpt = _clean_text(
                "; ".join(
                    part for part in (
                        _clean_text(result.get("journalTitle"), limit=140),
                        _clean_text(result.get("authorString"), limit=260),
                    )
                    if part
                ),
                limit=400,
            )
            excerpt = abstract or metadata_excerpt
            if not title or not excerpt:
                continue
            doi = _clean_text(result.get("doi"), limit=256).removeprefix("https://doi.org/") or None
            source = _clean_text(result.get("source"), limit=20).upper()
            article_id = _clean_text(result.get("id"), limit=40)
            url = (
                f"https://europepmc.org/article/PMC/{pmcid}"
                if pmcid
                else (f"https://europepmc.org/article/{source}/{article_id}" if source and article_id else f"https://doi.org/{doi}" if doi else "")
            )
            year = _clean_text(result.get("pubYear"), limit=8)
            entries.append(
                {
                    "id": article_id or pmcid or doi,
                    "title": title,
                    "excerpt": excerpt,
                    "url": url,
                    "doi": doi,
                    "year": int(year) if year.isdigit() else None,
                    "query": _clean_text(query, limit=240),
                    "source_type": "europepmc",
                    "evidence_type": _infer_evidence_type(title, excerpt),
                    "journal": _clean_text(result.get("journalTitle"), limit=200) or None,
                    "authors": _authors(result.get("authorString")),
                    "pmcid": pmcid,
                }
            )
            if len(entries) >= limit:
                break
        return entries
