"""Real SDK envelopes and actual CLI/HTTP boundaries; no Sentry network calls."""
from __future__ import annotations

import http.client
import logging
import os
import runpy
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import sentry_sdk
from sentry_sdk import logger, metrics
from sentry_sdk.attachments import Attachment
from sentry_sdk.transport import Transport

from agent import app, observability

ROOT = Path(__file__).resolve().parents[1]
SECRET = "PRIVATE-prompt-manuscript-evidence-member-auth@example.test"


class MemoryTransport(Transport):
    def __init__(self):
        super().__init__()
        self.envelopes = []
        self.received = threading.Event()

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)
        self.received.set()


@pytest.fixture
def telemetry(monkeypatch):
    observability._client.cache_clear()
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTRY_RELEASE", subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
    transport = MemoryTransport()
    real_client = sentry_sdk.Client
    monkeypatch.setattr(sentry_sdk, "Client", lambda **options: real_client(transport=transport, **options))
    yield transport
    client = observability._client()
    if client is not None:
        client.close()
    observability._client.cache_clear()


def test_real_sdk_envelope_strict_allowlist_and_ambient_isolation(telemetry, monkeypatch):
    monkeypatch.setenv("SENTRY_SERVER_NAME", SECRET)
    before_active = sentry_sdk.get_client().is_active()
    with sentry_sdk.isolation_scope() as isolation, sentry_sdk.new_scope() as current:
        before_client = sentry_sdk.Client(
            dsn="https://public@example.invalid/2", default_integrations=False,
            auto_enabling_integrations=False, enable_logs=False, enable_metrics=False,
        )
        current.set_client(before_client)
        for scope in (isolation, current):
            scope.set_user({"email": SECRET})
            scope.set_tag("private", SECRET)
            scope.set_extra("prompt", SECRET)
            scope.set_context("trace", {"dynamic_sampling_context": {"secret": SECRET}})
            scope.add_attachment(bytes=SECRET.encode(), filename=SECRET)
        sentry_sdk.add_breadcrumb(message=SECRET)
        logging.getLogger("test.observability").error(SECRET)
        try:
            raise RuntimeError(SECRET)
        except RuntimeError:
            observability.capture_terminal("publishing_cycle")
        assert sentry_sdk.get_client() is before_client
        before_client.close()
    client = observability._client()
    assert client is not before_client
    assert sentry_sdk.get_client().is_active() == before_active
    assert client.integrations == {}
    assert len(telemetry.envelopes) == 1
    envelope = telemetry.envelopes[0]
    wire = envelope.serialize()
    assert SECRET.encode() not in wire
    assert set(envelope.headers) == {"event_id", "sent_at"}
    assert [item.headers["type"] for item in envelope.items] == ["event"]
    event = envelope.items[0].payload.json
    assert set(event) == {"event_id", "platform", "level", "message", "environment", "release", "tags", "fingerprint"}
    assert event["tags"] == {"operation": "publishing_cycle", "failure": "unhandled_exception"}
    assert event["release"] == subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assert event["environment"] == "test"
    assert event["event_id"] == envelope.headers["event_id"]
    assert len(event["event_id"]) == 32
    for option in ("default_integrations", "auto_enabling_integrations", "send_default_pii",
                   "include_local_variables", "include_source_context", "attach_stacktrace",
                   "propagate_traces", "enable_logs", "enable_metrics", "auto_session_tracking",
                   "send_client_reports", "enable_backpressure_handling", "spotlight"):
        assert client.options[option] is False
    for option in ("max_breadcrumbs", "traces_sample_rate", "profiles_sample_rate", "profile_session_sample_rate"):
        assert client.options[option] == 0


def test_before_send_drops_sensitive_fields_and_attachment_hints(telemetry):
    client = observability._client()
    dirty = {key: {"private": SECRET} for key in (
        "exception", "request", "user", "extra", "contexts", "breadcrumbs", "threads",
        "stacktrace", "modules", "sdk", "logentry", "_meta",
    )}
    dirty.update(tags={"operation": "status_http", "failure": "unhandled_exception", "private": SECRET},
                 message=SECRET, transaction=SECRET, server_name=SECRET, environment=SECRET, release=SECRET)
    client.capture_event(dirty, hint={"attachments": [Attachment(bytes=SECRET.encode(), filename=SECRET)]})
    assert len(telemetry.envelopes) == 1
    assert SECRET.encode() not in telemetry.envelopes[0].serialize()
    assert len(telemetry.envelopes[0].items) == 1


def test_sdk_log_metric_and_transaction_envelopes_are_dropped(telemetry):
    client = observability._client()
    with sentry_sdk.new_scope() as scope:
        scope.set_client(client)
        logger.error(SECRET)
        metrics.count(SECRET, 1, attributes={"private": SECRET})
    client.capture_event({"type": "transaction", "transaction": SECRET})
    client.flush(timeout=1)
    assert not telemetry.envelopes


def test_cli_imports_are_identical_to_implementation_modules():
    import daily_research_paper_cycle
    import daily_research_paper_submit
    from publishing import fresh_lane, submission
    assert daily_research_paper_cycle is fresh_lane
    assert daily_research_paper_submit is submission
    assert daily_research_paper_cycle.run_cycle is fresh_lane.run_cycle
    assert daily_research_paper_submit.run_cycle is submission.run_cycle


@pytest.mark.parametrize("dsn", [None, "", "  "])
def test_disabled_config_never_constructs_sdk(telemetry, monkeypatch, dsn):
    if dsn is None:
        monkeypatch.delenv("SENTRY_DSN")
    else:
        monkeypatch.setenv("SENTRY_DSN", dsn)
    def forbidden(**_options):
        pytest.fail("disabled configuration initialized Sentry")
    monkeypatch.setattr(sentry_sdk, "Client", forbidden)
    assert observability.run_observed("publishing_cycle", lambda: 0) == 0
    observability.capture_terminal("status_http")
    assert observability._client() is None
    assert not telemetry.envelopes


def test_invalid_dsn_and_environment_fail_closed(telemetry, monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "not-a-dsn")
    from sentry_sdk.client import Client
    with monkeypatch.context() as patch:
        patch.setattr(sentry_sdk, "Client", Client)
        assert observability.run_observed("publishing_submit", lambda: 3) == 3
        assert observability._client() is None
    observability._client.cache_clear()
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", SECRET)
    monkeypatch.setenv("SENTRY_RELEASE", SECRET)
    def no_checkout(*_args, **_kwargs):
        raise OSError("Git unavailable")
    monkeypatch.setattr(observability.subprocess, "check_output", no_checkout)
    observability.capture_terminal("status_process")
    event = telemetry.envelopes[0].items[0].payload.json
    assert event["environment"] == "unspecified"
    assert event["release"] == "unknown"
    assert SECRET.encode() not in telemetry.envelopes[0].serialize()


@pytest.mark.parametrize("entrypoint,module,operation", [
    ("daily_research_paper_cycle.py", "publishing.fresh_lane", "publishing_cycle"),
    ("daily_research_paper_submit.py", "publishing.submission", "publishing_submit"),
])
def test_real_publishing_cli_captures_and_preserves_exception(telemetry, monkeypatch, entrypoint, module, operation):
    import importlib
    implementation = importlib.import_module(module)
    original = RuntimeError(SECRET)
    def failed_main():
        raise original
    monkeypatch.setattr(implementation, "main", failed_main)
    with pytest.raises(RuntimeError) as caught:
        runpy.run_path(str(ROOT / "scripts" / entrypoint), run_name="__main__")
    assert caught.value is original
    assert len(telemetry.envelopes) == 1
    assert telemetry.envelopes[0].items[0].payload.json["tags"]["operation"] == operation
    assert SECRET.encode() not in telemetry.envelopes[0].serialize()


@pytest.mark.parametrize("status", ["submission_revise_requested", "submission_rejected_by_researka", "submission_failed", "no_revise_pending"])
def test_real_cycle_cli_keeps_scientific_and_scheduled_retry_results(telemetry, monkeypatch, tmp_path, status):
    from publishing import fresh_lane
    ledger = {"status": status, "submitted": 0, "published": 0, "retryable": True}
    monkeypatch.setattr(fresh_lane, "run_cycle", lambda **_kwargs: ledger)
    monkeypatch.setattr(sys, "argv", ["cycle", "--submit", "--mode", "revise", "--runs-root", str(tmp_path)])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / "scripts/daily_research_paper_cycle.py"), run_name="__main__")
    assert result.value.code == (2 if status == "submission_failed" else 0 if status == "no_revise_pending" else 3)
    assert not telemetry.envelopes
    assert ledger["status"] == status


def test_terminal_execution_exit_is_captured_once(telemetry, monkeypatch):
    from publishing import fresh_lane
    monkeypatch.setattr(fresh_lane, "run_cycle", lambda **_k: {"status": "local_gate_execution_failed", "submitted": 0, "published": 0})
    monkeypatch.setattr(sys, "argv", ["cycle"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / "scripts/daily_research_paper_cycle.py"), run_name="__main__")
    assert result.value.code == os.EX_SOFTWARE
    assert len(telemetry.envelopes) == 1
    assert telemetry.envelopes[0].items[0].payload.json["tags"]["failure"] == "local_gate_execution_failed"


def test_telemetry_failure_never_changes_publishing_result_or_exception(telemetry, monkeypatch):
    client = observability._client()
    def unavailable(*_args, **_kwargs):
        raise OSError("transport unavailable")
    original = RuntimeError(SECRET)
    def failed():
        raise original
    with monkeypatch.context() as patch:
        patch.setattr(client, "capture_event", unavailable)
        patch.setattr(client, "flush", unavailable)
        assert observability.run_observed("publishing_cycle", lambda: os.EX_SOFTWARE) == os.EX_SOFTWARE
        with pytest.raises(RuntimeError) as caught:
            observability.run_observed("publishing_submit", failed)
    assert caught.value is original


def test_http_thread_exception_captured_and_server_still_serves(telemetry, monkeypatch):
    original = app._LiveHandler.do_GET
    def fail(_self):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(app._LiveHandler, "do_GET", fail)
    server = app._LiveServer(("127.0.0.1", 0), app._LiveHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=2)
    try:
        connection.request("GET", "/" + SECRET, headers={"Authorization": SECRET})
        with pytest.raises(http.client.RemoteDisconnected):
            connection.getresponse()
        assert telemetry.received.wait(2)
        assert len(telemetry.envelopes) == 1
        assert telemetry.envelopes[0].items[0].payload.json["tags"]["operation"] == "status_http"
        assert SECRET.encode() not in telemetry.envelopes[0].serialize()
        monkeypatch.setattr(app._LiveHandler, "do_GET", original)
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        assert b"Research Agent service live" in response.read()
        assert len(telemetry.envelopes) == 1
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_status_process_startup_error_is_preserved(telemetry, monkeypatch):
    original = OSError(SECRET)
    def failed(_args):
        raise original
    monkeypatch.setattr(app, "_dashboard", failed)
    with pytest.raises(OSError) as caught:
        app.main(["dashboard"])
    assert caught.value is original
    assert telemetry.envelopes[0].items[0].payload.json["tags"]["operation"] == "status_process"


@pytest.mark.parametrize("status,code", [("remote_dedupe_failed", 2), ("submit_not_configured", 2), ("submission_authentication_failed", 3)])
def test_cycle_reports_operational_failures_without_ledger_details(telemetry, monkeypatch, tmp_path, status, code):
    from publishing import fresh_lane
    monkeypatch.setattr(fresh_lane, "run_cycle", lambda **_k: {"status": status, "submitted": 0, "published": 0, "reason": SECRET})
    monkeypatch.setattr(sys, "argv", ["cycle", "--submit", "--mode", "revise", "--runs-root", str(tmp_path)])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / "scripts/daily_research_paper_cycle.py"), run_name="__main__")
    assert result.value.code == code
    assert len(telemetry.envelopes) == 1
    assert telemetry.envelopes[0].items[0].payload.json["tags"]["failure"] == status
    assert SECRET.encode() not in telemetry.envelopes[0].serialize()


def test_release_prefers_checkout_over_stale_configuration(telemetry, monkeypatch):
    monkeypatch.setenv("SENTRY_RELEASE", "0" * 40)
    observability.capture_terminal("status_process", "synthetic_test")
    event = telemetry.envelopes[0].items[0].payload.json
    assert event["release"] == subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assert event["message"] == "V3 synthetic verification"
