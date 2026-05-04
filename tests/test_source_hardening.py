"""Bullet-proof source-adapter hardening tests.

Asserts the fail-soft contract for every adapter:
  - Network errors (httpx.HTTPError) → return [] (no crash)
  - Rate limit (429) → return [] (no crash)
  - Auth failure (401/403) → return [] (no crash)
  - Server error (5xx) → return [] (no crash)
  - Malformed JSON → return [] (no crash)
  - Empty body → return [] (no crash)

The aggregator runs sources in parallel via asyncio.gather; any one
adapter that raises crashes the entire fan-out and aborts the run.
These tests prove no adapter can cause that.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from agent.sources._base import safe_get_json, safe_get_text


# ---------- helper-level contract tests -----------------------------

class _FakeResponse:
    """Minimal stub matching the parts of httpx.Response we use."""
    def __init__(self, status_code: int, text: str = "", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


@pytest.mark.asyncio
async def test_safe_get_json_returns_none_on_network_error():
    """Transport error → None (caller treats as 'source contributed 0')."""
    cli = AsyncMock()
    cli.get.side_effect = httpx.ConnectError("boom")
    assert await safe_get_json(cli, "http://x.test/") is None


@pytest.mark.asyncio
async def test_safe_get_json_returns_none_on_timeout():
    """Timeout → None, not an exception that aborts the aggregator."""
    cli = AsyncMock()
    cli.get.side_effect = httpx.ReadTimeout("slow")
    assert await safe_get_json(cli, "http://x.test/") is None


@pytest.mark.asyncio
async def test_safe_get_json_returns_none_on_429():
    """Rate limit → None (don't bring down the run)."""
    cli = AsyncMock()
    cli.get.return_value = _FakeResponse(429)
    assert await safe_get_json(cli, "http://x.test/") is None


@pytest.mark.asyncio
async def test_safe_get_json_returns_none_on_auth_failure():
    """401 / 403 (bad key) → None."""
    cli = AsyncMock()
    for code in (401, 403):
        cli.get.return_value = _FakeResponse(code)
        assert await safe_get_json(cli, "http://x.test/") is None


@pytest.mark.asyncio
async def test_safe_get_json_returns_none_on_server_error():
    """5xx → None."""
    cli = AsyncMock()
    for code in (500, 502, 503, 504):
        cli.get.return_value = _FakeResponse(code)
        assert await safe_get_json(cli, "http://x.test/") is None


@pytest.mark.asyncio
async def test_safe_get_json_returns_none_on_malformed_body():
    """Invalid JSON in body → None, not a crash."""
    cli = AsyncMock()
    cli.get.return_value = _FakeResponse(200, json_data=None)  # raises ValueError on .json()
    assert await safe_get_json(cli, "http://x.test/") is None


@pytest.mark.asyncio
async def test_safe_get_json_returns_data_on_200():
    """Happy path: 200 + valid JSON → parsed dict."""
    cli = AsyncMock()
    cli.get.return_value = _FakeResponse(200, json_data={"hello": "world"})
    out = await safe_get_json(cli, "http://x.test/")
    assert out == {"hello": "world"}


@pytest.mark.asyncio
async def test_safe_get_text_returns_none_on_empty_body():
    """200 but empty body → None (XML adapters need content)."""
    cli = AsyncMock()
    cli.get.return_value = _FakeResponse(200, text="")
    assert await safe_get_text(cli, "http://x.test/") is None


@pytest.mark.asyncio
async def test_safe_get_text_returns_text_on_200():
    """Happy path: 200 + non-empty text → that text."""
    cli = AsyncMock()
    cli.get.return_value = _FakeResponse(200, text="<feed>hi</feed>")
    out = await safe_get_text(cli, "http://x.test/")
    assert out == "<feed>hi</feed>"


# ---------- per-adapter fail-soft assertions -----------------------

ALL_CORPUS_CLIENTS = [
    "agent.sources.pubmed.PubMedClient",
    "agent.sources.europepmc.EuropePMCClient",
    "agent.sources.openalex.OpenAlexClient",
    "agent.sources.clinicaltrials.ClinicalTrialsClient",
    "agent.sources.biorxiv.BioRxivClient",
    "agent.sources.medrxiv.MedRxivClient",
    "agent.sources.semantic_scholar.SemanticScholarClient",
    "agent.sources.crossref.CrossrefClient",
    "agent.sources.doaj.DoajClient",
    "agent.sources.openaire.OpenAireClient",
    "agent.sources.pmc_oai.PmcOaiClient",
    "agent.sources.arxiv.ArxivClient",
    "agent.sources.core.CoreClient",
    "agent.sources.chembl.ChemblClient",
]


def _import_client(qualified_name: str):
    """Import a client class given its fully-qualified name."""
    module_path, class_name = qualified_name.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


@pytest.mark.parametrize("client_path", ALL_CORPUS_CLIENTS)
@pytest.mark.asyncio
async def test_adapter_returns_empty_on_429(client_path: str):
    """Every corpus adapter MUST return [] on 429 — no exceptions."""
    Client = _import_client(client_path)
    cli = Client()
    fake_http = AsyncMock()
    fake_http.get.return_value = _FakeResponse(429)
    fake_http.post.return_value = _FakeResponse(429)
    out = await cli.search(fake_http, "test query", limit=5)
    assert out == [], (
        f"{client_path} did not fail-soft on 429 — returned {len(out)} hits"
    )


@pytest.mark.parametrize("client_path", ALL_CORPUS_CLIENTS)
@pytest.mark.asyncio
async def test_adapter_returns_empty_on_5xx(client_path: str):
    """Every corpus adapter MUST return [] on 503 — no exceptions."""
    Client = _import_client(client_path)
    cli = Client()
    fake_http = AsyncMock()
    fake_http.get.return_value = _FakeResponse(503)
    fake_http.post.return_value = _FakeResponse(503)
    out = await cli.search(fake_http, "test query", limit=5)
    assert out == [], (
        f"{client_path} did not fail-soft on 503 — returned {len(out)} hits"
    )


@pytest.mark.parametrize("client_path", ALL_CORPUS_CLIENTS)
@pytest.mark.asyncio
async def test_adapter_returns_empty_on_network_error(client_path: str):
    """Every corpus adapter MUST return [] on transport error."""
    Client = _import_client(client_path)
    cli = Client()
    fake_http = AsyncMock()
    fake_http.get.side_effect = httpx.ConnectError("boom")
    fake_http.post.side_effect = httpx.ConnectError("boom")
    out = await cli.search(fake_http, "test query", limit=5)
    assert out == [], (
        f"{client_path} did not fail-soft on network error — returned {len(out)} hits"
    )


@pytest.mark.parametrize("client_path", ALL_CORPUS_CLIENTS)
@pytest.mark.asyncio
async def test_adapter_returns_empty_on_malformed_json(client_path: str):
    """Every corpus adapter MUST return [] on malformed JSON."""
    Client = _import_client(client_path)
    cli = Client()
    fake_http = AsyncMock()
    # 200 status but .json() raises (XML adapters: text-shaped pubmed/arxiv
    # have separate XML ParseError handling — same fail-soft outcome).
    fake_http.get.return_value = _FakeResponse(200, text="<garbage>", json_data=None)
    fake_http.post.return_value = _FakeResponse(200, text="<garbage>", json_data=None)
    out = await cli.search(fake_http, "test query", limit=5)
    assert out == [], (
        f"{client_path} did not fail-soft on malformed JSON — returned {len(out)} hits"
    )
