"""HTTPX-backed trace clients — CT.gov v2 / ISRCTN / ChEMBL / Europe PMC.

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

Day 10.14 — `HttpxTrialRegistryClient` now also handles ISRCTN IDs
(UK trial registry). Empirical: MET-PREVENT (ISRCTN29932357) was
spuriously failing nct_exists in the canonical-corpus benchmark
because the v0 client only knew CT.gov.

ISRCTN parser: deliberately uses regex extraction (not xml.etree)
to eliminate XXE / billion-laughs / DTD-injection attack surface on
the third-party registry response. The 7 fields we need are simple
top-level tags inside `<trial><main>`; regex is sufficient and safer
than stdlib XML parsing.
"""
from __future__ import annotations

import re
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
_ISRCTN_BASE = "https://www.isrctn.com/api/query/format/who"
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


# Day 10.14 — ISRCTN uses prose status labels. Map them to our
# TrialStatus literal. Match is on lowercase, whitespace-collapsed.
# Anything not in this map falls through to "unknown" (safe default;
# never crashes the pipeline on a status string the registry adds).
_ISRCTN_STATUS_MAP: Mapping[str, TrialStatus] = {
    "recruiting": "recruiting",
    "ongoing": "active_not_recruiting",
    "no longer recruiting": "active_not_recruiting",
    "completed": "completed",
    "closed": "completed",
    "stopped": "terminated",
    "terminated": "terminated",
    "suspended": "suspended",
    "withdrawn": "withdrawn",
    "in setup": "unknown",
    "in setup, pending funding": "unknown",
    "pending": "unknown",
}

# Day 10.14 — ISRCTN phase strings that mean "no phase declared". Map
# to None so downstream code doesn't carry a misleading literal.
_ISRCTN_NULL_PHASE = frozenset({"not specified", "not applicable", "n/a"})

# Day 10.14 — regex extractors for ISRCTN response fields. We extract
# only the 7 top-level tags we need and never invoke an XML parser, so
# the response is immune to DTD / external-entity / billion-laughs
# attacks regardless of what the registry returns.
_ISRCTN_TRIAL_BLOCK_RE = re.compile(
    r"<trial\b[^>]*>(.*?)</trial>",
    re.IGNORECASE | re.DOTALL,
)
_ISRCTN_MAIN_BLOCK_RE = re.compile(
    r"<main\b[^>]*>(.*?)</main>",
    re.IGNORECASE | re.DOTALL,
)


def _isrctn_field(block: str, tag: str) -> str:
    """Extract `<tag>...</tag>` content from an ISRCTN block, or empty
    string when missing. Whitespace-trimmed; tag-internal HTML/XML is
    NOT processed (matches the regex literally between tag boundaries).
    """
    pattern = rf"<{tag}\b[^>]*>(.*?)</{tag}>"
    m = re.search(pattern, block, re.IGNORECASE | re.DOTALL)
    if m is None:
        return ""
    return m.group(1).strip()


def _normalize_status(raw: str | None) -> TrialStatus:
    if not raw:
        return "unknown"
    return _CT_STATUS_MAP.get(raw.strip().upper(), "unknown")


def _normalize_isrctn_status(raw: str | None) -> TrialStatus:
    if not raw:
        return "unknown"
    key = " ".join(raw.split()).lower()
    return _ISRCTN_STATUS_MAP.get(key, "unknown")


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
    """Backend for ClinicalTrials.gov v2 + ISRCTN registries.

    Routes by trial-ID prefix:
      - NCT*    → ClinicalTrials.gov API v2 (JSON)
      - ISRCTN* → ISRCTN registry WHO-format API (XML)

    Day 10.14 added ISRCTN handling. Empirical: MET-PREVENT
    (ISRCTN29932357) was spuriously failing the nct_exists trace
    because the v0 client returned None for any non-NCT id.
    """

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = _CT_BASE,
        isrctn_base_url: str = _ISRCTN_BASE,
        timeout: float = 15.0,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._base = base_url.rstrip("/")
        self._isrctn_base = isrctn_base_url
        self._owns_client = client is None

    def get_trial(self, trial_id: str) -> TrialRecord | None:
        tid = trial_id.strip().upper()
        if tid.startswith("NCT"):
            return self._get_ctgov_trial(tid)
        if tid.startswith("ISRCTN"):
            return self._get_isrctn_trial(tid)
        return None

    def _get_ctgov_trial(self, tid: str) -> TrialRecord | None:
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

    def _get_isrctn_trial(self, tid: str) -> TrialRecord | None:
        """Fetch from the ISRCTN WHO-format API (XML response).

        Parser: regex-based field extraction (not xml.etree) so the
        third-party response cannot trigger XXE / billion-laughs /
        DTD-injection attacks. The 7 fields we need are simple top-
        level tags inside `<trial><main>`; regex is sufficient and
        keeps the runtime dep set to httpx-only per AGENTS.md.

        Multi-trial responses: the WHO `q=` parameter is a keyword
        search, not exact-id match. If the registry returns multiple
        `<trial>` blocks, we select the one whose `<trial_id>` text
        equals `tid` (the requested id). If none match, return None
        rather than risk binding an unrelated trial to the requested
        id (Day 10.14 reviewer-found precision concern).

        `has_results=True` requires a populated `<results_url_link>` —
        the `<results_date_completed>` field can be set to an
        anticipated date for trials that have ended enrollment but
        not yet posted results, so it's not a reliable signal alone.
        """
        try:
            resp = self._client.get(
                self._isrctn_base,
                params={"q": tid},
                headers={"Accept": "application/xml"},
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            raise TraceBackendError(
                f"ISRCTN GET failed for {tid!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise TraceBackendError(
                f"ISRCTN {resp.status_code} for {tid!r}: "
                f"{resp.text[:200]!r}"
            )
        body = resp.text or ""
        # Find the `<main>` block of the trial whose `<trial_id>`
        # matches `tid`. Empty result-set returns None.
        target_main: str | None = None
        for trial_block in _ISRCTN_TRIAL_BLOCK_RE.finditer(body):
            block_text = trial_block.group(1)
            main_match = _ISRCTN_MAIN_BLOCK_RE.search(block_text)
            if main_match is None:
                continue
            main_block = main_match.group(1)
            if _isrctn_field(main_block, "trial_id").upper() == tid:
                target_main = main_block
                break
        if target_main is None:
            return None
        title = (
            _isrctn_field(target_main, "scientific_title")
            or _isrctn_field(target_main, "public_title")
        )
        status_raw = _isrctn_field(target_main, "recruitment_status")
        results_url = _isrctn_field(target_main, "results_url_link")
        has_results = bool(results_url)
        completion = (
            _isrctn_field(target_main, "results_date_completed")
            or _isrctn_field(target_main, "date_enrolment")
            or None
        )
        phase_raw = _isrctn_field(target_main, "phase")
        phase = (
            None
            if phase_raw.lower() in _ISRCTN_NULL_PHASE
            else (phase_raw or None)
        )
        return TrialRecord(
            trial_id=_isrctn_field(target_main, "trial_id") or tid,
            title=title,
            status=_normalize_isrctn_status(status_raw),
            has_results=has_results,
            phase=phase,
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
