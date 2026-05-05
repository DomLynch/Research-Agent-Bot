"""arXiv adapter.

Endpoint: https://export.arxiv.org/api/query
Free, no auth. Atom 1.0 XML response only (no JSON option).

Per arXiv's user manual (info.arxiv.org/help/api/user-manual.html, fetched
2026-05-04): "we encourage you to play nice and incorporate a 3 second
delay in your code." Implements the same async-lock rate-limit pattern as
the Semantic Scholar adapter to keep parallel SourceAggregator fan-outs
within the polite-use threshold.

arXiv's biomedical signal is thin — it's a physics/CS/math preprint
server. Hosted under cs.{AI,LG,CL} categories, occasionally under q-bio.
For a drug-class topic, expect 0-3 hits per query. Included for breadth
on methodology / cross-domain papers (statistical methods, ML for
biomedicine, computational biology).
"""
from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET

import httpx

from agent.sources._base import clean_text, normalize_doi, safe_get_text
from agent.types import RawHit

_ARXIV_URL = "https://export.arxiv.org/api/query"

# Polite-use rate limit (arXiv manual recommends 3 sec between requests).
# Slightly buffered to 3.1s; cumulative across all client instances within
# a single event loop via async-safe lock.
_RATE_LIMIT_SEC = 3.1
_rate_lock = asyncio.Lock()
_last_call_ts: float = 0.0

# Atom 1.0 namespaces used in arXiv responses.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


async def _await_rate_limit() -> None:
    """Async-safe polite-use gate: at most 1 call per _RATE_LIMIT_SEC
    seconds, cumulative across all ArxivClient instances."""
    global _last_call_ts
    async with _rate_lock:
        now = time.monotonic()
        wait = _RATE_LIMIT_SEC - (now - _last_call_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_ts = time.monotonic()


def _build_search_query(query: str) -> str:
    """Convert a free-text query like 'aspirin AND aging AND elderly'
    into arXiv's prefixed query format `all:aspirin+AND+all:aging+...`.
    Words separated by 'AND' get the `all:` prefix; everything else
    falls back to a single `all:<phrase>` query."""
    cleaned = clean_text(query, limit=3000)
    # Split on AND/OR while preserving operators.
    tokens = re.split(r"\s+(AND|OR)\s+", cleaned)
    if len(tokens) == 1:
        return f"all:{tokens[0].strip()}"
    out: list[str] = []
    for tok in tokens:
        t = tok.strip()
        if not t:
            continue
        if t in ("AND", "OR"):
            out.append(t)
        else:
            # Strip any leading parens/quotes from a clause.
            t = t.replace("(", "").replace(")", "")
            t = t.replace('"', "").strip()
            if t:
                out.append(f"all:{t}")
    return " ".join(out)


class ArxivClient:
    name = "arxiv"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "search_query": _build_search_query(query),
            "max_results": str(max(1, min(limit, 1000))),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        await _await_rate_limit()
        text = await safe_get_text(client, _ARXIV_URL, params=params)
        if text is None:
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        out: list[RawHit] = []
        for entry in root.findall("atom:entry", _NS):
            hit = self._parse(entry, query=query)
            if hit:
                out.append(hit)
        return out

    def _parse(
        self, entry: ET.Element, *, query: str,
    ) -> RawHit | None:
        title_el = entry.find("atom:title", _NS)
        summary_el = entry.find("atom:summary", _NS)
        title = clean_text(
            title_el.text if title_el is not None else "", limit=300,
        )
        abstract = clean_text(
            summary_el.text if summary_el is not None else "",
            limit=4000,
        )
        if not title or not abstract:
            return None
        # arXiv ID lives in <id>http://arxiv.org/abs/2401.12345v1</id>
        id_el = entry.find("atom:id", _NS)
        arxiv_id = ""
        if id_el is not None and id_el.text:
            m = re.search(r"abs/([^v]+)", id_el.text)
            if m:
                arxiv_id = m.group(1)
        # DOI (when authors registered one — many don't)
        doi_el = entry.find("arxiv:doi", _NS)
        doi = normalize_doi(
            doi_el.text if doi_el is not None else None,
        )
        # Publication year from <published>YYYY-MM-DD...</published>
        pub_el = entry.find("atom:published", _NS)
        year: int | None = None
        if pub_el is not None and pub_el.text:
            m = re.match(r"(\d{4})", pub_el.text)
            if m:
                try:
                    year = int(m.group(1))
                except ValueError:
                    year = None
        # Best URL: prefer DOI, else arXiv abstract page
        url = (
            f"https://doi.org/{doi}" if doi
            else (
                f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id
                else "https://arxiv.org/"
            )
        )
        return RawHit(
            source=self.name,
            title=title,
            abstract=abstract,
            year=year,
            url=url,
            doi=doi,
            pmid=None,
            nct=None,
            venue="arXiv preprint",
            raw={"arxiv_id": arxiv_id},
        )
