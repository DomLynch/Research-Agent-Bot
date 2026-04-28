"""Trace-client Protocols + result dataclasses + TraceBackendError.

DESIGN-001 §7: citation-trace must work on VPS and CI without MCP. The
Protocols defined here are the contract `citation_trace.py` consumes —
backends (fixture / httpx / mcp) plug in via runtime selectors in
`trace_clients/__init__.py`.

Hard rule (DESIGN-001 §1): all backends must agree on this contract; only
the transport differs. A backend that reshapes the contract to fit its
favorite API would silently break the trust spine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "TrialStatus",
    "TrialRecord",
    "CompoundRecord",
    "LiteratureRecord",
    "TrialRegistryClient",
    "DrugAliasClient",
    "LiteratureClient",
    "TraceBackendError",
]


# --- Frozen result dataclasses -------------------------------------------

TrialStatus = Literal[
    "recruiting", "active_not_recruiting", "completed",
    "terminated", "withdrawn", "suspended", "unknown",
]


@dataclass(frozen=True, slots=True)
class TrialRecord:
    """One trial-registry row. Returned by `TrialRegistryClient.get_trial`.

    `has_results` is the load-bearing field for citation_trace —
    a `published_results` citation requires `has_results=True`, else
    the trace fails with the protocol-as-results contradiction.
    """

    trial_id: str
    title: str
    status: TrialStatus
    has_results: bool
    phase: str | None = None
    primary_completion_date: str | None = None  # ISO 8601


@dataclass(frozen=True, slots=True)
class CompoundRecord:
    """One ChEMBL compound row. Returned by `DrugAliasClient.lookup`."""

    canonical_name: str
    chembl_id: str | None
    aliases: tuple[str, ...]
    drug_class: str | None = None


@dataclass(frozen=True, slots=True)
class LiteratureRecord:
    """One paper / preprint metadata row. Returned by `LiteratureClient.fetch`."""

    identifier: str  # DOI or PMID
    title: str
    abstract: str
    authors: tuple[str, ...]
    venue: str | None = None
    year: int | None = None


# --- Protocol interfaces (the contract) ----------------------------------


@runtime_checkable
class TrialRegistryClient(Protocol):
    """Contract for trial-registry backends.

    Returns None when the trial id is not in the registry. citation_trace.py
    treats None as a fatal failure for any results-role citation.
    """

    def get_trial(self, trial_id: str) -> TrialRecord | None: ...


@runtime_checkable
class DrugAliasClient(Protocol):
    """Contract for drug-alias backends. Used by `citation_trace.alias_match`."""

    def lookup(self, name_or_alias: str) -> CompoundRecord | None: ...


@runtime_checkable
class LiteratureClient(Protocol):
    """Contract for paper / preprint metadata. Used for citation existence."""

    def fetch(self, doi_or_pmid: str) -> LiteratureRecord | None: ...


# --- Backend errors ------------------------------------------------------


class TraceBackendError(RuntimeError):
    """Raised when a backend cannot serve a request structurally — fixture
    corpus missing, malformed data on disk, http transport error after
    retries, MCP not loaded, etc. Distinct from `None` returns, which
    mean 'record absent' (a legitimate trace-failure signal)."""
