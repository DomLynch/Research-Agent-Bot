from __future__ import annotations

import re
from typing import Any

import httpx


NIH_REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"


def _clean(value: Any, *, limit: int = 1800) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _pick(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload.get(name)
    lowered = {str(k).lower(): v for k, v in payload.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _year(project: dict[str, Any]) -> int | None:
    for value in (
        _pick(project, "fiscal_year", "fiscalYear", "fy"),
        _pick(project, "project_start_date", "projectStartDate"),
        _pick(project, "project_end_date", "projectEndDate"),
    ):
        text = _clean(value, limit=16)
        match = re.match(r"(\d{4})", text)
        if match:
            return int(match.group(1))
    return None


class NIHReporterClient:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers={"User-Agent": "researka-reference-agent/0.1"},
        )

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        response = self.client.post(
            NIH_REPORTER_URL,
            json={
                "criteria": {
                    "advanced_text_search": {
                        "operator": "and",
                        "search_field": "projecttitle,abstracttext,terms",
                        "search_text": _clean(query, limit=240),
                    }
                },
                "include_fields": [
                    "project_title",
                    "project_num",
                    "project_start_date",
                    "project_end_date",
                    "fiscal_year",
                    "phr_text",
                    "terms",
                    "project_detail_url",
                    "principal_investigators",
                ],
                "sort_field": "project_start_date",
                "sort_order": "desc",
                "offset": 0,
                "limit": max(1, min(limit, 25)),
            },
        )
        response.raise_for_status()
        entries: list[dict[str, Any]] = []
        for project in response.json().get("results") or []:
            title = _clean(_pick(project, "project_title", "projectTitle"), limit=300)
            excerpt = _clean(_pick(project, "phr_text", "phrText", "terms"), limit=1600)
            if not title or not excerpt:
                continue
            investigators = []
            for pi in _pick(project, "principal_investigators", "principalInvestigators") or []:
                if isinstance(pi, dict):
                    name = _clean(_pick(pi, "full_name", "fullName"), limit=120)
                    if name:
                        investigators.append(name)
            project_num = _clean(_pick(project, "project_num", "projectNum"), limit=80)
            entries.append(
                {
                    "id": project_num or title,
                    "title": title,
                    "excerpt": excerpt,
                    "url": _clean(_pick(project, "project_detail_url", "projectDetailUrl"), limit=600),
                    "doi": None,
                    "year": _year(project),
                    "query": _clean(query, limit=240),
                    "source_type": "nih_reporter",
                    "evidence_type": "protocol",
                    "journal": "NIH RePORTER",
                    "authors": investigators,
                }
            )
            if len(entries) >= limit:
                break
        return entries
