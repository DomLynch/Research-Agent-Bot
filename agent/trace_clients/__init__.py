"""Trace clients package — backend-agnostic interface for citation_trace.py.

Public surface (re-exported for backward compat with the old monolithic
`agent.trace_clients` module):

  Protocols + data:
    TrialRegistryClient, DrugAliasClient, LiteratureClient
    TrialRecord, CompoundRecord, LiteratureRecord, TrialStatus
    TraceBackendError

  Fixture backends (CI / planted-failure regression):
    FixtureTrialRegistryClient, FixtureDrugAliasClient, FixtureLiteratureClient

  Selectors (chosen by `TRACE_BACKEND` env var):
    get_trial_registry_client, get_drug_alias_client, get_literature_client

httpx backends ship in Day 3.3b (`_httpx.py`); MCP backends are optional.
"""
from __future__ import annotations

import os

from agent.trace_clients._fixture import (
    FixtureDrugAliasClient,
    FixtureLiteratureClient,
    FixtureTrialRegistryClient,
)
from agent.trace_clients.protocols import (
    CompoundRecord,
    DrugAliasClient,
    LiteratureClient,
    LiteratureRecord,
    TraceBackendError,
    TrialRecord,
    TrialRegistryClient,
    TrialStatus,
)

__all__ = [
    # Protocols + data
    "TrialRegistryClient",
    "DrugAliasClient",
    "LiteratureClient",
    "TrialRecord",
    "CompoundRecord",
    "LiteratureRecord",
    "TrialStatus",
    "TraceBackendError",
    # Fixture backends
    "FixtureTrialRegistryClient",
    "FixtureDrugAliasClient",
    "FixtureLiteratureClient",
    # Selectors
    "get_trial_registry_client",
    "get_drug_alias_client",
    "get_literature_client",
]


def _backend() -> str:
    """Return the explicitly configured backend; fixtures are test-only."""
    backend = os.environ.get("TRACE_BACKEND", "").strip().lower()
    if not backend:
        raise TraceBackendError(
            "TRACE_BACKEND must be explicitly set to 'http' or 'fixture'",
        )
    if backend == "fixture" and os.environ.get("TRACE_ALLOW_FIXTURES") != "1":
        raise TraceBackendError(
            "TRACE_BACKEND='fixture' requires TRACE_ALLOW_FIXTURES=1",
        )
    return backend


def _unimplemented(backend: str, kind: str) -> TraceBackendError:
    return TraceBackendError(
        f"TRACE_BACKEND={backend!r} for {kind}: not yet implemented. "
        f"Available: 'fixture', 'http'. MCP is optional."
    )


def get_trial_registry_client() -> TrialRegistryClient:
    """Return the explicitly selected TrialRegistryClient."""
    backend = _backend()
    if backend == "fixture":
        return FixtureTrialRegistryClient()
    if backend == "http":
        # Lazy import keeps the fixture path zero-cost on systems without
        # httpx in the import path (httpx is the runtime's only dep, so
        # this is mostly principled tidiness — `_httpx` only loads when
        # the http backend is actually selected).
        from agent.trace_clients._httpx import HttpxTrialRegistryClient
        return HttpxTrialRegistryClient()
    raise _unimplemented(backend, "TrialRegistryClient")


def get_drug_alias_client() -> DrugAliasClient:
    backend = _backend()
    if backend == "fixture":
        return FixtureDrugAliasClient()
    if backend == "http":
        from agent.trace_clients._httpx import HttpxDrugAliasClient
        return HttpxDrugAliasClient()
    raise _unimplemented(backend, "DrugAliasClient")


def get_literature_client() -> LiteratureClient:
    backend = _backend()
    if backend == "fixture":
        return FixtureLiteratureClient()
    if backend == "http":
        from agent.trace_clients._httpx import HttpxLiteratureClient
        return HttpxLiteratureClient()
    raise _unimplemented(backend, "LiteratureClient")
