"""OpenCitations Meta v1 enrichment — bibliographic provenance per DOI.

Endpoint: https://api.opencitations.net/meta/v1/metadata/{ids}
Per OpenCitations docs (api.opencitations.net/meta/v1, fetched 2026-05-04):
  - 180 requests/minute per IP (≈3 req/sec sustained)
  - Auth: optional but recommended via Authorization header. Set
    OPENCITATIONS_ACCESS_TOKEN env var to use one (improves rate
    limits + reliability under load).

Multiple identifiers can be batched in a single call by joining with
`__` (double underscore): e.g.
    /metadata/doi:10.1/x__doi:10.1/y__pmid:12345

Use case for Researka: given a list of DOIs from the discovered corpus,
fetch verified bibliographic metadata (title, authors with ORCIDs when
present, venue, publication date). Complements iCite (PMID-keyed,
citation impact) with DOI-keyed publishing provenance — important for
the audit appendix's "is this a real paper?" gate.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

_OPENCITATIONS_META_URL = "https://api.opencitations.net/meta/v1/metadata"
# Cap per request to keep URLs short and avoid 414. With ~30 chars per
# DOI and an "__" separator, 20 DOIs fits well under typical 2KB URL
# limits. Larger batches risk truncation by intermediate proxies.
_MAX_BATCH_SIZE = 20


@dataclass(frozen=True, slots=True)
class OpenCitationsRecord:
    """Compact bibliographic record returned by OpenCitations Meta."""
    doi: str                  # primary key (lower-case, no protocol)
    omid: str                 # OpenCitations Meta ID
    title: str
    authors: tuple[str, ...] = field(default_factory=tuple)
    pub_date: str = ""        # YYYY or YYYY-MM-DD
    venue: str = ""
    publisher: str = ""
    work_type: str = ""       # journal article, book chapter, etc.


class OpenCitationsMetaClient:
    """Batch-fetch bibliographic metadata for known DOIs.

    Usage:
        client = OpenCitationsMetaClient()
        async with httpx.AsyncClient() as h:
            recs = await client.fetch(h, ["10.1093/ageing/afaf271"])
            print(recs["10.1093/ageing/afaf271"].authors)
    """

    name = "opencitations_meta"

    def _headers(self) -> dict[str, str]:
        token = os.environ.get("OPENCITATIONS_ACCESS_TOKEN")
        if token:
            return {"authorization": token}
        return {}

    async def fetch(
        self,
        client: httpx.AsyncClient,
        dois: list[str] | tuple[str, ...],
    ) -> dict[str, OpenCitationsRecord]:
        """Returns {doi_lowercase: OpenCitationsRecord} for every DOI in
        the input that OpenCitations recognizes. Missing DOIs silently
        dropped. Splits into batches of _MAX_BATCH_SIZE."""
        out: dict[str, OpenCitationsRecord] = {}
        cleaned = [
            d.strip().lower() for d in dois if d and d.strip()
        ]
        # Dedupe preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for d in cleaned:
            if d not in seen:
                seen.add(d)
                unique.append(d)
        for i in range(0, len(unique), _MAX_BATCH_SIZE):
            batch = unique[i:i + _MAX_BATCH_SIZE]
            ids_param = "__".join(f"doi:{d}" for d in batch)
            url = f"{_OPENCITATIONS_META_URL}/{ids_param}"
            try:
                response = await client.get(
                    url, headers=self._headers(), timeout=30.0,
                )
            except httpx.HTTPError:
                continue
            # Fail-soft on 429 / auth / 5xx — same policy as corpus adapters
            if response.status_code in (401, 403, 429):
                continue
            if response.status_code >= 500 or response.status_code != 200:
                continue
            try:
                records = response.json()
            except ValueError:
                continue
            if not isinstance(records, list):
                continue
            for record in records:
                rec = self._parse(record)
                if rec:
                    out[rec.doi] = rec
        return out

    @staticmethod
    def _parse(record: dict[str, Any]) -> OpenCitationsRecord | None:
        # The 'id' field is space-separated tokens like
        # "doi:10.1/x omid:br/123 pmid:456". Pull each by prefix.
        id_field = (record.get("id") or "").strip()
        if not id_field:
            return None
        doi = ""
        omid = ""
        for token in id_field.split():
            if token.startswith("doi:"):
                doi = token[len("doi:"):].lower()
            elif token.startswith("omid:"):
                omid = token[len("omid:"):]
        if not doi:
            return None
        # Authors are semicolon-separated, possibly with " [orcid:X]" or
        # " [omid:Y]" suffixes — strip those for the display name.
        authors_raw = (record.get("author") or "").strip()
        author_list: list[str] = []
        if authors_raw:
            for chunk in authors_raw.split(";"):
                # "Surname, Given [orcid:..., omid:...]" → "Surname, Given"
                name = chunk.split("[")[0].strip()
                if name:
                    author_list.append(name)
        return OpenCitationsRecord(
            doi=doi,
            omid=omid,
            title=(record.get("title") or "").strip()[:300],
            authors=tuple(author_list[:50]),
            pub_date=(record.get("pub_date") or "").strip()[:16],
            venue=(record.get("venue") or "").strip()[:200],
            publisher=(record.get("publisher") or "").strip()[:200],
            work_type=(record.get("type") or "").strip()[:64],
        )
