"""Pytest configuration and shared fixtures.

Snapshot harness — stdlib only, no external snapshot library.

Snapshots live under tests/__snapshots__/<safe-test-name>.txt
Set UPDATE_SNAPSHOTS=1 to (re)write snapshots from current output.

Topic-default for tests
-----------------------
Production code (run_v06_synthesis.py main()) requires an explicit
--topic CLI arg; the orchestrator's module-level QUANT_DIR/PARSED_DIR
are sentinels until _set_topic() runs. The universal-fix-no-hardcoding
rule (2026-05-04) removed the metformin defaults from module-import
time so a missing topic configuration surfaces as an error instead of
silently using metformin papers.

For TEST collection / TEST runtime, however, many existing tests
exercise topic-aware logic (anaphoric-misread detection, change-value
overgroup detection, etc.) on metformin-style paper text without
explicitly setting up a topic context. Those tests rely on the corpus
paths pointing somewhere with real quant_claims data. Setting
TOPIC_DOMAIN=metformin and pre-calling orch._set_topic("metformin") at
conftest-load gives them the expected metformin context. Tests that
need a different topic call _set_topic() inside their own setup;
production code never reaches this fixture.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _install_httpx_test_stub_if_missing() -> None:
    try:
        import httpx  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    import json as _json
    from urllib.parse import urlencode

    class HTTPError(Exception):
        pass

    class HTTPStatusError(HTTPError):
        def __init__(self, message: str, *, response: "Response") -> None:
            super().__init__(message)
            self.response = response

    class ConnectError(HTTPError):
        pass

    class TimeoutException(HTTPError):
        pass

    class ReadTimeout(TimeoutException):
        pass

    class PoolTimeout(TimeoutException):
        pass

    class NetworkError(HTTPError):
        pass

    class RemoteProtocolError(HTTPError):
        pass

    class Request:
        def __init__(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            content: bytes = b"",
        ) -> None:
            self.method = method
            self.url = url
            self.headers = headers or {}
            self.content = content

    class Response:
        def __init__(
            self,
            status_code: int,
            *,
            json: Any = None,
            text: str | None = None,
            content: bytes | None = None,
            headers: dict[str, str] | None = None,
        ) -> None:
            self.status_code = status_code
            self._json = json
            self.headers = headers or {}
            if content is not None:
                self.content = content
                self.text = content.decode("utf-8", errors="replace")
            elif text is not None:
                self.text = text
                self.content = text.encode()
            elif json is not None:
                self.text = _json.dumps(json)
                self.content = self.text.encode()
            else:
                self.text = ""
                self.content = b""

        def json(self) -> Any:
            if self._json is not None:
                return self._json
            return _json.loads(self.text)

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise HTTPStatusError(
                    f"{self.status_code} error response",
                    response=self,
                )

    class MockTransport:
        def __init__(self, handler: Any) -> None:
            self.handler = handler

    def _url(url: str, params: dict[str, Any] | None) -> str:
        if not params:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{urlencode(params, doseq=True)}"

    def _body(json_payload: Any = None, data: Any = None) -> bytes:
        if json_payload is not None:
            return _json.dumps(json_payload).encode()
        if data is None:
            return b""
        return data if isinstance(data, bytes) else str(data).encode()

    class Client:
        def __init__(
            self,
            *,
            transport: MockTransport | None = None,
            headers: dict[str, str] | None = None,
            timeout: float | None = None,
            **_: Any,
        ) -> None:
            self.transport = transport
            self.headers = headers or {}
            self.timeout = timeout

        def request(self, method: str, url: str, **kwargs: Any) -> Response:
            if self.transport is None:
                raise ConnectError("test httpx stub has no transport")
            headers = {**self.headers, **(kwargs.get("headers") or {})}
            req = Request(
                method,
                _url(url, kwargs.get("params")),
                headers=headers,
                content=_body(kwargs.get("json"), kwargs.get("data")),
            )
            return self.transport.handler(req)

        def get(self, url: str, **kwargs: Any) -> Response:
            return self.request("GET", url, **kwargs)

        def post(self, url: str, **kwargs: Any) -> Response:
            return self.request("POST", url, **kwargs)

        def close(self) -> None:
            return None

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: Any) -> None:
            self.close()

    class AsyncClient(Client):
        async def request(self, method: str, url: str, **kwargs: Any) -> Response:
            return super().request(method, url, **kwargs)

        async def get(self, url: str, **kwargs: Any) -> Response:
            return await self.request("GET", url, **kwargs)

        async def post(self, url: str, **kwargs: Any) -> Response:
            return await self.request("POST", url, **kwargs)

        async def aclose(self) -> None:
            return None

        async def __aenter__(self) -> "AsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            await self.aclose()

    stub = ModuleType("httpx")
    for name, value in {
        "AsyncClient": AsyncClient,
        "Client": Client,
        "ConnectError": ConnectError,
        "HTTPError": HTTPError,
        "HTTPStatusError": HTTPStatusError,
        "MockTransport": MockTransport,
        "NetworkError": NetworkError,
        "PoolTimeout": PoolTimeout,
        "ReadTimeout": ReadTimeout,
        "RemoteProtocolError": RemoteProtocolError,
        "Request": Request,
        "Response": Response,
        "TimeoutException": TimeoutException,
    }.items():
        setattr(stub, name, value)
    sys.modules["httpx"] = stub


_install_httpx_test_stub_if_missing()

# Test-only metformin context — see module docstring rationale. This
# only affects test collection + execution; production CLI runs always
# pass through run_v06_synthesis main() which sets TOPIC_DOMAIN from
# the --topic arg before any work.
os.environ.setdefault("TOPIC_DOMAIN", "metformin")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    import run_v06_synthesis as _orch  # noqa: E402
    _orch._set_topic("metformin")
except (ImportError, FileNotFoundError, OSError):
    # Some test environments may not have full corpus on disk —
    # tests that need it will fail with a clear corpus-missing error.
    pass

SNAPSHOT_DIR = Path(__file__).parent / "__snapshots__"
UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"


def _snapshot_path(node_id: str, name: str | None) -> Path:
    """Translate a pytest node id into a stable on-disk filename."""
    safe = node_id.replace("::", "__").replace("/", "_").replace(".py", "")
    if name:
        safe = f"{safe}__{name}"
    return SNAPSHOT_DIR / f"{safe}.txt"


def _serialize(actual: object) -> str:
    if isinstance(actual, str):
        return actual
    return json.dumps(actual, indent=2, sort_keys=True, default=str)


@pytest.fixture
def snapshot(request: pytest.FixtureRequest):
    """Compare a value against a stored snapshot file.

    Usage:
        def test_foo(snapshot):
            snapshot(some_string)
            snapshot(some_dict, name="case1")  # optional label for multiple snapshots
    """

    def _check(actual: object, name: str | None = None) -> None:
        path = _snapshot_path(request.node.nodeid, name)
        rendered = _serialize(actual)
        if not path.exists():
            if not UPDATE:
                raise AssertionError(
                    f"\nSnapshot missing: {path}\n"
                    f"Run with UPDATE_SNAPSHOTS=1 to create the baseline, "
                    f"then commit it.\n"
                    f"--- would-be content ---\n{rendered}\n"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
            return
        if UPDATE:
            path.write_text(rendered, encoding="utf-8")
            return
        expected = path.read_text(encoding="utf-8")
        assert rendered == expected, (
            f"\nSnapshot mismatch: {path}\n"
            f"Run with UPDATE_SNAPSHOTS=1 to refresh.\n"
            f"--- expected ---\n{expected}\n"
            f"--- actual ---\n{rendered}\n"
        )

    return _check


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to tests/fixtures/ — for raw captured API responses."""
    return Path(__file__).parent / "fixtures"
