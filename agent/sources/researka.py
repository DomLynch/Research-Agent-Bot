from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import httpx

from agent.sources._base import USER_AGENT, SourceResult, clean_text, normalize_doi
from agent.types import RawHit

RESEARKA_BASE = "https://database.researka.org"
TOPIC_PAPERS_PATH = "/api/v1/papers/topic"
FACT_SEARCH_PATH = "/api/v1/tier2/facts/search"
CORPUS_SEARCH_PATH = "/api/v1/search"
_FIRST_WORD_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_\-]+)")


def _researka_token() -> str | None:
    tok = os.environ.get("RESEARKA_DATABASE_TOKEN")
    return tok.strip() if tok and tok.strip() else None


def _topic_from_query(query: str) -> str:
    m = _FIRST_WORD_RE.search(query)
    return m.group(1).lower() if m else clean_text(query, limit=64).lower()


def _build_url(doi: str | None, pmid: str | None, pmcid: str | None) -> str:
    if doi:
        return f"https://doi.org/{doi}"
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    pid = pmcid.lstrip("PMC").lstrip("pmc") if pmcid else ""
    return f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pid}/" if pid else ""


def _fact_phrase(fact: dict[str, Any]) -> str:
    phrase = fact.get("canonical_phrase")
    if not isinstance(phrase, str) or not phrase.strip():
        return ""
    value = fact.get("numeric_value")
    units = clean_text(fact.get("units"), limit=40)
    suffix = f" [{value} {units or ''}]".rstrip() if value is not None else ""
    tier = fact.get("source_tier") or "tier2"
    status = (fact.get("validation") or {}).get("status")
    mark = f"{tier}:{status}" if status else str(tier)
    return f"{phrase.strip()} ({mark}){suffix}"


def _facts_text(facts: Any) -> str:
    phrases = [_fact_phrase(f) for f in (facts if isinstance(facts, list) else []) if isinstance(f, dict)]
    phrases = [p for p in phrases if p]
    return " Database facts: " + " | ".join(phrases[:8]) if phrases else ""


def _paper_from_fact(fact: dict[str, Any]) -> dict[str, Any] | None:
    paper = fact.get("paper")
    phrase = _fact_phrase(fact)
    if not isinstance(paper, dict) or not phrase:
        return None
    return {**paper, "id": fact.get("paper_id"), "abstract": f"Database fact: {phrase}", "facts": [fact]}


def _hit_from_paper(record: dict[str, Any], query: str, *, lane: str = "") -> RawHit | None:
    title = clean_text(record.get("title"), limit=400)
    if not title:
        return None
    doi = normalize_doi(record.get("doi"))
    pmid_raw = record.get("pmid")
    pmcid_raw = record.get("pmcid")
    pmid = str(pmid_raw).strip() if pmid_raw not in (None, "") else None
    pmcid = str(pmcid_raw).strip() if pmcid_raw not in (None, "") else None
    facts = record.get("facts") if isinstance(record.get("facts"), list) else []
    abstract = clean_text(record.get("abstract"), limit=4000)
    abstract = clean_text(abstract + _facts_text(facts), limit=5000)
    return RawHit(
        source="researka",
        title=title,
        abstract=abstract,
        year=record.get("publication_year") if isinstance(record.get("publication_year"), int) else record.get("year") if isinstance(record.get("year"), int) else None,
        url=_build_url(doi, pmid, pmcid),
        doi=doi,
        pmid=pmid,
        venue=clean_text(record.get("journal_name") or record.get("journal"), limit=200) or None,
        raw={
            "query": clean_text(query, limit=300),
            "paper_id": record.get("id") or record.get("paper_id"),
            "pmcid": pmcid,
            "lane": lane or record.get("lane"),
            "cited_by_count": record.get("cited_by_count"),
            "quality_score": record.get("quality_score"),
            "database_facts": facts,
        },
    )


def _key(hit: RawHit) -> str:
    if hit.doi:
        return f"doi:{hit.doi}"
    if hit.pmid:
        return f"pmid:{hit.pmid}"
    if hit.raw.get("paper_id"):
        return f"paper:{hit.raw['paper_id']}"
    return f"title:{hit.title.lower()[:120]}"


def _score(hit: RawHit) -> tuple[int, int, int]:
    facts = hit.raw.get("database_facts") or []
    return (int(any(f.get("source_tier") == "tier1" for f in facts if isinstance(f, dict))), len(facts), len(hit.abstract))


def _merge(hits: list[RawHit], limit: int) -> list[RawHit]:
    out: dict[str, RawHit] = {}
    for hit in hits:
        key = _key(hit)
        if key not in out or _score(hit) > _score(out[key]):
            out[key] = hit
    return sorted(out.values(), key=_score, reverse=True)[:limit]


def _shape_status(path: str, data: Any) -> tuple[str, str]:
    if path in {FACT_SEARCH_PATH, TOPIC_PAPERS_PATH}:
        return ("ok", "") if isinstance(data, list) else ("bad_shape", f"{path} returned {type(data).__name__}")
    if path == CORPUS_SEARCH_PATH:
        return ("ok", "") if isinstance(data, dict) else ("bad_shape", f"{path} returned {type(data).__name__}")
    return "ok", ""


class ResearkaClient:
    name = "researka"

    async def _post(self, client: httpx.AsyncClient, token: str, path: str, body: dict[str, Any]) -> tuple[Any, str, str]:
        try:
            resp = await client.post(
                RESEARKA_BASE + path,
                json=body,
                headers={"X-Researka-Token": token, "User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            return None, "transport_error", f"{type(exc).__name__}: {str(exc)[:160]}"
        if resp.status_code in (401, 403):
            return None, "auth_failed", f"HTTP {resp.status_code}"
        if resp.status_code == 429:
            return None, "rate_limited", "HTTP 429"
        if resp.status_code >= 500:
            return None, "server_error", f"HTTP {resp.status_code}"
        if resp.status_code != 200:
            return None, "http_error", f"HTTP {resp.status_code}"
        try:
            return resp.json(), "ok", ""
        except ValueError as exc:
            return None, "bad_json", f"{type(exc).__name__}: {str(exc)[:160]}"

    async def search_result(self, client: httpx.AsyncClient, query: str, *, limit: int) -> SourceResult:
        token = _researka_token()
        topic = _topic_from_query(query)
        if not token or not topic:
            return SourceResult([], "missing_token", "RESEARKA_DATABASE_TOKEN missing")
        cap = max(1, min(int(limit), 50))
        fact_result, paper_result, corpus_result = await asyncio.gather(
            self._post(client, token, FACT_SEARCH_PATH, {
                "query": query, "top_k": cap, "min_confidence": "high", "numeric_only": True,
            }),
            self._post(client, token, TOPIC_PAPERS_PATH, {
                "topic": topic, "limit": cap, "include_facts": True,
                "facts_per_paper": 8, "min_confidence": "high",
            }),
            self._post(client, token, CORPUS_SEARCH_PATH, {
                "query": query, "established_k": min(cap, 30),
                "discovery_k": min(cap // 2, 25), "semantic_k": min(cap, 30),
            }),
        )
        facts, papers, corpus = (fact_result[0], paper_result[0], corpus_result[0])
        hits: list[RawHit] = []
        if isinstance(facts, list):
            hits += [h for f in facts if isinstance(f, dict) for p in [_paper_from_fact(f)] if p for h in [_hit_from_paper(p, query, lane="fact")] if h]
        if isinstance(papers, list):
            hits += [h for p in papers if isinstance(p, dict) for h in [_hit_from_paper(p, query, lane="topic")] if h]
        if isinstance(corpus, dict):
            for lane in ("established", "discovery", "semantic"):
                rows = corpus.get(lane)
                if isinstance(rows, list):
                    hits += [h for p in rows if isinstance(p, dict) for h in [_hit_from_paper(p, query, lane=lane)] if h]
        shaped = [
            _shape_status(FACT_SEARCH_PATH, facts) if fact_result[1] == "ok" else (fact_result[1], fact_result[2]),
            _shape_status(TOPIC_PAPERS_PATH, papers) if paper_result[1] == "ok" else (paper_result[1], paper_result[2]),
            _shape_status(CORPUS_SEARCH_PATH, corpus) if corpus_result[1] == "ok" else (corpus_result[1], corpus_result[2]),
        ]
        statuses = [status for status, _error in shaped]
        status = "ok" if all(s == "ok" for s in statuses) else next(s for s in statuses if s != "ok")
        error = "; ".join(e for _status, e in shaped if e)
        return SourceResult(_merge(hits, cap), status, error)

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int) -> list[RawHit]:
        return (await self.search_result(client, query, limit=limit)).hits
