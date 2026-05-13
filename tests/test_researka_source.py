"""Tests for agent.sources.researka — tier-2 facts adapter.

Stdlib-only. No live HTTP — every test uses an httpx MockTransport so
the test suite stays hermetic and the adapter's fail-soft branches are
deterministically exercised.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest

from agent.sources.researka import (  # type: ignore[import-not-found]
    RESEARKA_BASE,
    TOPIC_PAPERS_PATH,
    ResearkaClient,
    _topic_from_query,
)
from agent.types import RawHit


# ---- helpers --------------------------------------------------------------


def _mock_client(responder) -> httpx.AsyncClient:
    transport = httpx.MockTransport(responder)
    return httpx.AsyncClient(transport=transport)


def _ok_response(records: list[dict]) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(records).encode())


@pytest.fixture
def with_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("RESEARKA_DATABASE_TOKEN", "test-token")
    yield "test-token"


@pytest.fixture
def no_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("RESEARKA_DATABASE_TOKEN", raising=False)
    yield None


# ---- topic-slug extraction (universal, no per-topic table) ---------------


def test_topic_from_query_takes_first_word() -> None:
    assert _topic_from_query("berberine AND randomized trial") == "berberine"
    assert _topic_from_query("urolithin_a AND mitochondria") == "urolithin_a"
    assert _topic_from_query("caloric restriction AND aging") == "caloric"


def test_topic_from_query_lowercases() -> None:
    assert _topic_from_query("Rapamycin AND Longevity") == "rapamycin"


def test_topic_from_query_handles_leading_whitespace() -> None:
    assert _topic_from_query("  metformin AND glycemia") == "metformin"


def test_topic_from_query_works_for_non_biomed_topics() -> None:
    """Universal-no-hardcoding: must work for any domain."""
    assert _topic_from_query("permafrost carbon flux") == "permafrost"
    assert _topic_from_query("ARMA forecasting equity returns") == "arma"


# ---- fail-soft semantics --------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_token(no_token: None) -> None:
    """Adapter MUST NOT call the live API without auth — fail-soft."""
    calls: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"[]")

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=10)
    assert hits == []
    assert calls == [], "adapter must not hit the API without a token"


@pytest.mark.asyncio
async def test_search_returns_empty_on_500(with_token: str) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"server error")

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=5)
    assert hits == []


@pytest.mark.asyncio
async def test_search_returns_empty_on_401(with_token: str) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b'{"detail":"invalid token"}')

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=5)
    assert hits == []


@pytest.mark.asyncio
async def test_search_returns_empty_on_malformed_json(with_token: str) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not json")

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=5)
    assert hits == []


@pytest.mark.asyncio
async def test_search_returns_empty_on_non_array_response(
    with_token: str,
) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"data": "wrong shape"}')

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=5)
    assert hits == []


# ---- request shape -------------------------------------------------------


@pytest.mark.asyncio
async def test_search_sends_topic_token_and_method(with_token: str) -> None:
    received: dict = {}

    def responder(request: httpx.Request) -> httpx.Response:
        received["method"] = request.method
        received["url"] = str(request.url)
        received["headers"] = dict(request.headers)
        received["body"] = json.loads(request.content)
        return _ok_response([])

    async with _mock_client(responder) as client:
        await ResearkaClient().search(client, "berberine AND longevity", limit=8)

    assert received["method"] == "POST"
    assert received["url"] == RESEARKA_BASE + TOPIC_PAPERS_PATH
    # Auth header sent
    assert received["headers"].get("x-researka-token") == "test-token"
    # Body: extracted topic + limit + include_facts=False
    assert received["body"]["topic"] == "berberine"
    assert received["body"]["limit"] == 8
    assert received["body"]["include_facts"] is False


@pytest.mark.asyncio
async def test_search_caps_limit_at_50(with_token: str) -> None:
    """Defensive: API may not like huge limits. Adapter caps at 50."""
    received: dict = {}

    def responder(request: httpx.Request) -> httpx.Response:
        received["body"] = json.loads(request.content)
        return _ok_response([])

    async with _mock_client(responder) as client:
        await ResearkaClient().search(client, "berberine", limit=10_000)
    assert received["body"]["limit"] == 50


# ---- response normalization ----------------------------------------------


_SAMPLE_PAPER = {
    "title": "Berberine and aging: a randomized trial",
    "abstract": "We assessed berberine 500 mg daily for 12 weeks...",
    "year": 2024,
    "doi": "10.1234/example.001",
    "pmid": "12345678",
    "pmcid": "PMC9876543",
    "journal": "Aging Cell",
    "authors": ["Smith J", "Doe A"],
    "cited_by_count": 17,
    "similarity_score": 0.91,
}


@pytest.mark.asyncio
async def test_paper_hit_maps_to_raw_hit_correctly(with_token: str) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return _ok_response([_SAMPLE_PAPER])

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=10)

    assert len(hits) == 1
    h = hits[0]
    assert isinstance(h, RawHit)
    assert h.source == "researka"
    assert h.title.startswith("Berberine and aging")
    assert "berberine" in h.abstract.lower()
    assert h.year == 2024
    assert h.doi == "10.1234/example.001"
    assert h.pmid == "12345678"
    assert h.venue == "Aging Cell"
    # URL prefers DOI
    assert h.url == "https://doi.org/10.1234/example.001"


@pytest.mark.asyncio
async def test_url_falls_back_to_pubmed_then_pmc(with_token: str) -> None:
    no_doi = {**_SAMPLE_PAPER, "doi": None}

    def responder(request: httpx.Request) -> httpx.Response:
        return _ok_response([no_doi])

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=10)
    assert hits[0].url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"

    no_doi_no_pmid = {**_SAMPLE_PAPER, "doi": None, "pmid": None}

    def responder2(request: httpx.Request) -> httpx.Response:
        return _ok_response([no_doi_no_pmid])

    async with _mock_client(responder2) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=10)
    assert hits[0].url == (
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9876543/"
    )


@pytest.mark.asyncio
async def test_records_without_title_are_skipped(with_token: str) -> None:
    bad = {"title": "", "abstract": "x"}
    good = _SAMPLE_PAPER

    def responder(request: httpx.Request) -> httpx.Response:
        return _ok_response([bad, good])

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=10)
    assert len(hits) == 1
    assert hits[0].title.startswith("Berberine")


@pytest.mark.asyncio
async def test_non_dict_records_are_skipped(with_token: str) -> None:
    # Deliberately heterogeneous payload — adapter must skip non-dicts.
    bad_payload: list[object] = [_SAMPLE_PAPER, "stray string", 42, None]

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(bad_payload).encode())

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=10)
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_results_truncated_to_caller_limit(with_token: str) -> None:
    """Even if the API returns more than the caller asked for (e.g.
    after our internal cap-at-50), the adapter respects the caller's
    limit."""

    def responder(request: httpx.Request) -> httpx.Response:
        return _ok_response([_SAMPLE_PAPER] * 30)

    async with _mock_client(responder) as client:
        hits = await ResearkaClient().search(client, "berberine", limit=5)
    assert len(hits) == 5
