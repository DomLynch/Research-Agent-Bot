from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as et
from pathlib import Path
from typing import Any

import httpx

from agent.sources.core import COREClient
from agent.sources.unpaywall import UnpaywallClient


EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_XML_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
_SECTION_LABELS = {
    "methods": ("method", "materials", "patients and methods"),
    "results": ("result",),
    "discussion": ("discussion", "conclusion"),
}


def _clean_text(value: Any, *, limit: int = 20000) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def entry_identity(entry: dict[str, Any]) -> str:
    for key in ("doi", "url", "id", "title"):
        value = _clean_text(entry.get(key), limit=600).lower()
        if value:
            return value
    return ""


def _pmid_from_entry(entry: dict[str, Any]) -> str | None:
    text = " ".join(str(entry.get(k) or "") for k in ("id", "url"))
    match = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)|\bpmid[:/\s]*(\d+)\b|\b(\d{5,10})\b", text, re.IGNORECASE)
    if not match:
        return None
    for group in match.groups():
        if group and group.isdigit():
            return group
    return None


def _cache_path(cache_dir: Path, entry: dict[str, Any]) -> Path:
    identity = entry_identity(entry) or json.dumps(entry, sort_keys=True)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _section_name(title: str) -> str | None:
    lower = title.lower()
    for name, labels in _SECTION_LABELS.items():
        if any(label in lower for label in labels):
            return name
    return None


def _parse_full_text(xml_text: str) -> dict[str, Any]:
    root = et.fromstring(xml_text)
    body_text = _clean_text(" ".join("".join(node.itertext()) for node in root.findall(".//body//p")))
    sections: dict[str, str] = {}
    for sec in root.findall(".//body//sec"):
        title = _clean_text(sec.findtext("title"), limit=200)
        section_key = _section_name(title)
        if not section_key or section_key in sections:
            continue
        section_text = _clean_text(" ".join("".join(node.itertext()) for node in sec.findall(".//p")), limit=6000)
        if section_text:
            sections[section_key] = section_text
    if not body_text:
        body_text = _clean_text(" ".join(sections.values()))
    return {"text": body_text, "sections": sections}


class FullTextFetcher:
    def __init__(
        self,
        *,
        cache_dir: str | Path,
        timeout_sec: float = 12.0,
        transport: httpx.BaseTransport | None = None,
        unpaywall_client: UnpaywallClient | None = None,
        core_client: COREClient | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(timeout=timeout_sec, transport=transport, headers={"User-Agent": "researka-reference-agent/0.1"})
        self.unpaywall = unpaywall_client or UnpaywallClient(
            cache_dir=self.cache_dir / "unpaywall-cache",
            timeout_sec=timeout_sec,
            transport=transport,
        )
        self.core = core_client or COREClient(
            cache_dir=self.cache_dir / "core-cache",
            timeout_sec=timeout_sec,
            transport=transport,
        )

    def _search_query(self, entry: dict[str, Any]) -> str | None:
        pmcid = _clean_text(entry.get("pmcid"), limit=64)
        if pmcid:
            return f"PMCID:{pmcid}"
        doi = _clean_text(entry.get("doi"), limit=256)
        if doi:
            return f'DOI:"{doi}"'
        pmid = _pmid_from_entry(entry)
        if pmid:
            return f"EXT_ID:{pmid} AND SRC:MED"
        return None

    def _fetch_europepmc(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        query = self._search_query(entry)
        if not query:
            return None
        response = self.client.get(EUROPE_PMC_SEARCH_URL, params={"query": query, "format": "json", "pageSize": 1, "resultType": "core"})
        response.raise_for_status()
        result = ((response.json().get("resultList") or {}).get("result") or [{}])[0]
        pmcid = _clean_text(result.get("pmcid"), limit=64)
        if not pmcid:
            return None
        return self._fetch_pmc_xml(pmcid, source="europepmc")

    def _fetch_pmc_xml(self, pmcid: str, *, source: str) -> dict[str, Any] | None:
        xml_response = self.client.get(EUROPE_PMC_XML_URL.format(pmcid=pmcid))
        xml_response.raise_for_status()
        parsed = _parse_full_text(xml_response.text)
        if not parsed["text"]:
            return None
        return {
            "found": True,
            "pmcid": pmcid,
            "source": source,
            "text": parsed["text"],
            "sections": parsed["sections"],
        }

    def _detect_pmcid(self, *urls: str) -> str | None:
        for url in urls:
            match = re.search(r"/articles/(PMC\d+)", str(url or ""), re.IGNORECASE)
            if match:
                return match.group(1).upper()
        return None

    def _fetch_unpaywall(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        doi = _clean_text(entry.get("doi"), limit=300)
        payload = self.unpaywall.resolve(doi)
        if not payload or not payload.get("is_oa"):
            return None
        pmcid = self._detect_pmcid(payload.get("location_url", ""), payload.get("best_pdf_url", ""))
        if pmcid:
            parsed = self._fetch_pmc_xml(pmcid, source="unpaywall_jats")
            if parsed:
                return parsed
        pdf_url = _clean_text(payload.get("best_pdf_url"), limit=600) or _clean_text(payload.get("location_url"), limit=600)
        if pdf_url:
            return {
                "found": True,
                "source": "unpaywall_pdf_only",
                "text": "",
                "sections": {},
                "pdf_url": pdf_url,
            }
        return None

    def _fetch_core(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        payload = self.core.fetch_by_doi(_clean_text(entry.get("doi"), limit=300))
        if not payload:
            return None
        return {
            "found": True,
            "source": "core",
            "text": _clean_text(payload.get("text")),
            "sections": payload.get("sections") or {},
            "pdf_url": payload.get("download_url") or "",
        }

    def fetch(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        cache_path = _cache_path(self.cache_dir, entry)
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return payload if payload.get("found") else None
        pmcid = _clean_text(entry.get("pmcid"), limit=64)
        if pmcid:
            try:
                payload = self._fetch_pmc_xml(pmcid, source="europepmc")
            except (httpx.HTTPError, OSError, ValueError, et.ParseError):
                payload = None
            if payload:
                cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                return payload
        if not self._search_query(entry):
            cache_path.write_text(json.dumps({"found": False, "reason": "no_lookup"}), encoding="utf-8")
            return None
        try:
            payload = self._fetch_europepmc(entry)
        except (httpx.HTTPError, OSError, ValueError, et.ParseError):
            payload = None
        if not payload:
            try:
                payload = self._fetch_unpaywall(entry)
            except (httpx.HTTPError, OSError, ValueError, et.ParseError):
                payload = None
        if not payload:
            try:
                payload = self._fetch_core(entry)
            except (httpx.HTTPError, OSError, ValueError):
                payload = None
        if payload:
            cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload
        cache_path.write_text(json.dumps({"found": False, "reason": "no_full_text"}), encoding="utf-8")
        return None

    def enrich_entries(self, entries: list[dict[str, Any]], *, limit: int = 12) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        attempted = 0
        found_any = 0
        parseable_text_count = 0
        source_counts: dict[str, int] = {}
        for entry in entries:
            cloned = dict(entry)
            if attempted < limit and cloned.get("source_type") in {"pubmed", "openalex", "rxiv", "semantic_scholar", "europepmc"}:
                attempted += 1
                try:
                    payload = self.fetch(cloned)
                except (httpx.HTTPError, OSError, ValueError, et.ParseError):
                    payload = None
                if payload:
                    found_any += 1
                    source = str(payload.get("source") or "unknown")
                    source_counts[source] = source_counts.get(source, 0) + 1
                    if payload.get("text"):
                        parseable_text_count += 1
                        cloned["full_text"] = payload.get("text", "")
                        cloned["full_text_sections"] = payload.get("sections", {})
                    cloned["full_text_source"] = payload.get("source")
                    cloned["pmcid"] = payload.get("pmcid")
                    if payload.get("pdf_url"):
                        cloned["full_text_pdf_url"] = payload.get("pdf_url")
                else:
                    source_counts["none"] = source_counts.get("none", 0) + 1
            enriched.append(cloned)
        return enriched, {
            "attempted": attempted,
            "found": parseable_text_count,
            "found_any": found_any,
            "parseable_text_count": parseable_text_count,
            "source_counts": source_counts,
        }
