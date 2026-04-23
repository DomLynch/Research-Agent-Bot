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
        if "api.unpaywall.org" in request.url.host:
            return httpx.Response(404, json={})
        raise AssertionError(f"Unexpected path: {request.url.path}")

    return httpx.MockTransport(handler)


def test_fetch_full_text_from_europe_pmc_and_cache(tmp_path: Path) -> None:
    counter: dict[str, int] = {}
    fetcher = FullTextFetcher(cache_dir=tmp_path, transport=_transport(counter))
    entry = {"doi": "10.1000/test", "title": "Test paper", "source_type": "pubmed"}

    enriched, stats = fetcher.enrich_entries([entry], limit=1)

    assert stats["attempted"] == 1
    assert stats["found"] == 1
    assert stats["found_any"] == 1
    assert stats["parseable_text_count"] == 1
    assert enriched[0]["full_text_source"] == "europepmc"
    assert "Older adults" in enriched[0]["full_text"]
    assert enriched[0]["full_text_sections"]["methods"].startswith("Older adults")
    cached = FullTextFetcher(cache_dir=tmp_path, transport=_transport(counter))
    second, second_stats = cached.enrich_entries([entry], limit=1)
    assert second[0]["pmcid"] == "PMC123"
    assert second_stats["found"] == 1
    assert second_stats["found_any"] == 1
    assert counter["calls"] == 2


def test_fetch_full_text_handles_missing_pmcid(tmp_path: Path) -> None:
    fetcher = FullTextFetcher(cache_dir=tmp_path, transport=_transport({}, has_pmcid=False))
    entry = {"doi": "10.1000/missing", "title": "Missing pmcid", "source_type": "pubmed"}

    enriched, stats = fetcher.enrich_entries([entry], limit=1)

    assert stats["attempted"] == 1
    assert stats["found"] == 0
    assert "full_text" not in enriched[0]
    assert stats["source_counts"]["none"] == 1


def test_fetch_cascades_to_unpaywall_pmc_xml(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"resultList": {"result": [{}]}})
        if "api.unpaywall.org" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "is_oa": True,
                    "oa_status": "gold",
                    "best_oa_location": {
                        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9999999/",
                        "url_for_pdf": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9999999/pdf/main.pdf",
                    },
                },
            )
        if request.url.path.endswith("/PMC9999999/fullTextXML"):
            xml = """
            <article>
              <body>
                <sec><title>Results</title><p>Frailty improved by 23%.</p></sec>
              </body>
            </article>
            """
            return httpx.Response(200, text=xml)
        raise AssertionError(f"Unexpected URL: {request.url}")

    fetcher = FullTextFetcher(cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    enriched, stats = fetcher.enrich_entries([{"doi": "10.1/jats", "title": "JATS paper", "source_type": "pubmed"}], limit=1)

    assert enriched[0]["full_text_source"] == "unpaywall_jats"
    assert "23%" in enriched[0]["full_text"]
    assert stats["source_counts"]["unpaywall_jats"] == 1
    assert stats["found_any"] == 1
    assert stats["parseable_text_count"] == 1


def test_fetch_cascades_to_unpaywall_pdf_only(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"resultList": {"result": [{}]}})
        if "api.unpaywall.org" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "is_oa": True,
                    "oa_status": "bronze",
                    "best_oa_location": {
                        "url": "https://example.org/article",
                        "url_for_pdf": "https://example.org/article.pdf",
                    },
                },
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    fetcher = FullTextFetcher(cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    enriched, stats = fetcher.enrich_entries([{"doi": "10.1/pdfonly", "title": "PDF only", "source_type": "pubmed"}], limit=1)

    assert enriched[0]["full_text_source"] == "unpaywall_pdf_only"
    assert enriched[0]["full_text_pdf_url"] == "https://example.org/article.pdf"
    assert "full_text" not in enriched[0]
    assert stats["source_counts"]["unpaywall_pdf_only"] == 1
    assert stats["found_any"] == 1
    assert stats["parseable_text_count"] == 0


def test_entry_identity_prefers_doi_then_url() -> None:
    assert entry_identity({"doi": "10.1000/test", "url": "https://example.com"}) == "10.1000/test"
    assert entry_identity({"url": "https://example.com"}) == "https://example.com"


def test_fetch_full_text_accepts_semantic_scholar_entries(tmp_path: Path) -> None:
    counter: dict[str, int] = {}
    fetcher = FullTextFetcher(cache_dir=tmp_path, transport=_transport(counter))
    entry = {"doi": "10.1000/test", "title": "Test paper", "source_type": "semantic_scholar"}

    enriched, stats = fetcher.enrich_entries([entry], limit=1)

    assert stats["attempted"] == 1
    assert stats["found"] == 1
    assert enriched[0]["full_text_source"] == "europepmc"
