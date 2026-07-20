"""PubMed adapter via NCBI E-utilities.

Endpoints:
  esearch.fcgi  — returns PMID list for a query (JSON)
  efetch.fcgi   — returns full article XML for a PMID list

Two calls per search. Polite pool: no API key, ≤3 req/s.
With NCBI_API_KEY env var: 10 req/s (free key, register at
https://account.ncbi.nlm.nih.gov/settings/).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable

import httpx

from agent.sources._base import (
    clean_text,
    normalize_doi,
    safe_get_json,
    safe_get_text,
)
from agent.types import RawHit

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PMID_AUDIT_RETRY_SECONDS = 60
_PMCID_RECEIPT_RE = re.compile(r"(?<![A-Z0-9])PMC\d+(?![A-Z0-9])", re.I)
_GENERIC_TITLE_WORDS = {
    "analysis", "article", "clinical", "cohort", "controlled", "effect", "effects", "paper",
    "prospective", "randomised", "randomized", "report", "research", "results", "retrospective",
    "study", "trial",
}


def pmid_rows_fingerprint(rows: list[dict[str, Any]]) -> str:
    """Hash only source-identity fields so cached audits cannot outlive their input."""
    fields = ("pmid", "source_pmid", "title", "source_title", "doi", "source_doi",
              "pmcid", "source_pmcid", "receipt_id")
    identity = [{name: str(row.get(name) or "").strip() for name in fields} for row in rows]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _identity_alias_issues(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for row in rows:
        pmids = {str(row.get(name) or "").strip() for name in ("source_pmid", "pmid")} - {""}
        dois = {normalize_doi(row.get(name)) or "" for name in ("source_doi", "doi")} - {""}
        pmcids = {clean_text(row.get(name)).upper() for name in ("source_pmcid", "pmcid")} - {""}
        pmcids.update(match.upper() for match in _PMCID_RECEIPT_RE.findall(
            str(row.get("receipt_id") or ""),
        ))
        conflicts = [name for name, values in (("pmid", pmids), ("doi", dois), ("pmcid", pmcids))
                     if len(values) > 1]
        if conflicts:
            issues.append({"receipt_id": str(row.get("receipt_id") or ""),
                           "mismatch": "conflicting_" + ",".join(conflicts)})
    return issues


def pmid_audit_is_current(audit: dict[str, Any] | None, rows: list[dict[str, Any]]) -> bool:
    if (not audit or audit.get("provider") != "ncbi_pubmed"
            or audit.get("input_fingerprint") != pmid_rows_fingerprint(rows)
            or _identity_alias_issues(rows)):
        return False
    status = audit.get("status")
    declared = sum(bool(str(row.get("source_pmid") or row.get("pmid") or "").strip()) for row in rows)
    if status == "verified":
        return bool(audit.get("passed") is True and audit.get("entries") == len(rows)
                    and audit.get("declared") == audit.get("verified") == declared
                    and audit.get("without_pmid") == len(rows) - declared
                    and audit.get("issues") == [])
    if status in {"identity_mismatch", "invalid_or_missing_pmid"}:
        return bool(audit.get("passed") is False and audit.get("entries") == len(rows))
    if status != "provider_unavailable" or audit.get("passed") is not False:
        return False
    try:
        age = time.time() - float(audit.get("checked_at") or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= age < PMID_AUDIT_RETRY_SECONDS


def pmid_audit_passed(audit: dict[str, Any] | None, rows: list[dict[str, Any]]) -> bool:
    return bool(
        pmid_audit_is_current(audit, rows)
        and audit
        and audit.get("status") == "verified"
        and int(audit.get("declared") or 0) > 0
    )


def verify_pmid_rows(
    rows: list[dict[str, Any]], *, timeout: float = 20.0,
    get: Callable[..., Any] = httpx.get,
) -> dict[str, Any]:
    """Verify declared PMID identities against one NCBI PubMed fetch."""
    declared = [row for row in rows if str(row.get("source_pmid") or row.get("pmid") or "").strip()]
    pmids = [str(row.get("source_pmid") or row.get("pmid") or "").strip() for row in declared]
    base = {"provider": "ncbi_pubmed", "entries": len(rows), "declared": len(pmids),
            "input_fingerprint": pmid_rows_fingerprint(rows), "checked_at": time.time()}
    alias_issues = _identity_alias_issues(rows)
    if alias_issues:
        return {**base, "passed": False, "status": "identity_mismatch", "verified": 0,
                "without_pmid": len(rows) - len(pmids), "issues": alias_issues}
    if not pmids or any(not pmid.isdigit() for pmid in pmids):
        return {**base, "passed": False, "status": "invalid_or_missing_pmid", "verified": 0}
    params = {"db": "pubmed", "retmode": "xml", "id": ",".join(dict.fromkeys(pmids))}
    if key := _ncbi_key():
        params["api_key"] = key
    try:
        response = get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=timeout)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except (httpx.HTTPError, ET.ParseError, OSError, ValueError) as exc:
        return {**base, "passed": False, "status": "provider_unavailable", "verified": 0,
                "error": type(exc).__name__}
    if root.tag.upper() == "ERROR" or root.find(".//ERROR") is not None:
        return {**base, "passed": False, "status": "provider_unavailable", "verified": 0,
                "error": "provider_error_payload"}
    records: dict[str, tuple[str, str, str]] = {}
    for article in root.findall("./PubmedArticle"):
        pmid = clean_text(article.findtext("./MedlineCitation/PMID"))
        title_node = article.find("./MedlineCitation/Article/ArticleTitle")
        title = clean_text("".join(title_node.itertext()) if title_node is not None else "", limit=500)
        ids = {str(node.attrib.get("IdType") or "").lower(): clean_text(node.text)
               for node in article.findall("./PubmedData/ArticleIdList/ArticleId")}
        records[pmid] = (title, normalize_doi(ids.get("doi")) or "", ids.get("pmc", "").upper())
    missing_pmids = [pmid for pmid in dict.fromkeys(pmids) if pmid not in records]
    if missing_pmids:
        return {**base, "passed": False, "status": "provider_unavailable", "verified": 0,
                "without_pmid": len(rows) - len(pmids), "error": "partial_provider_response",
                "issues": [{"pmid": pmid, "mismatch": "record_missing"} for pmid in missing_pmids]}
    issues: list[dict[str, str]] = []
    for row, pmid in zip(declared, pmids, strict=True):
        title, doi, pmcid = records.get(pmid, ("", "", ""))
        expected_title = clean_text(row.get("source_title") or row.get("title"), limit=500)
        expected_doi = normalize_doi(row.get("source_doi") or row.get("doi")) or ""
        expected_pmcid = clean_text(row.get("source_pmcid") or row.get("pmcid")).upper()
        if not expected_pmcid and (match := _PMCID_RECEIPT_RE.search(str(row.get("receipt_id") or ""))):
            expected_pmcid = match.group(0).upper()
        expected_words = re.findall(r"[a-z0-9]+", expected_title.lower())
        actual_words = re.findall(r"[a-z0-9]+", title.lower())
        expected_tokens, actual_tokens = set(expected_words), set(actual_words)
        informative_words = {
            word for word in expected_words if len(word) >= 4 and word not in _GENERIC_TITLE_WORDS
        }
        informative_title = bool(
            len(informative_words) >= 2
            and (len(expected_words) >= 5 or len(" ".join(expected_words)) >= 30)
        )
        title_match = " ".join(expected_words) in " ".join(actual_words) or (
            len(expected_tokens & actual_tokens) / max(1, len(expected_tokens | actual_tokens)) >= 0.75
        )
        matches = ({"title": title_match} if expected_title else {})
        matches.update({"doi": expected_doi == doi} if expected_doi else {})
        matches.update({"pmcid": expected_pmcid == pmcid} if expected_pmcid else {})
        mismatches = [name for name, matched in matches.items() if not matched]
        if expected_title and not (expected_doi or expected_pmcid) and not informative_title:
            mismatches.append("title_under_specified")
        if not records.get(pmid) or not matches or mismatches:
            issues.append({"receipt_id": str(row.get("receipt_id") or ""), "pmid": pmid,
                           "mismatch": ",".join(mismatches) or "record_missing"})
    return {**base, "passed": not issues, "status": "verified" if not issues else "identity_mismatch",
            "verified": len(pmids) - len(issues), "without_pmid": len(rows) - len(pmids), "issues": issues}


def _ncbi_key() -> str | None:
    """Return NCBI API key from env. None = polite-pool (3 req/s).
    Set: NCBI_API_KEY=<your-key>.
    Register at https://account.ncbi.nlm.nih.gov/settings/."""
    key = os.environ.get("NCBI_API_KEY")
    return key.strip() if key else None


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
            "term": clean_text(query, limit=3000),
        }
        # Add NCBI API key if available (3 req/s → 10 req/s)
        key = _ncbi_key()
        if key:
            params["api_key"] = key
        data = await safe_get_json(
            client, f"{EUTILS_BASE}/esearch.fcgi", params=params,
        )
        if data is None:
            return []
        payload = data.get("esearchresult", {})
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
        # NCBI key bumps rate limit from 3/s → 10/s
        key = _ncbi_key()
        if key:
            params["api_key"] = key
        text = await safe_get_text(
            client, f"{EUTILS_BASE}/efetch.fcgi", params=params,
        )
        if text is None:
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
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
        # 4000 char window keeps the results section intact for classification.
        # Earlier 1600 cap clipped 47% of abstracts mid-methodology, hiding
        # outcome markers and forcing real RCTs into the mechanistic default.
        abstract = clean_text(abstract_text, limit=4000)
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
            raw={"query": clean_text(query, limit=3000)},
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
