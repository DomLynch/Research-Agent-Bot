"""NIH iCite enrichment — citation impact metrics per PMID.

Endpoint: https://icite.od.nih.gov/api/pubs?pmids=<csv>
No auth required. Up to 1000 PMIDs per request. JSON response.

Per the iCite docs (icite.od.nih.gov/api, fetched 2026-05-04), the
response contains the field-normalized Relative Citation Ratio (RCR),
NIH percentile, raw citation count, and the human/animal/clinical flags.
This is the right ranking signal for biomedical work — raw citation
count overweights large-field papers (everyone in oncology cites
everyone), while RCR normalizes by co-citation network.

Used post-corpus to tag each paper with its impact score, feeding into
ranking + the publication appendix's "evidence strength" disclosure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class CitationMetrics:
    """Compact, slottable summary of one paper's iCite metrics."""
    pmid: str
    rcr: float | None              # Relative Citation Ratio
    nih_percentile: float | None    # 0-100; higher = more cited
    citation_count: int | None
    expected_per_year: float | None
    is_clinical: bool
    is_research_article: bool
    year: int | None


_ICITE_URL = "https://icite.od.nih.gov/api/pubs"


class ICiteClient:
    """Batch-fetch citation metrics for a list of PMIDs.

    Usage:
        client = ICiteClient()
        async with httpx.AsyncClient() as h:
            metrics = await client.fetch(h, ["30566884", "29320655"])
    """

    name = "icite"

    async def fetch(
        self,
        client: httpx.AsyncClient,
        pmids: list[str] | tuple[str, ...],
        *,
        batch_size: int = 1000,
    ) -> dict[str, CitationMetrics]:
        """Returns {pmid: CitationMetrics} for every PMID in the input
        that iCite knows about. Missing PMIDs are silently dropped.

        Splits into batches of `batch_size` (max 1000 per docs)."""
        out: dict[str, CitationMetrics] = {}
        # Normalize, dedupe, drop empties.
        cleaned = [p.strip() for p in pmids if p and p.strip()]
        seen: set[str] = set()
        unique_pmids: list[str] = []
        for p in cleaned:
            if p not in seen:
                seen.add(p)
                unique_pmids.append(p)
        for i in range(0, len(unique_pmids), batch_size):
            batch = unique_pmids[i:i + batch_size]
            params = {"pmids": ",".join(batch)}
            try:
                response = await client.get(
                    _ICITE_URL, params=params, timeout=30.0,
                )
                if response.status_code != 200:
                    continue
                data = response.json().get("data", [])
            except (httpx.HTTPError, ValueError):
                continue
            for record in data:
                metrics = self._parse(record)
                if metrics:
                    out[metrics.pmid] = metrics
        return out

    @staticmethod
    def _parse(record: dict[str, Any]) -> CitationMetrics | None:
        pmid = record.get("pmid")
        if pmid is None:
            return None
        return CitationMetrics(
            pmid=str(pmid),
            rcr=_safe_float(record.get("relative_citation_ratio")),
            nih_percentile=_safe_float(record.get("nih_percentile")),
            citation_count=_safe_int(record.get("citation_count")),
            expected_per_year=_safe_float(
                record.get("expected_citations_per_year"),
            ),
            is_clinical=bool(record.get("is_clinical", False)),
            is_research_article=bool(
                record.get("is_research_article", False),
            ),
            year=_safe_int(record.get("year")),
        )


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
