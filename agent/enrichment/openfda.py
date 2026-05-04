"""openFDA drug-adverse-event enrichment (FAERS).

Endpoint: https://api.fda.gov/drug/event.json

Free, no API key required for low-volume use (~240 requests/minute
unauthenticated, per open.fda.gov/apis/authentication; an optional
free key bumps quota and is recommended for production scale).

Use case for Researka — drug-topic safety provenance:
  - top_reactions("aspirin") returns the top-N MedDRA-coded adverse
    reactions reported in FAERS, with report counts. Feeds the
    safety_tolerability + bleeding_risk evidence slots in topic
    packs directly from regulatory data, not literature.
  - recent_reports() returns recent report metadata (date, serious
    flag, primary source) for the drug — useful for audit-layer
    "is this drug still raising late safety signals?" checks.

Data spans 2004→present, sourced from the FDA Adverse Event Reporting
System (FAERS), updated quarterly. Critical caveat: FAERS reports are
voluntary and unstructured at submission; counts reflect
report-volume, not population incidence. Useful as a relative-rank
signal across reactions for one drug, NOT as a denominator-anchored
risk estimate.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

_FAERS_URL = "https://api.fda.gov/drug/event.json"


@dataclass(frozen=True, slots=True)
class AdverseReactionCount:
    """One row of top-reactions aggregation."""
    reaction: str       # MedDRA-coded preferred term
    count: int          # number of FAERS reports mentioning this reaction


@dataclass(frozen=True, slots=True)
class AdverseReport:
    """One FAERS adverse-event report (compact)."""
    receive_date: str          # YYYYMMDD
    serious: bool              # any serious-outcome flag set
    primary_source_country: str
    reactions: tuple[str, ...] = field(default_factory=tuple)


class OpenFDAClient:
    """Drug adverse-event lookups via FAERS. Two methods:
    top_reactions() for safety-axis ranking, recent_reports() for
    individual report provenance.

    Usage:
        client = OpenFDAClient()
        async with httpx.AsyncClient() as h:
            top = await client.top_reactions(h, "aspirin", limit=10)
            print([(r.reaction, r.count) for r in top])
    """

    name = "openfda"

    def _params_with_key(self, params: dict[str, str]) -> dict[str, str]:
        """Add api_key query param if OPENFDA_API_KEY is set
        (raises rate limit, optional)."""
        key = os.environ.get("OPENFDA_API_KEY")
        if key:
            params = {**params, "api_key": key}
        return params

    async def top_reactions(
        self,
        client: httpx.AsyncClient,
        drug_name: str,
        *,
        limit: int = 10,
    ) -> list[AdverseReactionCount]:
        """Returns top-N adverse reactions by report count for a given
        drug, using FAERS' count-aggregation endpoint. Searches both
        brand_name + generic_name OR'd together to catch the full
        report set regardless of how a submitter wrote the drug name."""
        # Generic name is the canonical FAERS field; brand-name reports
        # are also indexed under generic_name when the FDA's mapping
        # resolves them. Caller passes the generic ("aspirin"), not a
        # brand. Single-field query keeps URL-encoding straightforward.
        search = f"patient.drug.openfda.generic_name:{drug_name}"
        params = self._params_with_key({
            "search": search,
            "count": "patient.reaction.reactionmeddrapt.exact",
            "limit": str(max(1, min(limit, 100))),
        })
        try:
            response = await client.get(
                _FAERS_URL, params=params, timeout=30.0,
            )
        except httpx.HTTPError:
            return []
        if response.status_code in (401, 403, 429):
            return []
        if response.status_code >= 500 or response.status_code != 200:
            return []
        try:
            data = response.json()
        except ValueError:
            return []
        out: list[AdverseReactionCount] = []
        for record in data.get("results", []):
            term = (record.get("term") or "").strip()
            count = record.get("count")
            if not term or count is None:
                continue
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                continue
            out.append(AdverseReactionCount(
                reaction=term[:200], count=count_int,
            ))
        return out

    async def recent_reports(
        self,
        client: httpx.AsyncClient,
        drug_name: str,
        *,
        limit: int = 10,
    ) -> list[AdverseReport]:
        """Returns recent FAERS reports for a drug, sorted by receive
        date desc. For audit-layer usage: confirms a drug still has
        recent safety signals (or doesn't, which is itself a signal).

        See top_reactions docstring re: generic-name-only search choice."""
        search = f"patient.drug.openfda.generic_name:{drug_name}"
        params = self._params_with_key({
            "search": search,
            "sort": "receivedate:desc",
            "limit": str(max(1, min(limit, 100))),
        })
        try:
            response = await client.get(
                _FAERS_URL, params=params, timeout=30.0,
            )
        except httpx.HTTPError:
            return []
        if response.status_code in (401, 403, 429):
            return []
        if response.status_code >= 500 or response.status_code != 200:
            return []
        try:
            data = response.json()
        except ValueError:
            return []
        out: list[AdverseReport] = []
        for record in data.get("results", []):
            out.append(self._parse_report(record))
        return out

    @staticmethod
    def _parse_report(record: dict[str, Any]) -> AdverseReport:
        receive_date = (record.get("receivedate") or "")[:8]
        serious = bool(int(record.get("serious", 0) or 0))
        primary = record.get("primarysource") or {}
        country = (primary.get("reportercountry") or "").strip()[:8]
        reactions: list[str] = []
        for r in (record.get("patient", {}).get("reaction", []) or []):
            term = (r.get("reactionmeddrapt") or "").strip()
            if term:
                reactions.append(term[:200])
        return AdverseReport(
            receive_date=receive_date,
            serious=serious,
            primary_source_country=country,
            reactions=tuple(reactions[:25]),
        )
