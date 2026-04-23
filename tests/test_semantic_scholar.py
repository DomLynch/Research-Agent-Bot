"""Tests for agent.sources.semantic_scholar. Uses MockTransport only.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_semantic_scholar.py -v
"""
from __future__ import annotations

import httpx

from agent.sources.semantic_scholar import SemanticScholarClient


def _transport(handler):
    return httpx.MockTransport(handler)


# Sample S2 responses — realistic shapes
_SEARCH_RESPONSE = {
    "total": 1,
    "data": [{
        "paperId": "abc",
        "title": "Metformin for anti-aging: a systematic review",
        "abstract": "We reviewed 20 RCTs of metformin in older adults...",
        "year": 2023,
        "externalIds": {"DOI": "10.1000/example.2023", "PubMed": "12345"},
        "publicationTypes": ["Review"],
    }],
}

_REFERENCES_RESPONSE = {
    "data": [
        {"citedPaper": {
            "paperId": "ref1",
            "title": "Metformin in older adults: RCT",
            "abstract": "Randomized controlled trial of 200 patients...",
            "year": 2015,
            "externalIds": {"DOI": "10.1000/rct.2015"},
            "publicationTypes": ["ClinicalTrial"],
        }},
        {"citedPaper": {
            "paperId": "ref2",
            "title": "Mechanisms of metformin",
            "abstract": "Review of mechanisms...",
            "year": 2018,
            "externalIds": {"DOI": "10.1000/mech.2018"},
            "publicationTypes": ["Review"],
        }},
    ],
}


def test_search_returns_normalized_papers():
    def handler(req):
        assert "paper/search" in str(req.url)
        return httpx.Response(200, json=_SEARCH_RESPONSE)
    client = SemanticScholarClient(transport=_transport(handler))
    results = client.search("metformin aging", limit=10)
    assert len(results) == 1
    r = results[0]
    assert r["doi"] == "10.1000/example.2023"
    assert r["year"] == 2023
    assert r["evidence_type"] == "review"
    assert r["source_type"] == "semantic_scholar"
    assert r["url"] == "https://doi.org/10.1000/example.2023"


def test_references_of_unwraps_citedPaper():
    def handler(req):
        assert "/references" in str(req.url)
        return httpx.Response(200, json=_REFERENCES_RESPONSE)
    client = SemanticScholarClient(transport=_transport(handler))
    refs = client.references_of("10.1000/example.2023")
    assert len(refs) == 2
    assert refs[0]["doi"] == "10.1000/rct.2015"
    assert refs[0]["evidence_type"] == "interventional"
    assert refs[1]["evidence_type"] == "review"


def test_citations_of_handles_citingPaper_wrap():
    response = {
        "data": [
            {"citingPaper": {
                "paperId": "cit1",
                "title": "New trial citing the review",
                "abstract": "Latest evidence...",
                "year": 2024,
                "externalIds": {"DOI": "10.1000/new.2024"},
                "publicationTypes": ["ClinicalTrial"],
            }},
        ],
    }
    def handler(req):
        assert "/citations" in str(req.url)
        return httpx.Response(200, json=response)
    client = SemanticScholarClient(transport=_transport(handler))
    cites = client.citations_of("10.1000/example.2023")
    assert len(cites) == 1
    assert cites[0]["year"] == 2024


def test_invalid_doi_returns_empty_list():
    def handler(req): raise AssertionError("should not call API on invalid DOI")
    client = SemanticScholarClient(transport=_transport(handler))
    assert client.references_of("") == []
    assert client.references_of("not a doi") == []
    assert client.citations_of("also not") == []


def test_doi_normalization():
    def handler(req):
        assert "DOI:10.1000/example.2023" in str(req.url)
        return httpx.Response(200, json=_REFERENCES_RESPONSE)
    client = SemanticScholarClient(transport=_transport(handler))
    # Accepts various prefixed forms
    assert len(client.references_of("https://doi.org/10.1000/example.2023")) == 2


def test_http_error_returns_empty():
    def handler(req): return httpx.Response(500)
    client = SemanticScholarClient(transport=_transport(handler))
    assert client.search("anything") == []
    assert client.references_of("10.1000/x") == []


def test_rate_limit_retries_once():
    call_count = [0]
    def handler(req):
        call_count[0] += 1
        if call_count[0] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json=_SEARCH_RESPONSE)
    client = SemanticScholarClient(transport=_transport(handler))
    results = client.search("metformin")
    assert len(results) == 1
    assert call_count[0] == 2


def test_missing_fields_handled_gracefully():
    response = {"data": [{"paperId": "x", "title": "", "externalIds": {}}]}
    def handler(req): return httpx.Response(200, json=response)
    client = SemanticScholarClient(transport=_transport(handler))
    results = client.search("anything")
    # Paper with no DOI and no title still returns but with safe defaults
    assert len(results) == 1
    assert results[0]["doi"] == ""
    assert results[0]["year"] is None


def test_evidence_type_inference_from_pub_types():
    response = {"data": [{
        "paperId": "x",
        "title": "A randomized trial of metformin",
        "abstract": "n/a",
        "year": 2020,
        "externalIds": {"DOI": "10.1/y"},
        "publicationTypes": ["ClinicalTrial"],
    }]}
    def handler(req): return httpx.Response(200, json=response)
    client = SemanticScholarClient(transport=_transport(handler))
    r = client.search("trial")[0]
    assert r["evidence_type"] == "interventional"


def test_evidence_type_inference_from_text_fallback():
    response = {"data": [{
        "paperId": "x",
        "title": "Umbrella review of X",
        "abstract": "We performed a systematic review...",
        "year": 2021,
        "externalIds": {"DOI": "10.1/z"},
        "publicationTypes": [],
    }]}
    def handler(req): return httpx.Response(200, json=response)
    client = SemanticScholarClient(transport=_transport(handler))
    r = client.search("anything")[0]
    assert r["evidence_type"] == "review"
