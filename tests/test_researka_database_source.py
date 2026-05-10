"""Tests for the private Researka Database source adapter."""
from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest

from agent.sources.researka_database import ResearkaDatabaseClient


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_search_returns_empty_without_token() -> None:
    with patch.dict(os.environ, {}, clear=True):
        async with httpx.AsyncClient() as client:
            hits = await ResearkaDatabaseClient().search(
                client, "rapamycin lifespan", limit=5,
            )
    assert hits == []


@pytest.mark.asyncio
async def test_search_posts_to_three_lane_endpoint_and_parses_hits() -> None:
    captured: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["url"] = str(req.url)
        captured["token"] = req.headers.get("X-Researka-Token")
        captured["json"] = req.read().decode()
        return httpx.Response(200, json={
            "established": [{
                "id": "openalex:W1",
                "title": "Rapamycin-mediated lifespan increase in mice",
                "abstract": "Rapamycin increased lifespan in genetically heterogeneous mice.",
                "publication_year": 2014,
                "journal_name": "Aging Cell",
                "doi": "https://doi.org/10.1111/acel.12237",
                "pmid": "24472261",
                "quality_score": 0.91,
                "cited_by_count": 700,
            }],
            "discovery": [],
            "semantic": [],
        })

    env = {
        "RESEARKA_DATABASE_TOKEN": "test-token",
        "RESEARKA_DATABASE_URL": "https://database.test",
    }
    with patch.dict(os.environ, env, clear=True):
        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            hits = await ResearkaDatabaseClient().search(
                client, "rapamycin lifespan", limit=5,
            )
    assert captured["method"] == "POST"
    assert captured["url"] == "https://database.test/api/v1/search"
    assert captured["token"] == "test-token"
    assert len(hits) == 1
    assert hits[0].source == "researka_database"
    assert hits[0].doi == "10.1111/acel.12237"
    assert hits[0].pmid == "24472261"
    assert hits[0].year == 2014
    assert hits[0].venue == "Aging Cell"
    assert hits[0].raw["lane"] == "established"
    assert hits[0].raw["quality_score"] == 0.91


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_search_fails_soft_on_auth_rate_limit_or_server_error(status: int) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": "x"})

    with patch.dict(os.environ, {"RESEARKA_DATABASE_TOKEN": "test-token"}):
        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            hits = await ResearkaDatabaseClient().search(client, "x", limit=3)
    assert hits == []


def test_parse_skips_rows_missing_title_or_abstract() -> None:
    client = ResearkaDatabaseClient()
    assert client._parse({"title": "x"}, lane="semantic", query="x") is None
    assert client._parse({"abstract": "x"}, lane="semantic", query="x") is None
