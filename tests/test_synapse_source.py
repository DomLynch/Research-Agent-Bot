"""Tests for agent.sources.synapse — Synapse (Sage Bionetworks) adapter."""
from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest

from agent.sources.synapse import SEARCH_URL, SynapseClient


# ---------- Parser tests (no network) -------------------------------------


def test_parse_hit_full_record() -> None:
    hit = SynapseClient()._parse_hit({
        "id": "syn12345",
        "name": "AMP-AD whole-genome sequencing",
        "description": "Multi-cohort WGS for Alzheimer's disease research.",
        "node_type": "entity.project",
        "created_on": 1376581601,  # 2013-08-15
    })
    assert hit is not None
    assert hit.source == "synapse"
    assert hit.title == "AMP-AD whole-genome sequencing"
    assert hit.abstract.startswith("Multi-cohort WGS")
    assert hit.year == 2013
    assert hit.url == "https://www.synapse.org/Synapse:syn12345"
    assert hit.venue == "Synapse"
    assert hit.raw["synapse_id"] == "syn12345"


def test_parse_hit_uses_modified_on_when_created_on_missing() -> None:
    hit = SynapseClient()._parse_hit({
        "id": "syn1", "name": "x", "modified_on": 1735689600,  # 2025-01-01
    })
    assert hit is not None
    assert hit.year == 2025


def test_parse_hit_year_none_when_no_timestamp() -> None:
    hit = SynapseClient()._parse_hit({"id": "syn1", "name": "x"})
    assert hit is not None
    assert hit.year is None


def test_parse_hit_returns_none_when_name_missing() -> None:
    assert SynapseClient()._parse_hit({"id": "syn1"}) is None
    assert SynapseClient()._parse_hit({}) is None


def test_parse_hit_returns_none_for_non_dict() -> None:
    assert SynapseClient()._parse_hit("string") is None
    assert SynapseClient()._parse_hit(None) is None


def test_parse_hit_falls_back_to_generated_description() -> None:
    """No description → adapter generates a placeholder so aggregator
    never sees an empty abstract."""
    hit = SynapseClient()._parse_hit({
        "id": "syn1", "name": "Some Project", "node_type": "entity.project",
    })
    assert hit is not None
    assert "project" in hit.abstract.lower()
    assert "Some Project" in hit.abstract


# ---------- End-to-end with mocked transport ------------------------------


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_token() -> None:
    """Adapter is opt-in: missing SYNAPSE_AUTH_TOKEN → empty list, no call."""
    with patch.dict(os.environ, {"SYNAPSE_AUTH_TOKEN": ""}, clear=False):
        # Pop the var if it's set globally
        os.environ.pop("SYNAPSE_AUTH_TOKEN", None)
        async with httpx.AsyncClient() as client:
            result = await SynapseClient().search(client, "rapamycin", limit=5)
    assert result == []


@pytest.mark.asyncio
async def test_search_parses_201_response_with_hits() -> None:
    """Synapse returns 201 (not 200) for the search POST; both must work."""
    payload = {
        "found": 2,
        "hits": [
            {"id": "syn1", "name": "Rapamycin lifespan",
             "description": "ITP cohort.", "created_on": 1735689600},
            {"id": "syn2", "name": "Rapamycin in mice",
             "description": "Heterogeneous stock.", "created_on": 1672531200},
        ],
    }
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert str(req.url) == SEARCH_URL
        assert req.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(201, json=payload)

    with patch.dict(os.environ, {"SYNAPSE_AUTH_TOKEN": "test-token"}):
        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            hits = await SynapseClient().search(client, "rapamycin", limit=10)
    assert len(hits) == 2
    assert hits[0].title == "Rapamycin lifespan"
    assert hits[0].year == 2025
    assert hits[1].year == 2023


@pytest.mark.asyncio
async def test_search_accepts_200_response_too() -> None:
    """Backwards-compat: if Synapse changes to 200 someday, adapter still works."""
    def handler(req): return httpx.Response(200, json={"hits": [
        {"id": "syn1", "name": "X", "description": "y"},
    ]})
    with patch.dict(os.environ, {"SYNAPSE_AUTH_TOKEN": "test-token"}):
        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            hits = await SynapseClient().search(client, "q", limit=1)
    assert len(hits) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_search_fails_soft_on_non_success_status(status) -> None:
    def handler(req): return httpx.Response(status, json={"reason": "x"})
    with patch.dict(os.environ, {"SYNAPSE_AUTH_TOKEN": "test-token"}):
        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            hits = await SynapseClient().search(client, "q", limit=1)
    assert hits == []


@pytest.mark.asyncio
async def test_search_fails_soft_on_invalid_json() -> None:
    def handler(req): return httpx.Response(201, content=b"not json")
    with patch.dict(os.environ, {"SYNAPSE_AUTH_TOKEN": "test-token"}):
        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            hits = await SynapseClient().search(client, "q", limit=1)
    assert hits == []


@pytest.mark.asyncio
async def test_search_fails_soft_on_missing_hits_key() -> None:
    def handler(req): return httpx.Response(201, json={"found": 0})
    with patch.dict(os.environ, {"SYNAPSE_AUTH_TOKEN": "test-token"}):
        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            hits = await SynapseClient().search(client, "q", limit=1)
    assert hits == []


@pytest.mark.asyncio
async def test_search_request_body_uses_query_term_array() -> None:
    """Synapse search expects queryTerm as a list, not a string."""
    captured = {}
    def handler(req):
        import json
        captured["body"] = json.loads(req.content)
        return httpx.Response(201, json={"hits": []})
    with patch.dict(os.environ, {"SYNAPSE_AUTH_TOKEN": "test-token"}):
        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            await SynapseClient().search(client, "rapamycin aging", limit=20)
    assert captured["body"]["queryTerm"] == ["rapamycin aging"]
    assert captured["body"]["size"] == 20


@pytest.mark.asyncio
async def test_search_size_clamps_to_one_hundred() -> None:
    """Synapse allows up to 100 per page; adapter clamps to that."""
    captured = {}
    def handler(req):
        import json
        captured["body"] = json.loads(req.content)
        return httpx.Response(201, json={"hits": []})
    with patch.dict(os.environ, {"SYNAPSE_AUTH_TOKEN": "test-token"}):
        async with httpx.AsyncClient(transport=_mock_transport(handler)) as client:
            await SynapseClient().search(client, "x", limit=500)
    assert captured["body"]["size"] == 100
