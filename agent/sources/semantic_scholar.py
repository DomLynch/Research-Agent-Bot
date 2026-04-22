"""Semantic Scholar citation graph adapter.

Three modes:
  1. search(query)            — topic-based search (same shape as PubMed/OpenAlex)
  2. references_of(doi)       — fetch the reference list of a given paper
  3. citations_of(doi)        — fetch papers that cite a given paper

Mode 1 is the drop-in retrieval source (works like existing clients).
Modes 2-3 enable citation-graph traversal from known good reviews.

API docs: https://api.semanticscholar.org/api-docs/
Rate limits: ~100 req/5min without key, ~1 req/sec with key.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx


BASE_URL = "https://api.semanticscholar.org/graph/v1"
USER_AGENT = "researka-reference-agent/0.1 (+https://researka.org)"
DEFAULT_TIMEOUT = 12.0


class SemanticScholarClient:
    def __init__(
        self,
        *,
        api_key_env: str = "SEMANTIC_SCHOLAR_API_KEY",
        timeout_sec: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = os.getenv(api_key_env, "").strip()
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers=headers,
        )

    # ---- Public API ----

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Topic search — returns up to `limit` papers matching the query string.

        Matches the shape of PubMedClient.search() for drop-in compatibility:
        each result dict has: title, excerpt, year, doi, url, source_type,
        evidence_type, query.
        """
        params = {
            "query": _clean(query, limit=240),
            "limit": max(1, min(limit, 100)),
            "fields": "title,abstract,year,externalIds,publicationTypes",
        }
        data = self._get("/paper/search", params=params)
        return [self._normalize(item, query, source_mode="search")
                for item in data.get("data", [])]

    def references_of(self, doi: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return papers that `doi` cites (its reference list)."""
        normalized = _normalize_doi(doi)
        if not normalized:
            return []
        params = {
            "limit": max(1, min(limit, 100)),
            "fields": "title,abstract,year,externalIds,publicationTypes",
        }
        data = self._get(f"/paper/DOI:{normalized}/references", params=params)
        return [self._normalize(_unwrap_citation(item), f"references_of:{normalized}",
                                 source_mode="reference")
                for item in data.get("data", [])
                if _unwrap_citation(item)]

    def citations_of(self, doi: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return papers that cite `doi` (newer work citing this paper)."""
        normalized = _normalize_doi(doi)
        if not normalized:
            return []
        params = {
            "limit": max(1, min(limit, 100)),
            "fields": "title,abstract,year,externalIds,publicationTypes",
        }
        data = self._get(f"/paper/DOI:{normalized}/citations", params=params)
        return [self._normalize(_unwrap_citation(item), f"citations_of:{normalized}",
                                 source_mode="citing")
                for item in data.get("data", [])
                if _unwrap_citation(item)]

    # ---- Internals ----

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET with one retry on 429 (rate limit). Returns empty dict on error."""
        for attempt in range(2):
            try:
                r = self.client.get(f"{BASE_URL}{path}", params=params)
                if r.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, ValueError):
                return {}
        return {}

    def _normalize(self, paper: dict[str, Any], query: str,
                   *, source_mode: str) -> dict[str, Any]:
        """Convert a Semantic Scholar paper dict to the shared source shape."""
        ext = paper.get("externalIds") or {}
        doi = _normalize_doi(ext.get("DOI"))
        pmid = ext.get("PubMed") or ""
        title = _clean(paper.get("title"), limit=300)
        excerpt = _clean(paper.get("abstract"), limit=1600)
        year = paper.get("year")
        if isinstance(year, str) and year.isdigit():
            year = int(year)
        elif not isinstance(year, int):
            year = None
        pub_types = paper.get("publicationTypes") or []
        evidence_type = _infer_evidence_type(pub_types, title, excerpt)
        url = _build_url(doi, pmid)
        return {
            "title": title,
            "excerpt": excerpt,
            "year": year,
            "doi": doi,
            "url": url,
            "source_type": "semantic_scholar",
            "evidence_type": evidence_type,
            "query": _clean(query, limit=240),
            "_s2_mode": source_mode,
        }


# ---- Helpers ----

_DOI_RE = re.compile(r"^10\.\d{3,}/[^\s]+$")


def _normalize_doi(value: Any) -> str:
    if not value:
        return ""
    raw = str(value).strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "DOI:"):
        if raw.lower().startswith(prefix.lower()):
            raw = raw[len(prefix):]
    raw = raw.strip().lower()
    return raw if _DOI_RE.match(raw) else ""


def _clean(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _unwrap_citation(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """S2 wraps references/citations as {citingPaper: {...}} or {citedPaper: {...}}."""
    if not isinstance(item, dict):
        return None
    for key in ("citedPaper", "citingPaper"):
        if isinstance(item.get(key), dict):
            return item[key]
    return item if "title" in item else None


def _infer_evidence_type(pub_types: list[str], title: str, excerpt: str) -> str:
    """Map S2 publicationTypes + text heuristics to existing evidence_type labels."""
    pub_types_lower = [str(p).lower() for p in pub_types]
    text = f"{title} {excerpt}".lower()
    if any("review" in p for p in pub_types_lower):
        return "review"
    if any(p in pub_types_lower for p in ("meta-analysis", "systematic review")):
        return "review"
    if any(term in text for term in ("systematic review", "meta-analysis", "umbrella review")):
        return "review"
    if any("clinicaltrial" in p or "randomizedcontrolledtrial" in p for p in pub_types_lower):
        return "interventional"
    if "randomized" in text and "trial" in text:
        return "interventional"
    if "cohort" in text or "longitudinal" in text:
        return "observational"
    return "primary"


def _build_url(doi: str, pmid: str) -> str:
    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return ""
