from __future__ import annotations

import httpx

from agent.sources.reporter import NIHReporterClient


def _transport(handler):
    return httpx.MockTransport(handler)


def test_reporter_search_normalizes_project_hits():
    payload = {
        "results": [
            {
                "project_title": "Rapamycin for healthy aging in older adults",
                "project_num": "R01AG000001",
                "fiscal_year": 2026,
                "phr_text": "Clinical aging trial funding in older adults receiving sirolimus.",
                "project_detail_url": "https://reporter.nih.gov/project-details/1",
                "principal_investigators": [{"full_name": "Matt Kaeberlein"}],
            }
        ]
    }

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "projects/search" in str(req.url)
        return httpx.Response(200, json=payload)

    client = NIHReporterClient(transport=_transport(handler))
    results = client.search("rapamycin aging older adults", limit=5)
    assert len(results) == 1
    first = results[0]
    assert first["source_type"] == "nih_reporter"
    assert first["evidence_type"] == "protocol"
    assert first["year"] == 2026
    assert first["authors"] == ["Matt Kaeberlein"]
