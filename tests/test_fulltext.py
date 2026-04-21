from __future__ import annotations
from pathlib import Path

import httpx

from agent.fulltext import FullTextFetcher, entry_identity


def _transport(counter: dict[str, int], *, has_pmcid: bool = True) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        counter["calls"] = counter.get("calls", 0) + 1
        if request.url.path.endswith("/search"):
            result = {"resultList": {"result": [{"pmcid": "PMC123"}] if has_pmcid else [{}]}}
            return httpx.Response(200, json=result)
        if request.url.path.endswith("/PMC123/fullTextXML"):
            xml = """
            <article>
              <body>
                <sec><title>Methods</title><p>Older adults randomized to treatment.</p></sec>
                <sec><title>Results</title><p>Outcome improved with hazard ratio 0.80.</p></sec>
              </body>
            </article>
            """
            return httpx.Response(200, text=xml)
        raise AssertionError(f"Unexpected path: {request.url.path}")

    return httpx.MockTransport(handler)


def test_fetch_full_text_from_europe_pmc_and_cache(tmp_path: Path) -> None:
    counter: dict[str, int] = {}
    fetcher = FullTextFetcher(cache_dir=tmp_path, transport=_transport(counter))
    entry = {"doi": "10.1000/test", "title": "Test paper", "source_type": "pubmed"}

    enriched, stats = fetcher.enrich_entries([entry], limit=1)

    assert stats["attempted"] == 1
    assert stats["found"] == 1
    assert enriched[0]["full_text_source"] == "europepmc"
    assert "Older adults" in enriched[0]["full_text"]
    assert enriched[0]["full_text_sections"]["methods"].startswith("Older adults")
    cached = FullTextFetcher(cache_dir=tmp_path, transport=_transport(counter))
    second, second_stats = cached.enrich_entries([entry], limit=1)
    assert second[0]["pmcid"] == "PMC123"
    assert second_stats["found"] == 1
    assert counter["calls"] == 2


def test_fetch_full_text_handles_missing_pmcid(tmp_path: Path) -> None:
    fetcher = FullTextFetcher(cache_dir=tmp_path, transport=_transport({}, has_pmcid=False))
    entry = {"doi": "10.1000/missing", "title": "Missing pmcid", "source_type": "pubmed"}

    enriched, stats = fetcher.enrich_entries([entry], limit=1)

    assert stats["attempted"] == 1
    assert stats["found"] == 0
    assert "full_text" not in enriched[0]


def test_entry_identity_prefers_doi_then_url() -> None:
    assert entry_identity({"doi": "10.1000/test", "url": "https://example.com"}) == "10.1000/test"
    assert entry_identity({"url": "https://example.com"}) == "https://example.com"
