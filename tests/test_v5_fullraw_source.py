from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agent.sources.v5_fullraw import V5FullRawClient


def _mock_client(responder) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(responder))


@pytest.fixture
def fullraw_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "http://fullraw.test/search")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TOKEN", "test-token")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "12")


@pytest.mark.asyncio
async def test_fullraw_disabled_without_url_or_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", raising=False)
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_TOKEN", raising=False)
    calls: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    async with _mock_client(responder) as client:
        hits = await V5FullRawClient().search(client, "metformin longevity", limit=3)

    assert hits == []
    assert calls == []


@pytest.mark.asyncio
async def test_fullraw_posts_query_and_maps_receipt(fullraw_env: None) -> None:
    received: dict[str, Any] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        received["auth"] = request.headers.get("authorization")
        received["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "meta": {
                    "shard_receipt": {
                        "shards_searched": 50,
                        "sources_searched": {"openalex": 16, "pubmed": 17},
                        "papers_searched": 46768695,
                    },
                },
                "results": [
                    {
                        "title": "Metformin and longevity",
                        "abstract": "Metformin was evaluated in aging biology.",
                        "doi": "10.1000/example",
                        "year": 2024,
                        "journal": "Aging Cell",
                        "source": "openalex",
                        "openalex_id": "https://openalex.org/W1",
                        "cited_by_count": 12,
                    },
                ],
            },
        )

    async with _mock_client(responder) as client:
        hits = await V5FullRawClient().search(client, "metformin longevity", limit=3)

    assert received["url"] == "http://fullraw.test/search"
    assert received["auth"] == "Bearer test-token"
    assert received["body"] == {
        "query": "metformin longevity",
        "limit": 3,
        "top_k": 3,
        "year_min": 1900,
        "year_max": 2100,
        "corpus": "full_raw_450m_plus",
        "search_pass": "focused",
        "rank_mode": "relevance",
        "timeout_seconds": 12.0,
    }
    assert len(hits) == 1
    hit = hits[0]
    assert hit.source == "v5_fullraw"
    assert hit.raw["fullraw_source"] == "openalex"
    assert hit.raw["shard_receipt"]["shards_searched"] == 50
    assert "openalex" in hit.raw["shard_receipt"]["sources_searched"]


@pytest.mark.asyncio
async def test_fullraw_caps_publish_lane_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "http://fullraw.test/search")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TOKEN", "test-token")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "900")
    received: dict[str, Any] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        received["body"] = json.loads(request.content)
        return httpx.Response(200, json={"meta": {"shard_receipt": {}}, "results": []})

    async with _mock_client(responder) as client:
        await V5FullRawClient().search(client, "metformin longevity", limit=3)

    assert received["body"]["timeout_seconds"] == 300.0


@pytest.mark.asyncio
async def test_fullraw_query_timeout_overrides_long_corpus_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "http://fullraw.test/search")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TOKEN", "test-token")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TIMEOUT", "300")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_QUERY_TIMEOUT", "17")
    received: dict[str, Any] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        received["body"] = json.loads(request.content)
        return httpx.Response(200, json={"meta": {"shard_receipt": {}}, "results": []})

    async with _mock_client(responder) as client:
        await V5FullRawClient().search(client, "metformin longevity", limit=3)

    assert received["body"]["timeout_seconds"] == 17.0


@pytest.mark.asyncio
async def test_fullraw_fail_soft_on_http_error(fullraw_env: None) -> None:
    async with _mock_client(lambda request: httpx.Response(503, content=b"down")) as client:
        assert await V5FullRawClient().search(client, "metformin", limit=3) == []


@pytest.mark.asyncio
async def test_fullraw_fail_soft_on_timeout(fullraw_env: None) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow fullraw shard sweep", request=request)

    async with _mock_client(responder) as client:
        assert await V5FullRawClient().search(client, "low dose lithium aging", limit=3) == []
