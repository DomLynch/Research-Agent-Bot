from __future__ import annotations

import httpx

from agent.sources.europepmc import EuropePMCClient


def _transport(handler):
    return httpx.MockTransport(handler)


def test_europepmc_search_normalizes_core_fields():
    payload = {
        "resultList": {
            "result": [
                {
                    "id": "40147475",
                    "source": "MED",
                    "pmcid": "PMC1234567",
                    "doi": "10.1016/S0140-6736(25)00000-1",
                    "title": "Metformin and physical performance in older adults",
                    "abstractText": "Randomized placebo-controlled trial in older adults with frailty outcomes.",
                    "pubYear": "2025",
                    "journalTitle": "Lancet Healthy Longevity",
                    "authorString": "Witham M, Turner G",
                }
            ]
        }
    }

    def handler(req: httpx.Request) -> httpx.Response:
        assert "webservices/rest/search" in str(req.url)
        return httpx.Response(200, json=payload)

    client = EuropePMCClient(transport=_transport(handler))
    results = client.search("metformin aging older adults", limit=5)
    assert len(results) == 1
    first = results[0]
    assert first["source_type"] == "europepmc"
    assert first["evidence_type"] == "primary"
    assert first["pmcid"] == "PMC1234567"
    assert first["journal"] == "Lancet Healthy Longevity"
    assert first["authors"] == ["Witham M", "Turner G"]


def test_europepmc_search_falls_back_to_metadata_excerpt():
    payload = {
        "resultList": {
            "result": [
                {
                    "id": "123",
                    "source": "MED",
                    "title": "Trial protocol in older adults",
                    "abstractText": "",
                    "pubYear": "2024",
                    "journalTitle": "BMJ Open",
                    "authorString": "Smith J",
                }
            ]
        }
    }

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = EuropePMCClient(transport=_transport(handler))
    results = client.search("older adults protocol", limit=5)
    assert len(results) == 1
    assert results[0]["evidence_type"] == "protocol"
    assert "BMJ Open" in results[0]["excerpt"]
