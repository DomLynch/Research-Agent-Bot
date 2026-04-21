"""Tests for ClinicalTrials.gov source client (Step 10)."""

import json

import httpx

from agent.sources.clinicaltrials import (
    ClinicalTrialsClient,
    _extract_nct_id,
    _extract_title,
    _extract_year,
    _extract_excerpt,
    _is_interventional,
)


def _study(
    nct_id: str = "NCT00000001",
    title: str = "A Study of Rapamycin in Aging",
    summary: str = "This trial evaluates rapamycin for longevity.",
    year: int = 2024,
    study_type: str = "INTERVENTIONAL",
) -> dict:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id, "briefTitle": title},
            "descriptionModule": {"briefSummary": summary},
            "statusModule": {"primaryCompletionDateStruct": {"date": f"{year}-06-15"}},
            "designModule": {"studyType": study_type},
        }
    }


def _mock_response(studies: list[dict] | None = None) -> httpx.Response:
    if studies is None:
        studies = [_study()]
    body = json.dumps({"studies": studies}).encode()
    return httpx.Response(200, content=body, headers={"content-type": "application/json"})


# --- Extractors ---


class TestExtractors:
    def test_extract_nct_id(self):
        assert _extract_nct_id(_study()) == "NCT00000001"

    def test_extract_nct_id_missing(self):
        assert _extract_nct_id({}) == ""

    def test_extract_title(self):
        assert _extract_title(_study()) == "A Study of Rapamycin in Aging"

    def test_extract_title_uses_official(self):
        s = _study()
        del s["protocolSection"]["identificationModule"]["briefTitle"]
        s["protocolSection"]["identificationModule"]["officialTitle"] = "Official Title"
        assert _extract_title(s) == "Official Title"

    def test_extract_year(self):
        assert _extract_year(_study(year=2023)) == 2023

    def test_extract_year_from_start_date(self):
        s = _study()
        del s["protocolSection"]["statusModule"]["primaryCompletionDateStruct"]
        s["protocolSection"]["statusModule"]["startDateStruct"] = {"date": "2022-01-01"}
        assert _extract_year(s) == 2022

    def test_extract_year_missing(self):
        s = _study()
        del s["protocolSection"]["statusModule"]["primaryCompletionDateStruct"]
        assert _extract_year(s) is None

    def test_extract_excerpt(self):
        assert "rapamycin" in _extract_excerpt(_study())

    def test_extract_excerpt_missing(self):
        assert _extract_excerpt({}) == ""

    def test_is_interventional(self):
        assert _is_interventional(_study(study_type="INTERVENTIONAL")) == "interventional"

    def test_is_observational(self):
        assert _is_interventional(_study(study_type="OBSERVATIONAL")) == "observational"

    def test_is_observational_when_missing(self):
        assert _is_interventional({}) == "observational"


# --- Client.search ---


class TestClinicalTrialsClient:
    def test_search_returns_entries(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response([_study(), _study(nct_id="NCT00000002", title="Metformin and Aging")])

        client = ClinicalTrialsClient(transport=httpx.MockTransport(handler))
        results = client.search("rapamycin aging", limit=5)
        assert len(results) == 2
        assert results[0]["id"] == "NCT00000001"
        assert results[0]["source_type"] == "clinicaltrials"
        assert results[0]["url"] == "https://clinicaltrials.gov/study/NCT00000001"
        assert results[0]["doi"] is None
        assert results[0]["journal"] is None

    def test_search_skips_incomplete(self):
        def handler(request: httpx.Request) -> httpx.Response:
            bad = {"protocolSection": {"identificationModule": {"nctId": "NCT999"}}}
            return _mock_response([_study(), bad])

        client = ClinicalTrialsClient(transport=httpx.MockTransport(handler))
        results = client.search("test", limit=5)
        assert len(results) == 1

    def test_search_respects_limit(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response([_study(nct_id=f"NCT{i:08d}") for i in range(10)])

        client = ClinicalTrialsClient(transport=httpx.MockTransport(handler))
        results = client.search("test", limit=3)
        assert len(results) == 3

    def test_search_empty_results(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response([])

        client = ClinicalTrialsClient(transport=httpx.MockTransport(handler))
        results = client.search("nonexistent", limit=5)
        assert len(results) == 0

    def test_search_evidence_type_is_design(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response([_study(study_type="OBSERVATIONAL")])

        client = ClinicalTrialsClient(transport=httpx.MockTransport(handler))
        results = client.search("test", limit=5)
        assert results[0]["evidence_type"] == "observational"
