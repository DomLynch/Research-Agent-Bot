"""ClinicalTrials.gov v2 adapter.

Endpoint: https://clinicaltrials.gov/api/v2/studies
Returns trial registry records. The `hasResults` flag distinguishes a
registered protocol from a posted-results study — bundle.py uses this to
assign role={published_results, registered_pending} downstream.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text
from agent.types import RawHit

CTGOV_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


class ClinicalTrialsClient:
    name = "clinicaltrials"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "query.term": clean_text(query, limit=240),
            "pageSize": str(max(1, min(limit, 25))),
            "format": "json",
        }
        response = await client.get(CTGOV_STUDIES_URL, params=params)
        response.raise_for_status()
        studies = response.json().get("studies", []) or []
        return [hit for hit in (self._parse_study(s, query=query) for s in studies) if hit]

    def _parse_study(self, study: dict[str, Any], *, query: str) -> RawHit | None:
        protocol = study.get("protocolSection") or {}
        ident = protocol.get("identificationModule") or {}
        nct = clean_text(ident.get("nctId"))
        title = clean_text(
            ident.get("briefTitle") or ident.get("officialTitle"),
            limit=300,
        )
        desc = (protocol.get("descriptionModule") or {}).get("briefSummary")
        abstract = clean_text(desc)
        if not nct or not title:
            return None
        # CT.gov registered-pending trials sometimes have empty briefSummary.
        # Drop them only when we'd lose ALL signal — fall back to the title
        # so bundle.py can still classify them as registered_pending.
        if not abstract:
            abstract = title
        year = self._extract_year(protocol.get("statusModule") or {})
        has_results = bool(study.get("hasResults"))
        design = (protocol.get("designModule") or {}).get("studyType") or ""
        return RawHit(
            source="clinicaltrials",
            title=title,
            abstract=abstract,
            year=year,
            url=f"https://clinicaltrials.gov/study/{nct}",
            nct=nct,
            venue=None,
            raw={
                "query": clean_text(query, limit=240),
                "has_results": has_results,
                "study_type": clean_text(design, limit=40),
            },
        )

    @staticmethod
    def _extract_year(status: dict[str, Any]) -> int | None:
        for key in (
            "primaryCompletionDateStruct",
            "completionDateStruct",
            "startDateStruct",
            "studyFirstPostDateStruct",
        ):
            date_str = (status.get(key) or {}).get("date", "")
            if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
                return int(date_str[:4])
        return None
