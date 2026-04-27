"""Tests for agent/trace_clients.py — Protocol shapes + fixture backends + selectors.

Day 2.4 ships only the fixture backend; httpx + MCP backends are Day 3. The
selector tests here verify that http/mcp routes correctly raise
TraceBackendError so future Day 3 work can drop in implementations without
changing call sites.

Planted cases 2 (fabricated NCT) and 4 (alias drift) are exercised here at
the BACKEND layer. Day 3's citation_trace.py will combine these with the
Protocol contract to produce CitationTrace records.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from agent.trace_clients import (
    CompoundRecord,
    DrugAliasClient,
    FixtureDrugAliasClient,
    FixtureLiteratureClient,
    FixtureTrialRegistryClient,
    LiteratureClient,
    LiteratureRecord,
    TraceBackendError,
    TrialRecord,
    TrialRegistryClient,
    get_drug_alias_client,
    get_literature_client,
    get_trial_registry_client,
)

FIXTURES_ROOT = (
    Path(__file__).parent / "fixtures" / "trace_clients"
)


# --- Protocol structural conformance --------------------------------------


def test_fixture_trial_client_satisfies_protocol() -> None:
    assert isinstance(FixtureTrialRegistryClient(), TrialRegistryClient)


def test_fixture_drug_client_satisfies_protocol() -> None:
    assert isinstance(FixtureDrugAliasClient(), DrugAliasClient)


def test_fixture_literature_client_satisfies_protocol() -> None:
    assert isinstance(FixtureLiteratureClient(), LiteratureClient)


# --- Frozen dataclass guarantees ------------------------------------------


def test_trial_record_is_frozen() -> None:
    rec = TrialRecord(trial_id="X", title="Y", status="completed", has_results=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.title = "mutated"  # type: ignore[misc]


def test_compound_record_is_frozen() -> None:
    rec = CompoundRecord(canonical_name="metformin", chembl_id="CHEMBL1431",
                         aliases=("metformin",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.canonical_name = "mut"  # type: ignore[misc]


def test_literature_record_is_frozen() -> None:
    rec = LiteratureRecord(identifier="X", title="Y", abstract="Z", authors=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.title = "mut"  # type: ignore[misc]


# --- TrialRegistryClient — fixture backend --------------------------------


def test_tame_pinned_to_recruiting_no_results() -> None:
    """TAME (NCT04264897) is the canonical 'protocol-as-results' bait. The
    fixture pins status='recruiting' and has_results=False so the Day 3
    citation_trace catches any 'TAME demonstrated...' citation."""
    client = FixtureTrialRegistryClient()
    rec = client.get_trial("NCT04264897")
    assert rec is not None
    assert rec.status == "recruiting"
    assert rec.has_results is False


def test_masters_completed_with_results() -> None:
    client = FixtureTrialRegistryClient()
    rec = client.get_trial("NCT02308228")
    assert rec is not None and rec.status == "completed" and rec.has_results is True


def test_met_prevent_isrctn_lookup() -> None:
    """ISRCTN identifier path (vs NCT) — the fixture file uses the literal
    `ISRCTN29932357` stem since registry IDs of this form go straight to
    the trials directory."""
    client = FixtureTrialRegistryClient()
    rec = client.get_trial("ISRCTN29932357")
    assert rec is not None and rec.has_results is True


def test_planted_case_2_fabricated_nct_returns_none() -> None:
    """NCT99999999 is the planted case 2 fixture absence. Day 3's
    citation_trace.trace_nct will translate this None into a
    `passed=False, code=NCT_NOT_FOUND` CitationTrace."""
    client = FixtureTrialRegistryClient()
    assert client.get_trial("NCT99999999") is None


def test_trial_lookup_strips_whitespace() -> None:
    client = FixtureTrialRegistryClient()
    rec = client.get_trial("  NCT04264897  ")
    assert rec is not None


# --- DrugAliasClient — fixture backend ------------------------------------


def test_metformin_canonical_lookup() -> None:
    client = FixtureDrugAliasClient()
    rec = client.lookup("metformin")
    assert rec is not None
    assert rec.canonical_name == "metformin"
    assert rec.chembl_id == "CHEMBL1431"
    assert "Glucophage" in rec.aliases


def test_metformin_lookup_is_case_insensitive() -> None:
    client = FixtureDrugAliasClient()
    rec = client.lookup("METFORMIN")
    assert rec is not None and rec.canonical_name == "metformin"


def test_glucophage_alias_resolves_to_metformin() -> None:
    """Aliases listed inside metformin.json should resolve to the same
    canonical record."""
    client = FixtureDrugAliasClient()
    rec = client.lookup("Glucophage")
    assert rec is not None
    assert rec.canonical_name == "metformin"


def test_planted_case_4_glufomin_returns_none() -> None:
    """Glufomin is NOT in metformin.json's aliases. Day 3's
    citation_trace.trace_drug_alias will translate this into a
    `passed=False, code=ALIAS_NOT_IN_REGISTRY` CitationTrace."""
    client = FixtureDrugAliasClient()
    assert client.lookup("Glufomin") is None


def test_drug_lookup_strips_whitespace() -> None:
    client = FixtureDrugAliasClient()
    rec = client.lookup("  Glucophage  ")
    assert rec is not None and rec.canonical_name == "metformin"


# --- LiteratureClient — fixture backend -----------------------------------


def test_masters_paper_lookup_by_doi() -> None:
    client = FixtureLiteratureClient()
    rec = client.fetch("10.1111/acel.13039")
    assert rec is not None
    assert rec.year == 2019
    assert rec.venue == "Aging Cell"
    assert "MASTERS" in rec.title


def test_masters_paper_abstract_carries_quality_signals() -> None:
    """The fixture preserves the load-bearing prose from the gold passages
    in docs/quality-reference/metformin/README.md — explicit negative
    finding, p<.001 numeric, no spin."""
    client = FixtureLiteratureClient()
    rec = client.fetch("10.1111/acel.13039")
    assert rec is not None
    assert "negatively impacts the hypertrophic response" in rec.abstract
    assert "p < .001" in rec.abstract or "p<.001" in rec.abstract


def test_unknown_doi_returns_none() -> None:
    client = FixtureLiteratureClient()
    assert client.fetch("10.0000/nonexistent") is None


# --- Backend selectors ----------------------------------------------------


def test_default_backend_is_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACE_BACKEND", raising=False)
    assert isinstance(get_trial_registry_client(), FixtureTrialRegistryClient)
    assert isinstance(get_drug_alias_client(), FixtureDrugAliasClient)
    assert isinstance(get_literature_client(), FixtureLiteratureClient)


def test_explicit_fixture_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACE_BACKEND", "fixture")
    assert isinstance(get_trial_registry_client(), FixtureTrialRegistryClient)


def test_http_backend_not_yet_implemented(monkeypatch: pytest.MonkeyPatch) -> None:
    """Day 3 will implement; Day 2.4 raises so call sites fail loud
    instead of silently using a wrong backend."""
    monkeypatch.setenv("TRACE_BACKEND", "http")
    for getter in (get_trial_registry_client, get_drug_alias_client,
                   get_literature_client):
        with pytest.raises(TraceBackendError, match="not implemented in Day 2.4"):
            getter()


def test_mcp_backend_not_yet_implemented(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACE_BACKEND", "mcp")
    with pytest.raises(TraceBackendError, match="not implemented"):
        get_trial_registry_client()


def test_unknown_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACE_BACKEND", "carrier-pigeon")
    with pytest.raises(TraceBackendError):
        get_trial_registry_client()


# --- Malformed fixture handling -------------------------------------------


def test_malformed_fixture_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupt JSON fixture file in the trials/ directory should raise
    TraceBackendError, not silently return None or load a partial record.

    We point the fixture root at a tmp dir, drop a malformed JSON file
    in trials/NCT12345.json, and confirm the backend surfaces the parse
    error rather than swallowing it.
    """
    fake_root = tmp_path / "fixtures"
    (fake_root / "trials").mkdir(parents=True)
    bad = fake_root / "trials" / "NCT12345.json"
    bad.write_text("{ not: valid }")  # malformed JSON

    # Repoint the module-level _FIXTURES_ROOT to the tmp dir.
    import agent.trace_clients as tc
    monkeypatch.setattr(tc, "_FIXTURES_ROOT", fake_root)

    client = FixtureTrialRegistryClient()
    with pytest.raises(TraceBackendError, match="malformed fixture"):
        client.get_trial("NCT12345")


# --- Fixture corpus discipline -------------------------------------------


def test_canonical_metformin_trials_all_present() -> None:
    """If the topic_pack lists a canonical trial, the trace_clients fixture
    directory must have a fixture for it. Otherwise Day 3 citation_trace
    will return None for canonical hits and falsely accuse a real trial of
    being fabricated."""
    expected_ids = {
        "NCT04264897",      # TAME
        "NCT02308228",      # MASTERS
        "NCT01765946",      # MILES
        "ISRCTN29932357",   # MET-PREVENT
    }
    trials_dir = FIXTURES_ROOT / "trials"
    found = {p.stem for p in trials_dir.glob("*.json")}
    missing = expected_ids - found
    assert not missing, (
        f"missing trial fixtures for canonical NCTs: {missing}. "
        f"Update tests/fixtures/trace_clients/trials/ before Day 3."
    )
