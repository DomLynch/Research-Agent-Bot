"""Opt-in terminal-error telemetry; never pass research or exception data to Sentry."""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentry_sdk import Client
    from sentry_sdk._types import Event

_OPERATIONS = {"status_http", "status_process", "publishing_cycle", "publishing_submit"}
_FAILURES = {"unhandled_exception", "local_gate_execution_failed", "submission_authentication_failed",
             "remote_dedupe_failed", "submit_not_configured", "synthetic_test"}
_ENVIRONMENTS = {"production", "staging", "development", "test"}


@lru_cache(maxsize=1)
def _client() -> Client | None:
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return None
    # Observability failures must not change publishing or mask its original error.
    try:
        from sentry_sdk import Client

        environment = os.environ.get("SENTRY_ENVIRONMENT", "")
        environment = environment if environment in _ENVIRONMENTS else "unspecified"
        release = os.environ.get("SENTRY_RELEASE", "")
        with suppress(OSError, subprocess.SubprocessError):
            release = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", release):
            release = "unknown"

        def allowlist(event: Event, hint: dict[str, Any]) -> Event | None:
            hint.clear()  # Attachments live in hints, outside the event payload.
            tags = event.get("tags", {})
            operation, failure = tags.get("operation"), tags.get("failure")
            if not isinstance(operation, str) or not isinstance(failure, str):
                return None
            if operation not in _OPERATIONS or failure not in _FAILURES:
                return None
            event_id = event.get("event_id", "")
            if not isinstance(event_id, str) or not re.fullmatch(r"[0-9a-f]{32}", event_id):
                return None
            return {
                "event_id": event_id,
                "platform": "python", "level": "error", "message": "V3 synthetic verification" if failure == "synthetic_test" else "V3 terminal technical error",
                "environment": environment, "release": release,
                "tags": {"operation": operation, "failure": failure, "synthetic_test": str(failure == "synthetic_test").lower()},
                "fingerprint": ["v3", operation, failure],
            }

        return Client(
            dsn=dsn, environment=environment, release=release,
            default_integrations=False, auto_enabling_integrations=False, integrations=[],
            send_default_pii=False, include_local_variables=False, include_source_context=False,
            max_request_body_size="never", max_breadcrumbs=0, attach_stacktrace=False,
            traces_sample_rate=0.0, profiles_sample_rate=0.0, profile_session_sample_rate=0.0,
            propagate_traces=False, enable_logs=False, enable_metrics=False,
            before_send_log=lambda *_: None, before_send_metric=lambda *_: None,
            before_send_transaction=lambda *_: None,
            auto_session_tracking=False, send_client_reports=False,
            enable_backpressure_handling=False, spotlight=False, debug=False,
            server_name="", before_send=allowlist, shutdown_timeout=1,
        )
    except Exception:
        return None


def capture_terminal(operation: str, failure: str = "unhandled_exception") -> None:
    with suppress(Exception):  # Telemetry is best-effort, never a publishing dependency.
        if operation not in _OPERATIONS or failure not in _FAILURES:
            return
        client = _client()
        if client is not None:
            # Direct client call, no global/isolation scope, hints, or exception object.
            client.capture_event({"tags": {"operation": operation, "failure": failure}})
            client.flush(timeout=1)


def run_observed(operation: str, main: Callable[[], int]) -> int:
    try:
        return main()
    except Exception:
        capture_terminal(operation)
        raise
