from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from agent.sources.unpaywall import UNPAYWALL_API, UnpaywallAdapter


@pytest.fixture
def adapter():
    return UnpaywallAdapter()


def _mock_response(*, status_code: int = 200, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=json_body or {}, request=httpx.Request("GET", "https://example.com"))


class TestUnpaywallAdapterResolve:
    def test_returns_oa_location(self, adapter):
        body = {
            "is_oa": True,
            "best_oa_location": {
                "url": "https://example.com/paper.pdf",
                "version": "publishedVersion",
                "license": "cc-by",
                "host_type": "publisher",
            },
        }
        with patch.object(adapter.client, "get", return_value=_mock_response(json_body=body)) as mock_get:
            result = adapter.resolve("10.1234/test")
        assert result is not None
        assert result["oa_url"] == "https://example.com/paper.pdf"
        assert result["version"] == "publishedVersion"
        assert result["license"] == "cc-by"
        assert result["host_type"] == "publisher"
        assert result["is_oa"] is True
        assert result["doi"] == "10.1234/test"
        mock_get.assert_called_once()
        assert mock_get.call_args[0][0] == f"{UNPAYWALL_API}/10.1234/test"

    def test_returns_none_for_404(self, adapter):
        with patch.object(adapter.client, "get", return_value=_mock_response(status_code=404)):
            assert adapter.resolve("10.9999/nosuchdoi") is None

    def test_returns_none_for_no_best_oa(self, adapter):
        body = {"is_oa": False, "best_oa_location": None}
        with patch.object(adapter.client, "get", return_value=_mock_response(json_body=body)):
            assert adapter.resolve("10.1234/paywalled") is None

    def test_returns_none_for_empty_string_doi(self, adapter):
        with patch.object(adapter.client, "get") as mock_get:
            assert adapter.resolve("") is None
            mock_get.assert_not_called()

    def test_returns_none_on_http_error(self, adapter):
        with patch.object(adapter.client, "get", side_effect=httpx.ConnectError("network down")):
            assert adapter.resolve("10.1234/err") is None

    def test_returns_none_on_server_error(self, adapter):
        with patch.object(adapter.client, "get", return_value=_mock_response(status_code=500)):
            assert adapter.resolve("10.1234/servererr") is None

    def test_missing_url_field(self, adapter):
        body = {
            "is_oa": True,
            "best_oa_location": {
                "url": None,
                "version": "acceptedVersion",
            },
        }
        with patch.object(adapter.client, "get", return_value=_mock_response(json_body=body)):
            result = adapter.resolve("10.1234/nourl")
        assert result is not None
        assert result["oa_url"] is None
        assert result["license"] is None


class TestUnpaywallAdapterInit:
    def test_default_timeout(self):
        a = UnpaywallAdapter()
        assert a.client.timeout.connect == 12.0

    def test_custom_timeout(self):
        a = UnpaywallAdapter(timeout_sec=5.0)
        assert a.client.timeout.connect == 5.0

    def test_transport_injection(self):
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
        a = UnpaywallAdapter(transport=transport)
        with patch.object(a.client, "get", return_value=_mock_response(status_code=404)):
            assert a.resolve("10.1234/x") is None
