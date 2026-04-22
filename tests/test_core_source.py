from __future__ import annotations

from pathlib import Path

import httpx

from agent.sources.core import COREClient


def test_core_no_api_key_is_noop(tmp_path: Path) -> None:
    client = COREClient(cache_dir=tmp_path, api_key="")
    assert client.fetch_by_doi("10.1/test") is None


def test_core_fetches_text_when_available(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"fullText": "Methods and results in older adults.", "downloadUrl": "https://example.org/paper.pdf"}]},
        )

    client = COREClient(cache_dir=tmp_path, api_key="key", transport=httpx.MockTransport(handler))
    payload = client.fetch_by_doi("10.1/test")
    assert payload
    assert payload["found"] is True
    assert "older adults" in payload["text"]
    assert payload["download_url"] == "https://example.org/paper.pdf"


def test_core_returns_none_on_404(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    client = COREClient(cache_dir=tmp_path, api_key="key", transport=httpx.MockTransport(handler))
    assert client.fetch_by_doi("10.1/missing") is None


def test_core_cache_hit_avoids_second_network_call(tmp_path: Path) -> None:
    counter = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["calls"] += 1
        return httpx.Response(200, json={"results": [{"fullText": "Cached core text.", "downloadUrl": ""}]})

    client = COREClient(cache_dir=tmp_path, api_key="key", transport=httpx.MockTransport(handler))
    first = client.fetch_by_doi("10.1/cache")
    second = client.fetch_by_doi("10.1/cache")
    assert first == second
    assert counter["calls"] == 1


def test_core_bad_json_raises(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = COREClient(cache_dir=tmp_path, api_key="key", transport=httpx.MockTransport(handler))
    try:
        client.fetch_by_doi("10.1/bad")
    except ValueError:
        return
    raise AssertionError("Expected ValueError for invalid CORE JSON response")
