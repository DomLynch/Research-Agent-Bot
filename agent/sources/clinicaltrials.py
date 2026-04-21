from __future__ import annotations

import html
import re
from typing import Any

import httpx

CLINICALTRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"


def _clean_text(value: Any, *, limit: int = 1600) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()[:limit]


def _extract_year(study: dict[str, Any]) -> int | None:
    status = (study.get("protocolSection") or {}).get("statusModule") or {}
    for key in ("primaryCompletionDateStruct", "completionDateStruct", "startDateStruct", "studyFirstPostDateStruct"):
        date_str = (status.get(key) or {}).get("date", "")
        if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
            return int(date_str[:4])
    return None


def _extract_excerpt(study: dict[str, Any]) -> str:
    desc = (study.get("protocolSection") or {}).get("descriptionModule") or {}
    return _clean_text(desc.get("briefSummary"))


def _extract_title(study: dict[str, Any]) -> str:
    ident = (study.get("protocolSection") or {}).get("identificationModule") or {}
    return _clean_text(ident.get("briefTitle") or ident.get("officialTitle"), limit=300)


def _extract_nct_id(study: dict[str, Any]) -> str:
    ident = (study.get("protocolSection") or {}).get("identificationModule") or {}
    return _clean_text(ident.get("nctId"))


def _is_interventional(study: dict[str, Any]) -> str:
    design = (study.get("protocolSection") or {}).get("designModule") or {}
    study_type = _clean_text(design.get("studyType")).lower()
    return "interventional" if study_type == "interventional" else "observational"


class ClinicalTrialsClient:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers={"User-Agent": "researka-reference-agent/0.1"},
        )

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        response = self.client.get(
            CLINICALTRIALS_URL,
            params={
                "query.term": _clean_text(query, limit=240),
                "pageSize": max(1, min(limit, 20)),
                "format": "json",
            },
        )
        response.raise_for_status()
        entries: list[dict[str, Any]] = []
        for study in response.json().get("studies", []):
            nct_id = _extract_nct_id(study)
            title = _extract_title(study)
            excerpt = _extract_excerpt(study)
            if not nct_id or not title or not excerpt:
                continue
            year = _extract_year(study)
            design = _is_interventional(study)
            entries.append(
                {
                    "id": nct_id,
                    "title": title,
                    "excerpt": excerpt,
                    "url": f"https://clinicaltrials.gov/study/{nct_id}",
                    "doi": None,
                    "year": year,
                    "query": _clean_text(query, limit=240),
                    "source_type": "clinicaltrials",
                    "evidence_type": design,
                    "journal": None,
                }
            )
            if len(entries) >= limit:
                break
        return entries
