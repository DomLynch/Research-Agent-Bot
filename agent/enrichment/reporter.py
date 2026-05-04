"""NIH RePORTER enrichment — grant/funding metadata by topic.

Endpoint: POST https://api.reporter.nih.gov/v2/projects/search
No auth. JSON criteria payload. ~1 req/s polite limit.

Per NIH's RePORTER API docs (api.reporter.nih.gov, fetched 2026-05-04):
"It is recommended that users post no more than one URL request per
second and limit large jobs to either weekends or weekdays between
9:00 PM and 5:00 AM EST."

Use case for Researka: feed the RIS-compliant Funding & Conflicts
appendix. For each topic synthesis, surface the active NIH grants on
that topic so the human auditor can spot funding-source patterns
(e.g. "all 12 RCTs on this drug were funded by the same pharma R01s").
This isn't corpus evidence — it's the audit/disclosure layer.

Like iCite + RxNorm, this lives in agent/enrichment/, not
agent/sources/, because it returns grants metadata not papers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

_REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"


@dataclass(frozen=True, slots=True)
class GrantRecord:
    """Compact summary of one NIH grant project."""
    project_num: str
    title: str
    fiscal_year: int | None
    award_amount: int | None
    contact_pi_name: str
    organization: str
    abstract: str
    activity_code: str
    agencies: tuple[str, ...] = field(default_factory=tuple)


class ReporterClient:
    """Search NIH grants by topic + fiscal-year window.

    Usage:
        client = ReporterClient()
        async with httpx.AsyncClient() as h:
            grants = await client.search(
                h, "aspirin aging", fiscal_years=[2024, 2025], limit=20,
            )
    """

    name = "reporter"

    async def search(
        self,
        client: httpx.AsyncClient,
        topic: str,
        *,
        fiscal_years: list[int] | None = None,
        agencies: list[str] | None = None,
        limit: int = 25,
    ) -> list[GrantRecord]:
        criteria: dict[str, Any] = {
            "advanced_text_search": {
                "operator": "and",
                "search_field": "projecttitle,terms,abstracttext",
                "search_text": topic[:240],
            },
        }
        if fiscal_years:
            criteria["fiscal_years"] = fiscal_years
        if agencies:
            criteria["agencies"] = agencies
        payload = {
            "criteria": criteria,
            "limit": max(1, min(limit, 100)),
            "offset": 0,
        }
        try:
            response = await client.post(
                _REPORTER_URL, json=payload, timeout=30.0,
            )
            if response.status_code != 200:
                return []
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        return [
            r for r in (
                self._parse(rec) for rec in data.get("results", [])
            )
            if r
        ]

    @staticmethod
    def _parse(record: dict[str, Any]) -> GrantRecord | None:
        title = (record.get("project_title") or "").strip()
        proj_num = (record.get("project_num") or "").strip()
        if not title or not proj_num:
            return None
        # Pi name is in contact_pi_name OR principal_investigators[0]
        pi_name = (record.get("contact_pi_name") or "").strip()
        if not pi_name:
            pis = record.get("principal_investigators") or []
            if pis:
                first = pis[0]
                pi_name = (
                    f"{first.get('first_name','')} "
                    f"{first.get('last_name','')}"
                ).strip()
        org_obj = record.get("organization") or {}
        org_name = (org_obj.get("org_name") or "").strip()
        # Agencies live in agency_ic_admin.code or agency_ic_fundings
        agencies_raw = []
        admin = record.get("agency_ic_admin") or {}
        if admin.get("code"):
            agencies_raw.append(str(admin["code"]))
        for a in (record.get("agency_ic_fundings") or []):
            if a.get("code"):
                agencies_raw.append(str(a["code"]))
        return GrantRecord(
            project_num=proj_num,
            title=title[:300],
            fiscal_year=_safe_int(record.get("fiscal_year")),
            award_amount=_safe_int(record.get("award_amount")),
            contact_pi_name=pi_name[:200],
            organization=org_name[:200],
            abstract=(record.get("abstract_text") or "")[:4000],
            activity_code=(record.get("activity_code") or "")[:8],
            agencies=tuple(_unique_first(agencies_raw))[:10],
        )


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _unique_first(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out
