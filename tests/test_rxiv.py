from __future__ import annotations

import json

import httpx

from agent.sources.rxiv import RxivClient, _source_type


def _result(*, publisher: str = "bioRxiv", title: str = "Rapamycin preprint", abstract: str = "Preprint abstract on aging.", doi: str = "10.1101/2025.01.01.123456") -> dict:
    return {
        "id": "PPR123",
        "source": "PPR",
        "doi": doi,
        "title": title,
        "pubYear": "2025",
        "abstractText": abstract,
        "bookOrReportDetails": {"publisher": publisher},
        "fullTextUrlList": {"fullTextUrl": [{"url": f"https://doi.org/{doi}"}]},
        "authorList": {"author": [{"lastName": "Smith"}, {"lastName": "Jones"}]},
    }


def _mock_response(results: list[dict] | None = None) -> httpx.Response:
    body = json.dumps({"resultList": {"result": results or [_result()]}}).encode()
    return httpx.Response(200, content=body, headers={"content-type": "application/json"})


def test_source_type_maps_publishers():
    assert _source_type(_result(publisher="bioRxiv")) == "biorxiv"
    assert _source_type(_result(publisher="medRxiv")) == "medrxiv"
    assert _source_type(_result(publisher="Research Square")) is None


def test_search_returns_rxiv_entries():
    def handler(request: httpx.Request) -> httpx.Response:
        return _mock_response([_result(publisher="bioRxiv"), _result(publisher="medRxiv", doi="10.1101/2025.01.02.654321")])

    client = RxivClient(transport=httpx.MockTransport(handler))
    results = client.search("rapamycin aging", limit=5)
    assert len(results) == 2
    assert results[0]["source_type"] == "biorxiv"
    assert results[1]["source_type"] == "medrxiv"
    assert results[0]["url"].startswith("https://doi.org/")


def test_search_skips_non_rxiv_publishers():
    def handler(request: httpx.Request) -> httpx.Response:
        return _mock_response([_result(publisher="Research Square"), _result(publisher="bioRxiv")])

    client = RxivClient(transport=httpx.MockTransport(handler))
    results = client.search("rapamycin aging", limit=5)
    assert len(results) == 1
    assert results[0]["source_type"] == "biorxiv"


def test_search_respects_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return _mock_response([_result(doi=f"10.1101/2025.01.0{i}.1") for i in range(5)])

    client = RxivClient(transport=httpx.MockTransport(handler))
    results = client.search("rapamycin aging", limit=2)
    assert len(results) == 2
