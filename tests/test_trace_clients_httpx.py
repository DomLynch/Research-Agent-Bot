"""Tests for agent/trace_clients/_httpx.py — three httpx-backed backends.

Uses `httpx.MockTransport` for offline coverage; no real network. Live
smoke tests against CT.gov / ChEMBL / Europe PMC live in
`scripts/e2e_trace_clients_smoke.py` (opt-in, not run in CI).
"""
from __future__ import annotations

import httpx
import pytest

from agent.trace_clients._httpx import (
    HttpxDrugAliasClient,
    HttpxLiteratureClient,
    HttpxTrialRegistryClient,
)
from agent.trace_clients.protocols import TraceBackendError


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- HttpxTrialRegistryClient (CT.gov v2) --------------------------------


def test_httpx_trial_registry_happy_path_with_results() -> None:
    """A completed trial with hasResults=True maps to has_results=True
    + status='completed' + phase='PHASE3'."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert "NCT02308228" in str(request.url)
        return httpx.Response(200, json={
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT02308228",
                    "briefTitle": "MASTERS",
                },
                "statusModule": {
                    "overallStatus": "COMPLETED",
                    "primaryCompletionDateStruct": {"date": "2017-06-30"},
                },
                "designModule": {"phases": ["PHASE3"]},
            },
            "hasResults": True,
        })

    backend = HttpxTrialRegistryClient(client=_client(handler))
    rec = backend.get_trial("NCT02308228")
    assert rec is not None
    assert rec.trial_id == "NCT02308228"
    assert rec.status == "completed"
    assert rec.has_results is True
    assert rec.phase == "PHASE3"
    assert rec.primary_completion_date == "2017-06-30"
    assert rec.title == "MASTERS"


def test_httpx_trial_registry_recruiting_no_results() -> None:
    """A recruiting trial without hasResults → has_results=False
    + status='recruiting'. This is the planted-case-1 contradiction
    shape (TAME cited as published_results but registry says recruiting)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT04264897", "briefTitle": "TAME",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "primaryCompletionDateStruct": {"date": "2025-12-31"},
                },
                "designModule": {"phases": ["PHASE3"]},
            },
            "hasResults": False,
        })

    backend = HttpxTrialRegistryClient(client=_client(handler))
    rec = backend.get_trial("NCT04264897")
    assert rec is not None
    assert rec.status == "recruiting"
    assert rec.has_results is False


def test_httpx_trial_registry_returns_none_for_404() -> None:
    """Planted case 2: fabricated NCT → CT.gov returns 404 → backend
    returns None. None means 'record not found' — citation_trace flips
    that into trace_passed=False."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    backend = HttpxTrialRegistryClient(client=_client(handler))
    assert backend.get_trial("NCT99999999") is None


def test_httpx_trial_registry_raises_on_5xx() -> None:
    """5xx is a transport-level failure, not a 'record not found'.
    Raise so the orchestrator can surface the gap."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream busy")

    backend = HttpxTrialRegistryClient(client=_client(handler))
    with pytest.raises(TraceBackendError, match="503"):
        backend.get_trial("NCT04264897")


def test_httpx_trial_registry_raises_on_bad_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json {{")

    backend = HttpxTrialRegistryClient(client=_client(handler))
    with pytest.raises(TraceBackendError, match="non-JSON"):
        backend.get_trial("NCT04264897")


def test_httpx_trial_registry_skips_isrctn() -> None:
    """ISRCTN ids skip CT.gov entirely (different registry). The fixture
    backend still serves ISRCTN for the planted-failure regression."""
    backend = HttpxTrialRegistryClient(client=_client(
        # Handler should never be called; if it is, fail the test.
        lambda req: pytest.fail(f"unexpected HTTP call: {req.url}"),  # type: ignore[return-value]
    ))
    assert backend.get_trial("ISRCTN29932357") is None


def test_httpx_trial_registry_unknown_status_falls_back() -> None:
    """A status value outside the CT.gov enum we've seen → 'unknown',
    not crash. Future-proofs against CT.gov adding a new status."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "protocolSection": {
                "identificationModule": {"nctId": "NCT0", "briefTitle": "T"},
                "statusModule": {"overallStatus": "FROBNICATED"},
                "designModule": {},
            },
        })

    backend = HttpxTrialRegistryClient(client=_client(handler))
    rec = backend.get_trial("NCT0")
    assert rec is not None
    assert rec.status == "unknown"


def test_httpx_trial_registry_falls_back_to_results_section() -> None:
    """Older payload shape: no hasResults field but resultsSection present."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "protocolSection": {
                "identificationModule": {"nctId": "NCT0", "briefTitle": "T"},
                "statusModule": {"overallStatus": "COMPLETED"},
                "designModule": {},
            },
            "resultsSection": {"some": "data"},
        })

    backend = HttpxTrialRegistryClient(client=_client(handler))
    rec = backend.get_trial("NCT0")
    assert rec is not None
    assert rec.has_results is True


# --- HttpxDrugAliasClient (ChEMBL) ---------------------------------------


def test_httpx_drug_alias_happy_path_with_synonyms() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "molecules": [{
                "pref_name": "METFORMIN",
                "molecule_chembl_id": "CHEMBL1431",
                "molecule_synonyms": [
                    {"synonyms": "Glucophage"},
                    {"synonyms": "Biguanide"},
                ],
            }],
        })

    backend = HttpxDrugAliasClient(client=_client(handler))
    rec = backend.lookup("metformin")
    assert rec is not None
    assert rec.canonical_name == "METFORMIN"
    assert rec.chembl_id == "CHEMBL1431"
    assert "Glucophage" in rec.aliases
    assert "Biguanide" in rec.aliases


def test_httpx_drug_alias_returns_none_for_empty_results() -> None:
    """Planted case 4: ChEMBL returns 200 + empty molecules list →
    None. None is the drift signal."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"molecules": []})

    backend = HttpxDrugAliasClient(client=_client(handler))
    assert backend.lookup("Glufomin") is None


def test_httpx_drug_alias_returns_none_for_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    backend = HttpxDrugAliasClient(client=_client(handler))
    assert backend.lookup("anything") is None


def test_httpx_drug_alias_returns_none_for_blank_input() -> None:
    """Defensive: blank input → None without HTTP call. Avoids spending
    a request on a guaranteed-no-result query."""
    backend = HttpxDrugAliasClient(client=_client(
        lambda req: pytest.fail(f"unexpected HTTP call: {req.url}"),  # type: ignore[return-value]
    ))
    assert backend.lookup("   ") is None
    assert backend.lookup("") is None


def test_httpx_drug_alias_raises_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="ChEMBL down")

    backend = HttpxDrugAliasClient(client=_client(handler))
    with pytest.raises(TraceBackendError, match="500"):
        backend.lookup("metformin")


def test_httpx_drug_alias_handles_synonym_key_variants() -> None:
    """ChEMBL has used both 'synonyms' and 'synonym' as the inner key
    over time. Backend accepts either."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "molecules": [{
                "pref_name": "X",
                "molecule_chembl_id": "CHEMBL1",
                "molecule_synonyms": [
                    {"synonyms": "AliasViaPlural"},
                    {"synonym": "AliasViaSingular"},
                ],
            }],
        })

    backend = HttpxDrugAliasClient(client=_client(handler))
    rec = backend.lookup("X")
    assert rec is not None
    assert "AliasViaPlural" in rec.aliases
    assert "AliasViaSingular" in rec.aliases


# --- HttpxLiteratureClient (Europe PMC) ----------------------------------


def test_httpx_literature_doi_lookup() -> None:
    """A DOI starts with '10.' or contains '/' → query as DOI:..."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = request.url.params.get("query", "")
        return httpx.Response(200, json={
            "resultList": {"result": [{
                "doi": "10.1111/acel.13039",
                "title": "Aging study",
                "abstractText": "We studied aging.",
                "authorList": {
                    "author": [
                        {"fullName": "Smith J"},
                        {"firstName": "Jane", "lastName": "Doe"},
                    ],
                },
                "journalTitle": "Aging Cell",
                "pubYear": "2024",
            }]},
        })

    backend = HttpxLiteratureClient(client=_client(handler))
    rec = backend.fetch("10.1111/acel.13039")
    assert rec is not None
    assert rec.identifier == "10.1111/acel.13039"
    assert rec.title == "Aging study"
    assert rec.year == 2024
    assert "Smith J" in rec.authors
    assert "Jane Doe" in rec.authors
    assert captured["query"].startswith("DOI:")


def test_httpx_literature_pmid_lookup() -> None:
    """A bare-digit identifier → query as EXT_ID:... AND SRC:MED."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = request.url.params.get("query", "")
        return httpx.Response(200, json={
            "resultList": {"result": [{
                "pmid": "12345678", "title": "T", "abstractText": "A",
            }]},
        })

    backend = HttpxLiteratureClient(client=_client(handler))
    rec = backend.fetch("12345678")
    assert rec is not None
    assert "EXT_ID:12345678" in captured["query"]
    assert "SRC:MED" in captured["query"]


def test_httpx_literature_returns_none_for_empty_result_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"resultList": {"result": []}})

    backend = HttpxLiteratureClient(client=_client(handler))
    assert backend.fetch("10.1111/missing") is None


def test_httpx_literature_returns_none_for_blank_input() -> None:
    backend = HttpxLiteratureClient(client=_client(
        lambda req: pytest.fail(f"unexpected HTTP call: {req.url}"),  # type: ignore[return-value]
    ))
    assert backend.fetch("") is None
    assert backend.fetch("   ") is None


def test_httpx_literature_raises_on_4xx() -> None:
    """A 400 (malformed query) is a transport-level failure, not a
    'record not found'. Raise so the orchestrator can surface."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad query")

    backend = HttpxLiteratureClient(client=_client(handler))
    with pytest.raises(TraceBackendError, match="400"):
        backend.fetch("10.1/x")


def test_httpx_literature_handles_missing_optional_fields() -> None:
    """Records may lack journalTitle / pubYear / authorList — backend
    must coerce to None / empty rather than crash on KeyError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "resultList": {"result": [{
                "doi": "10.1/x", "title": "T", "abstractText": "A",
            }]},
        })

    backend = HttpxLiteratureClient(client=_client(handler))
    rec = backend.fetch("10.1/x")
    assert rec is not None
    assert rec.authors == ()
    assert rec.venue is None
    assert rec.year is None
