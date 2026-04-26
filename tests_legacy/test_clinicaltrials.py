"""Tests for ClinicalTrials.gov source client (Step 10)."""

import json

import httpx

from agent.sources.clinicaltrials import (
    ClinicalTrialsClient,
    _extract_nct_id,
    _extract_title,
    _extract_year,
    _extract_excerpt,
    _has_results,
    _is_interventional,
    _extract_results_extraction,
)


def _study(
    nct_id: str = "NCT00000001",
    title: str = "A Study of Rapamycin in Aging",
    summary: str = "This trial evaluates rapamycin for longevity.",
    year: int = 2024,
    study_type: str = "INTERVENTIONAL",
    has_results: bool = False,
) -> dict:
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id, "briefTitle": title},
            "descriptionModule": {"briefSummary": summary},
            "statusModule": {"primaryCompletionDateStruct": {"date": f"{year}-06-15"}},
            "designModule": {"studyType": study_type},
            "eligibilityModule": {"eligibilityCriteria": "Adults aged 65 and older with pre-diabetes."},
        }
    }
    if has_results:
        study["hasResults"] = True
        study["resultsSection"] = {
            "outcomeMeasuresModule": {
                "outcomeMeasures": [
                    {
                        "type": "PRIMARY",
                        "title": "Frailty Index",
                        "reportingStatus": "POSTED",
                        "paramType": "MEAN",
                        "unitOfMeasure": "Index score",
                        "timeFrame": "2 years",
                        "groups": [
                            {"id": "OG000", "title": "Metformin"},
                            {"id": "OG001", "title": "Placebo"},
                        ],
                        "denoms": [
                            {
                                "units": "Participants",
                                "counts": [
                                    {"groupId": "OG000", "value": "58"},
                                    {"groupId": "OG001", "value": "67"},
                                ],
                            }
                        ],
                        "classes": [
                            {
                                "categories": [
                                    {
                                        "measurements": [
                                            {"groupId": "OG000", "value": "-0.0002", "spread": "0.0002"},
                                            {"groupId": "OG001", "value": "0.0002", "spread": "0.0002"},
                                        ]
                                    }
                                ]
                            }
                        ],
                        "analyses": [{"pValue": "0.04"}],
                    }
                ]
            }
        }
    return study


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

    def test_has_results_flag(self):
        assert _has_results(_study(has_results=True)) is True
        assert _has_results(_study()) is False

    def test_extract_results_extraction(self):
        extraction = _extract_results_extraction(_study(has_results=True))
        assert extraction is not None
        assert extraction["primary_outcome"] == "Frailty Index"
        assert extraction["intervention"] == "Metformin"
        assert extraction["comparator"] == "Placebo"
        assert extraction["effects"][0]["metric"] == "MEAN"
        assert "p=0.04" in extraction["effects"][0]["source_span"]


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

    def test_search_marks_trial_results_and_populates_extraction(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response([_study(has_results=True)])

        client = ClinicalTrialsClient(transport=httpx.MockTransport(handler))
        results = client.search("test", limit=5)
        assert results[0]["trial_status"] == "results"
        assert results[0]["has_results"] is True
        assert results[0]["extraction"]["effects"][0]["outcome"] == "Frailty Index"

    def test_search_marks_registry_only_when_no_results_posted(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response([_study(has_results=False)])

        client = ClinicalTrialsClient(transport=httpx.MockTransport(handler))
        results = client.search("test", limit=5)
        assert results[0]["trial_status"] == "registered"
        assert results[0]["has_results"] is False
        assert results[0]["extraction"] is None
