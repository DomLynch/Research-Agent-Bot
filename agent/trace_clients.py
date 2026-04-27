"""Trace clients — backend-agnostic interface for citation_trace.py.

DESIGN-001 §7 specifies that citation-trace must work on VPS and CI without
MCP availability. This module defines three Protocol interfaces that
citation_trace.py consumes — never the concrete backends. Backend selection
is by the `TRACE_BACKEND` env var (`fixture`, `http`, or `mcp`).

Hard rule (DESIGN-001 §1):
  Citation-trace is the moat. Its correctness must not depend on whether
  the dev environment has MCP loaded or whether a third-party API is up.
  All three backends must agree on the Protocol contract; only the
  transport differs.

For Day 2.4 only the fixture backend is implemented. Day 3 ships
HttpxTrialRegistryClient (direct ClinicalTrials.gov), HttpxDrugAliasClient
(direct ChEMBL), and the MCP-backed variants. The selectors below already
route through the env var so Day 3 can drop in implementations without
changing call sites.

| Protocol            | Backend (Day 2.4 fixture) | Day 3 variants |
|---------------------|---------------------------|----------------|
| TrialRegistryClient | tests/fixtures/trace_clients/trials/*.json   | bio-research:c-trials MCP / clinicaltrials.gov httpx |
| DrugAliasClient     | tests/fixtures/trace_clients/compounds/*.json | bio-research:chembl MCP / ChEMBL httpx |
| LiteratureClient    | tests/fixtures/trace_clients/literature/*.json | bio-research:biorxiv MCP / Europe PMC httpx |
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "TrialRecord",
    "CompoundRecord",
    "LiteratureRecord",
    "TrialRegistryClient",
    "DrugAliasClient",
    "LiteratureClient",
    "FixtureTrialRegistryClient",
    "FixtureDrugAliasClient",
    "FixtureLiteratureClient",
    "TraceBackendError",
    "get_trial_registry_client",
    "get_drug_alias_client",
    "get_literature_client",
]

# --- Frozen result dataclasses --------------------------------------------

TrialStatus = Literal[
    "recruiting", "active_not_recruiting", "completed",
    "terminated", "withdrawn", "suspended", "unknown",
]


@dataclass(frozen=True, slots=True)
class TrialRecord:
    """One trial-registry row. Returned by TrialRegistryClient.get_trial.

    `has_results` is the load-bearing field for citation_trace —
    a published_results citation requires has_results=True.
    """

    trial_id: str
    title: str
    status: TrialStatus
    has_results: bool
    phase: str | None = None
    primary_completion_date: str | None = None  # ISO 8601


@dataclass(frozen=True, slots=True)
class CompoundRecord:
    """One ChEMBL compound row. Returned by DrugAliasClient.lookup."""

    canonical_name: str
    chembl_id: str | None
    aliases: tuple[str, ...]
    drug_class: str | None = None


@dataclass(frozen=True, slots=True)
class LiteratureRecord:
    """One paper / preprint metadata row. Returned by LiteratureClient.fetch."""

    identifier: str  # DOI or PMID
    title: str
    abstract: str
    authors: tuple[str, ...]
    venue: str | None = None
    year: int | None = None


# --- Protocol interfaces (the contract) -----------------------------------


@runtime_checkable
class TrialRegistryClient(Protocol):
    """Contract for trial-registry backends.

    Returns None when the trial id is not in the registry. citation_trace.py
    treats None as a fatal failure for any results-role citation.
    """

    def get_trial(self, trial_id: str) -> TrialRecord | None: ...


@runtime_checkable
class DrugAliasClient(Protocol):
    """Contract for drug-alias backends. Used by citation_trace.alias_match."""

    def lookup(self, name_or_alias: str) -> CompoundRecord | None: ...


@runtime_checkable
class LiteratureClient(Protocol):
    """Contract for paper / preprint metadata. Used for citation existence."""

    def fetch(self, doi_or_pmid: str) -> LiteratureRecord | None: ...


# --- Fixture-backed implementations (Day 2.4 ships these only) ------------


_FIXTURES_ROOT = (
    Path(__file__).resolve().parent.parent
    / "tests" / "fixtures" / "trace_clients"
)


class TraceBackendError(RuntimeError):
    """Raised when a fixture is malformed or the env-selected backend
    cannot serve a request (e.g., http/mcp backends not yet implemented)."""


def _safe_filename(stem: str) -> str:
    """Translate a registry id / DOI into a filesystem-safe stem.

    DOIs contain '/' which is illegal in filenames; replaced with '__'
    so e.g. '10.1111/acel.13039' → '10.1111__acel.13039'. The same
    convention is used in tests/fixtures/trace_clients/literature/.
    """
    return stem.replace("/", "__")


def _read_fixture(directory: str, stem: str) -> dict | None:
    """Return parsed JSON for `directory/<stem>.json`, or None if missing."""
    path = _FIXTURES_ROOT / directory / f"{_safe_filename(stem)}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise TraceBackendError(f"malformed fixture at {path}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class FixtureTrialRegistryClient:
    """Reads trial records from `tests/fixtures/trace_clients/trials/*.json`.

    Used by CI/dev. Day 3 adds HttpxTrialRegistryClient (direct API) and
    MCPTrialRegistryClient (via bio-research:c-trials).
    """

    def get_trial(self, trial_id: str) -> TrialRecord | None:
        data = _read_fixture("trials", trial_id.strip())
        if data is None:
            return None
        return TrialRecord(
            trial_id=data["trial_id"],
            title=data["title"],
            status=data["status"],
            has_results=bool(data["has_results"]),
            phase=data.get("phase"),
            primary_completion_date=data.get("primary_completion_date"),
        )


@dataclass(frozen=True, slots=True)
class FixtureDrugAliasClient:
    """Reads compound records from `tests/fixtures/trace_clients/compounds/*.json`.

    Lookup is case-insensitive: a fixture with canonical_name='metformin'
    AND aliases including 'Glucophage' will match all of {'metformin',
    'METFORMIN', 'glucophage', 'Glucophage'}. Returns None for any
    unknown name (including the planted 'Glufomin' fixture absence —
    that's how case 4's external layer catches the drift).
    """

    def lookup(self, name_or_alias: str) -> CompoundRecord | None:
        candidate = name_or_alias.strip().lower()
        # Try canonical-name lookup first (most fixtures filed under canonical).
        data = _read_fixture("compounds", candidate)
        if data is None:
            # Scan all fixtures for any whose aliases include the candidate.
            compounds_dir = _FIXTURES_ROOT / "compounds"
            if not compounds_dir.exists():
                return None
            for path in compounds_dir.glob("*.json"):
                with path.open("r", encoding="utf-8") as fh:
                    fixture = json.load(fh)
                aliases_lower = {a.lower() for a in fixture.get("aliases", [])}
                if (
                    fixture["canonical_name"].lower() == candidate
                    or candidate in aliases_lower
                ):
                    data = fixture
                    break
        if data is None:
            return None
        return CompoundRecord(
            canonical_name=data["canonical_name"],
            chembl_id=data.get("chembl_id"),
            aliases=tuple(data.get("aliases", ())),
            drug_class=data.get("drug_class"),
        )


@dataclass(frozen=True, slots=True)
class FixtureLiteratureClient:
    """Reads paper/preprint records from `tests/fixtures/trace_clients/literature/*.json`.

    Identifier accepts either DOI or PMID. The fixture filename uses the
    DOI with '/' → '__'.
    """

    def fetch(self, doi_or_pmid: str) -> LiteratureRecord | None:
        data = _read_fixture("literature", doi_or_pmid.strip())
        if data is None:
            return None
        return LiteratureRecord(
            identifier=data["identifier"],
            title=data["title"],
            abstract=data["abstract"],
            authors=tuple(data.get("authors", ())),
            venue=data.get("venue"),
            year=data.get("year"),
        )


# --- Backend selectors ----------------------------------------------------


def _backend() -> str:
    """Return the active TRACE_BACKEND. Default `fixture`."""
    return os.environ.get("TRACE_BACKEND", "fixture").strip().lower()


def _unimplemented(backend: str, kind: str) -> "TraceBackendError":
    return TraceBackendError(
        f"TRACE_BACKEND={backend!r} for {kind}: not implemented in Day 2.4. "
        f"Day 3 ships httpx + MCP backends."
    )


def get_trial_registry_client() -> TrialRegistryClient:
    """Return the active TrialRegistryClient.

    Day 2.4 supports only `fixture`. Day 3 will add `http` and `mcp` paths
    here without touching call sites in citation_trace.py.
    """
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
