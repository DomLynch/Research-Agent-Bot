from __future__ import annotations

from pathlib import Path

import httpx

from agent.sources.doaj import DOAJClient


def _transport(handler):
    return httpx.MockTransport(handler)


def test_doaj_lookup_matches_exact_journal_title(tmp_path: Path):
    payload = {
        "results": [
            {
                "bibjson": {
                    "title": "Geroscience",
                    "publisher": "Springer",
                    "license": [{"type": "CC BY"}],
                    "doaj_seal": True,
                }
            }
        ]
    }

    def handler(req: httpx.Request) -> httpx.Response:
        assert "api/search/journals" in str(req.url)
        return httpx.Response(200, json=payload)

    client = DOAJClient(cache_dir=tmp_path, transport=_transport(handler))
    meta = client.lookup_journal("Geroscience")
    assert meta
    assert meta["indexed"] is True
    assert meta["license"] == "CC BY"
    assert meta["seal"] is True


def test_doaj_annotate_entries_marks_indexed_journals(tmp_path: Path):
    payload = {"results": [{"bibjson": {"title": "Geroscience", "publisher": "Springer", "license": [{"type": "CC BY"}]}}]}

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = DOAJClient(cache_dir=tmp_path, transport=_transport(handler))
    entries = [{"title": "Paper", "journal": "Geroscience"}]
    annotated = client.annotate_entries(entries)
    assert annotated[0]["journal_quality"] == "doaj-indexed"
    assert annotated[0]["doaj_indexed"] is True
