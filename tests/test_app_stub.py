from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from typing import Iterator

from agent import app


@contextmanager
def _serve_status_app() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), app._LiveHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get(url: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read(),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def test_live_status_copy_is_current() -> None:
    body = app._LIVE_HTML
    assert "Research Agent service live" in body
    assert "claim graphs, manifests, verdict JSON" in body
    assert "Proof 001" not in body
    assert "Day 5" not in body


def test_live_status_http_surface_is_explicit() -> None:
    with _serve_status_app() as base:
        root_status, root_type, root_body = _get(f"{base}/")
        health_status, health_type, health_body = _get(f"{base}/health")
        openapi_status, openapi_type, openapi_body = _get(f"{base}/openapi.json")
        docs_status, docs_type, docs_body = _get(f"{base}/docs")

    assert root_status == 200
    assert root_type.startswith("text/html")
    assert b"Research Agent service live" in root_body

    assert health_status == 200
    assert health_type == "application/json"
    health = json.loads(health_body)
    assert health["status"] == "ok"
    assert health["http_surface"] == "deploy-status-only"
    assert "scripts/run_v06_synthesis.py" in health["synthesis_entrypoints"]

    assert openapi_status == 404
    assert openapi_type == "application/json"
    assert json.loads(openapi_body)["error"] == "not_found"

    assert docs_status == 404
    assert docs_type == "application/json"
    assert json.loads(docs_body)["error"] == "not_found"


def test_run_command_points_to_active_synthesis_entrypoints(capsys) -> None:
    rc = app.main(["run", "--topic", "rapamycin"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "scripts/run_v06_synthesis.py" in captured.err
    assert "Proof 001" not in captured.err
