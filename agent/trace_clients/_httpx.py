"""HTTPX-backed trace clients — CT.gov v2 / ChEMBL / Europe PMC.

DESIGN-001 §7: citation-trace must work without MCP. These backends hit
public REST APIs directly via httpx (the runtime's only dep). The
`TRACE_BACKEND=http` selector in `__init__.py` wires them up.

Sync httpx, not async — the Protocol contract is sync (citation_trace
calls `client.get_trial(...)` etc. without `await`). Each backend takes
an optional `httpx.Client` so tests can inject a `MockTransport` for
offline coverage; in production callers create one shared client and
pass it to all three backends to avoid per-call connection setup.

Failure semantics (matches the fixture backend's contract):
  - 404 / empty result → return None (record not found, legitimate
    trace-failure signal)
  - 5xx / transport error / bad JSON → raise TraceBackendError so the
    orchestrator can decide whether to retry or surface the gap

No retry / no rate-limit logic: the realistic per-claim trace volume
is ~5-10 calls and the public APIs are generous. Add retry only if a
real run shows transient failures.
"""
from __future__ import annotations

from collections.abc import Mapping

import httpx

from agent.trace_clients.protocols import (
    CompoundRecord,
    LiteratureRecord,
    TraceBackendError,
    TrialRecord,
    TrialStatus,
)

__all__ = [
    "HttpxTrialRegistryClient",
    "HttpxDrugAliasClient",
    "HttpxLiteratureClient",
]

_CT_BASE = "https://clinicaltrials.gov/api/v2"
_CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"
_EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# CT.gov v2 status enum → our TrialStatus literal. Anything outside
# this set falls through to "unknown" so a new value upstream doesn't
# crash the pipeline.
_CT_STATUS_MAP: Mapping[str, TrialStatus] = {
    "RECRUITING": "recruiting",
    "ACTIVE_NOT_RECRUITING": "active_not_recruiting",
    "COMPLETED": "completed",
    "TERMINATED": "terminated",
    "WITHDRAWN": "withdrawn",
    "SUSPENDED": "suspended",
}


def _normalize_status(raw: str | None) -> TrialStatus:
    if not raw:
        return "unknown"
    return _CT_STATUS_MAP.get(raw.strip().upper(), "unknown")


def _get_json(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    backend: str,
    target: str,
) -> dict | None:
    """Single GET → JSON, with consistent error mapping across backends.

    None on 404 (record absent). Raises TraceBackendError on transport
    error, 5xx, other 4xx, or bad JSON.
    """
    try:
        resp = client.get(
            url, params=params, headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise TraceBackendError(
            f"{backend} GET failed for {target!r}: {type(exc).__name__}: {exc}"
        ) from exc
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise TraceBackendError(
            f"{backend} {resp.status_code} for {target!r}: "
            f"{resp.text[:200]!r}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise TraceBackendError(
            f"{backend} returned non-JSON for {target!r}: {exc}"
        ) from exc


# --- CT.gov ---------------------------------------------------------------


class HttpxTrialRegistryClient:
    """Backend for ClinicalTrials.gov API v2.

    NCT IDs only — ISRCTN returns None (their public API has a different
    shape and isn't worth the divergence cost for v0; the fixture backend
    still serves ISRCTN for the planted-failure regression tests).
    """

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = _CT_BASE,
        timeout: float = 15.0,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._base = base_url.rstrip("/")
        self._owns_client = client is None

    def get_trial(self, trial_id: str) -> TrialRecord | None:
        tid = trial_id.strip().upper()
        if not tid.startswith("NCT"):
            return None
        url = f"{self._base}/studies/{tid}"
        data = _get_json(self._client, url, backend="CT.gov", target=tid)
        if data is None:
            return None
        proto = data.get("protocolSection") or {}
        ident = proto.get("identificationModule") or {}
        status_mod = proto.get("statusModule") or {}
        design = proto.get("designModule") or {}
        completion = (status_mod.get("primaryCompletionDateStruct") or {}).get("date")
        phases = design.get("phases") or []
        # `hasResults` is the v2 top-level summary flag; fall back to the
        # presence of resultsSection for older payloads that omit it.
        has_results = bool(
            data.get("hasResults") or data.get("resultsSection"),
        )
        return TrialRecord(
            trial_id=ident.get("nctId", tid),
            title=ident.get("briefTitle", "") or "",
            status=_normalize_status(status_mod.get("overallStatus")),
            has_results=has_results,
            phase=("/".join(phases) if phases else None),
            primary_completion_date=completion,
        )


# --- ChEMBL ---------------------------------------------------------------


class HttpxDrugAliasClient:
    """Backend for the EMBL-EBI ChEMBL REST API.

    Resolves a drug name / alias to a canonical compound + ChEMBL ID +
    synonym list. Used by `citation_trace.trace_alias_match` to flag
    drift (planted case 4 — 'Glufomin' returns no match).
    """

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = _CHEMBL_BASE,
        timeout: float = 15.0,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._base = base_url.rstrip("/")
        self._owns_client = client is None

    def lookup(self, name_or_alias: str) -> CompoundRecord | None:
        candidate = name_or_alias.strip()
        if not candidate:
            return None
        url = f"{self._base}/molecule/search.json"
        data = _get_json(
            self._client, url,
            params={"q": candidate}, backend="ChEMBL", target=candidate,
        )
        if data is None:
            return None
        molecules = data.get("molecules") or []
        if not molecules:
            return None
        mol = molecules[0]
        synonyms_raw = mol.get("molecule_synonyms") or []
        aliases = tuple(
            s.get("synonyms") or s.get("synonym")  # API has used both keys
            for s in synonyms_raw
            if (s.get("synonyms") or s.get("synonym"))
        )
        return CompoundRecord(
            canonical_name=mol.get("pref_name") or candidate,
            chembl_id=mol.get("molecule_chembl_id"),
            aliases=aliases,
            drug_class=None,  # not in /molecule; would need a 2nd call
        )


# --- Europe PMC -----------------------------------------------------------


class HttpxLiteratureClient:
    """Backend for the EMBL-EBI Europe PMC search API.

    Resolves a DOI or PMID to title + abstract + authors + venue. Used
    by `citation_trace` to verify a cite's bibliographic identity.
    """

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = _EPMC_BASE,
        timeout: float = 15.0,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._base = base_url.rstrip("/")
        self._owns_client = client is None

    def fetch(self, doi_or_pmid: str) -> LiteratureRecord | None:
        ident = doi_or_pmid.strip()
        if not ident:
            return None
        # DOIs always start with "10." and contain a slash; PMIDs are bare digits.
        if ident.lower().startswith("10.") or "/" in ident:
            query = f"DOI:{ident}"
        else:
            query = f"EXT_ID:{ident} AND SRC:MED"
        url = f"{self._base}/search"
        data = _get_json(
            self._client, url,
            params={"query": query, "format": "json", "resultType": "core"},
            backend="EuropePMC", target=ident,
        )
        if data is None:
            return None
        result_list = (data.get("resultList") or {}).get("result") or []
        if not result_list:
            return None
        rec = result_list[0]
        authors_raw = (rec.get("authorList") or {}).get("author") or []
        authors: list[str] = []
        for au in authors_raw:
            name = au.get("fullName")
            if not name:
                first = (au.get("firstName") or "").strip()
                last = (au.get("lastName") or "").strip()
                name = f"{first} {last}".strip()
            if name:
                authors.append(name)
        year: int | None = None
        pub_year = rec.get("pubYear")
        if pub_year:
            try:
                year = int(pub_year)
            except (TypeError, ValueError):
                year = None
        return LiteratureRecord(
            identifier=rec.get("doi") or rec.get("pmid") or ident,
            title=rec.get("title") or "",
            abstract=rec.get("abstractText") or "",
            authors=tuple(authors),
            venue=rec.get("journalTitle"),
            year=year,
        )
