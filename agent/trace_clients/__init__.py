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
    """Return the active TRACE_BACKEND. Default `fixture`."""
    return os.environ.get("TRACE_BACKEND", "fixture").strip().lower()


def _unimplemented(backend: str, kind: str) -> TraceBackendError:
    return TraceBackendError(
        f"TRACE_BACKEND={backend!r} for {kind}: not yet implemented. "
        f"Day 3.3b ships httpx; MCP is optional."
    )


def get_trial_registry_client() -> TrialRegistryClient:
    """Return the active TrialRegistryClient. Defaults to fixture."""
    backend = _backend()
    if backend == "fixture":
        return FixtureTrialRegistryClient()
    raise _unimplemented(backend, "TrialRegistryClient")


def get_drug_alias_client() -> DrugAliasClient:
    backend = _backend()
    if backend == "fixture":
        return FixtureDrugAliasClient()
    raise _unimplemented(backend, "DrugAliasClient")


def get_literature_client() -> LiteratureClient:
    backend = _backend()
    if backend == "fixture":
        return FixtureLiteratureClient()
    raise _unimplemented(backend, "LiteratureClient")
