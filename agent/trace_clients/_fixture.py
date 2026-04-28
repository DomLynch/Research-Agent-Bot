"""Fixture-backed trace-client implementations.

Reads from `tests/fixtures/trace_clients/{trials,compounds,literature}/*.json`.
Used by CI / dev / planted-failure regression tests. Keeps citation_trace
functional without external API access.

Distinguishes two failure modes:
  - File missing (record absent) → returns None. This is the normal
    'planted case 2 fabricated NCT' / 'case 4 alias drift' signal.
  - Corpus subdirectory missing entirely → raises TraceBackendError.
    A packaged runtime without the fixtures dir would otherwise silently
    return None for every lookup, making citation_trace falsely report
    every real id as fabricated. Operational guidance baked into the
    error: set TRACE_BACKEND=http or =mcp.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent.trace_clients.protocols import (
    CompoundRecord,
    LiteratureRecord,
    TraceBackendError,
    TrialRecord,
)

__all__ = [
    "FixtureTrialRegistryClient",
    "FixtureDrugAliasClient",
    "FixtureLiteratureClient",
]

_FIXTURES_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "tests" / "fixtures" / "trace_clients"
)


def _safe_filename(stem: str) -> str:
    """Translate a registry id / DOI into a filesystem-safe stem.

    DOIs contain '/' which is illegal in filenames; replaced with '__'
    so e.g. '10.1111/acel.13039' → '10.1111__acel.13039'. Same convention
    is used in the fixtures on disk.
    """
    return stem.replace("/", "__")


def _read_fixture(directory: str, stem: str) -> dict | None:
    """Return parsed JSON for `directory/<stem>.json`, or None if missing.

    Raises TraceBackendError when the corpus subdirectory is absent —
    that's a configuration error (different from 'record not found').
    """
    dir_path = _FIXTURES_ROOT / directory
    if not dir_path.exists():
        raise TraceBackendError(
            f"fixture corpus subdirectory missing: {dir_path}. "
            f"This is NOT 'record not found' (returns None); it's "
            f"'corpus not configured'. In packaged runtimes, set "
            f"TRACE_BACKEND=http or =mcp. The fixture backend requires "
            f"tests/fixtures/trace_clients/{{trials,compounds,literature}}/ "
            f"to exist."
        )
    path = dir_path / f"{_safe_filename(stem)}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise TraceBackendError(f"malformed fixture at {path}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class FixtureTrialRegistryClient:
    """Reads trial records from `tests/fixtures/trace_clients/trials/*.json`."""

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
    AND aliases including 'Glucophage' matches all of {'metformin',
    'METFORMIN', 'glucophage', 'Glucophage'}. Returns None for any
    unknown name (including planted 'Glufomin' fixture absence — that's
    how case 4's external layer catches the drift).
    """

    def lookup(self, name_or_alias: str) -> CompoundRecord | None:
        candidate = name_or_alias.strip().lower()
        # Canonical-name lookup first. _read_fixture raises if the
        # compounds/ directory is missing entirely — that's a
        # configuration error, not a miss.
        data = _read_fixture("compounds", candidate)
        if data is None:
            # Canonical file absent — scan all fixtures for any whose
            # aliases include the candidate. The compounds/ directory
            # is guaranteed to exist at this point because _read_fixture
            # would have raised if it didn't.
            compounds_dir = _FIXTURES_ROOT / "compounds"
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

    Identifier accepts either DOI or PMID. Filename uses DOI with `/` → `__`.
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
