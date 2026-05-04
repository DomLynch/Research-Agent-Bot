"""ClinicalTrials.gov v2 adapter.

Endpoint: https://clinicaltrials.gov/api/v2/studies
Returns trial registry records. The `hasResults` flag distinguishes a
registered protocol from a posted-results study — bundle.py uses this to
assign role={published_results, registered_pending} downstream.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text, safe_get_json
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
        data = await safe_get_json(client, CTGOV_STUDIES_URL, params=params)
        if data is None:
            return []
        studies = data.get("studies", []) or []
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
        # 4000-char window keeps trial description intact for classification.
        abstract = clean_text(desc, limit=4000)
        if not nct or not title:
            return None
        # CT.gov registered-pending trials sometimes have empty briefSummary.
        if not abstract:
            abstract = title
        # When the trial has posted results, append the structured primary
        # outcome to the abstract so the LLM can cite the actual finding —
        # CT.gov briefSummary describes the trial DESIGN, not the result.
        # Without this, MILES / Justice frailty / similar registered-results
        # trials show up tagged 'published_results' but with design-only
        # text, so the LLM defaults to the only paper with rich result
        # phrasing (e.g. METFORAGING) and ignores CT.gov outcomes.
        has_results = bool(study.get("hasResults"))
        if has_results:
            outcome_summary = self._format_posted_outcome(study)
            if outcome_summary:
                abstract = f"{abstract}\n\nPosted outcomes: {outcome_summary}"[:5500]
        year = self._extract_year(protocol.get("statusModule") or {})
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
    def _format_posted_outcome(study: dict[str, Any]) -> str:
        """Build a one-line summary of the primary posted outcome.

        Pulls primary-type outcomes from resultsSection.outcomeMeasuresModule
        and reports group titles + values, plus p-value if present. Returns
        empty string when no usable outcome rows are posted.
        """
        results = study.get("resultsSection") or {}
        outcomes = ((results.get("outcomeMeasuresModule") or {})
                    .get("outcomeMeasures") or [])
        for outcome in outcomes:
            if clean_text(outcome.get("type"), limit=20).upper() != "PRIMARY":
                continue
            title = clean_text(outcome.get("title"), limit=160)
            timeframe = clean_text(outcome.get("timeFrame"), limit=80)
            groups = {
                clean_text(g.get("id"), limit=20): clean_text(g.get("title"), limit=80)
                for g in (outcome.get("groups") or [])
            }
            measure_lines: list[str] = []
            for klass in outcome.get("classes") or []:
                for cat in klass.get("categories") or []:
                    for m in (cat.get("measurements") or [])[:3]:
                        gid = clean_text(m.get("groupId"), limit=20)
                        val = clean_text(m.get("value"), limit=40)
                        spread = clean_text(m.get("spread"), limit=40)
                        label = groups.get(gid, gid)
                        if not val:
                            continue
                        measure_lines.append(
                            f"{label}={val}" + (f" (±{spread})" if spread else "")
                        )
                if measure_lines:
                    break
            if not measure_lines:
                continue
            analyses = outcome.get("analyses") or []
            p_value = clean_text(
                (analyses[0].get("pValue") if analyses else ""), limit=24,
            )
            parts = [title]
            if timeframe:
                parts.append(f"timeframe={timeframe}")
            parts.append("; ".join(measure_lines))
            if p_value:
                parts.append(f"p={p_value}")
            return clean_text(". ".join(p for p in parts if p), limit=600)
        return ""

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
