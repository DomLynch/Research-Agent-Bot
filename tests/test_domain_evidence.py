"""Tests for agent/domain_evidence.py — Slice 8 step B refactor.

Verifies that domain adapters are TOML-loaded (no hardcoded
biomedical/management/economics/cs_ai/legal data in Python). Adding
a new domain is a TOML-only operation; the same engine services it.
"""
from __future__ import annotations

import pytest

from agent.domain_evidence import (
    DomainAdapter, get_adapter, list_domains, reload_registry,
)


# ---------- registry / list_domains -----------------------------------

def test_registry_includes_all_five_built_in_domains():
    """domains/*.toml is the source of truth. The 5 built-ins must
    all be discoverable; adding a 6th is a TOML-only change."""
    domains = list_domains()
    for name in (
        "biomedical", "management", "economics", "cs_ai", "legal",
    ):
        assert name in domains, f"missing domain: {name}"


# ---------- biomedical adapter ----------------------------------------

def test_biomedical_adapter_has_universal_shape():
    """Biomedical evidence hierarchy + outcome classes + signals
    are loaded from domains/biomedical.toml. Top of hierarchy is
    'rct' (the universal name), not 'A1' (biomedical-specific tier
    label)."""
    bio = get_adapter("biomedical")
    assert bio.name == "biomedical"
    # Universal type names (rct, cohort, meta_analysis) — not the
    # old A1/A2/B1 tier labels (which mixed shape with values).
    assert bio.evidence_hierarchy[0] == "rct"
    assert "cohort" in bio.evidence_hierarchy
    assert "meta_analysis" in bio.evidence_hierarchy
    # Outcome classes are domain-data, not Python constants.
    assert "mortality" in bio.outcome_classes
    assert "function" in bio.outcome_classes
    # Required-context schema declared in TOML.
    assert "population" in bio.required_context_fields
    assert "outcome" in bio.required_context_fields


def test_biomedical_signals_present_for_classifier():
    bio = get_adapter("biomedical")
    assert any("randomized" in s for s in bio.core_clinical_signals)
    assert any("mortality" in s for s in bio.core_clinical_signals)
    assert any("vitro" in s for s in bio.mechanism_signals)


# ---------- non-biomedical domains (universality proof) ---------------

def test_economics_uses_economics_specific_hierarchy():
    """Economics is causal-identification quality — different
    universe of types than biomedical."""
    econ = get_adapter("economics")
    assert econ.name == "economics"
    assert "natural_experiment" in econ.evidence_hierarchy
    assert "diff_in_diff" in econ.evidence_hierarchy
    # Economics outcomes don't overlap with biomedical
    assert "growth" in econ.outcome_classes
    assert "inflation" in econ.outcome_classes
    assert "mortality" not in econ.outcome_classes


def test_management_uses_field_experiment_top():
    mgmt = get_adapter("management")
    assert mgmt.evidence_hierarchy[0] == "field_experiment"
    assert "productivity" in mgmt.outcome_classes
    assert "retention" in mgmt.outcome_classes


def test_cs_ai_centers_on_ablation_benchmarks():
    cs = get_adapter("cs_ai")
    assert "ablation_benchmark" in cs.evidence_hierarchy
    assert "accuracy" in cs.outcome_classes
    assert any("ablation" in s for s in cs.core_clinical_signals)


def test_legal_domain_proves_any_industry_coverage():
    """Legal demonstrates 'any industry' — no biomedical leakage.
    Same engine will service legal precedent topics as biomedical
    drug topics."""
    legal = get_adapter("legal")
    assert legal.name == "legal"
    assert "supreme_court_decision" in legal.evidence_hierarchy
    assert "constitutional" in legal.outcome_classes
    assert "jurisdiction" in legal.required_context_fields


# ---------- get_adapter resolution -------------------------------------

def test_get_adapter_case_insensitive():
    assert get_adapter("BIOMEDICAL").name == "biomedical"
    assert get_adapter("Economics").name == "economics"
    assert get_adapter("cs_ai").name == "cs_ai"


def test_get_adapter_unknown_falls_back_to_biomedical():
    """Unknown / None / empty → biomedical (platform default).
    Fail-soft for legacy topic packs without `domain = "..."`."""
    assert get_adapter(None).name == "biomedical"
    assert get_adapter("").name == "biomedical"
    assert get_adapter("xxx_unknown").name == "biomedical"


def test_is_high_tier_uses_top_two_slots_per_domain():
    """Each domain's top-two hierarchy slots = high tier; lower = not."""
    bio = get_adapter("biomedical")
    assert bio.is_high_tier("rct")  # slot 0
    assert bio.is_high_tier("meta_analysis")  # slot 1
    assert not bio.is_high_tier("review")
    econ = get_adapter("economics")
    assert econ.is_high_tier("natural_experiment")
    assert econ.is_high_tier("rct")
    assert not econ.is_high_tier("theory")


# ---------- frozen invariant + back-compat aliases --------------------

def test_adapter_dataclass_is_frozen():
    from dataclasses import FrozenInstanceError
    bio = get_adapter("biomedical")
    with pytest.raises(FrozenInstanceError):
        bio.name = "other"  # type: ignore[misc]


def test_slice5_back_compat_aliases_resolve():
    """Slice 5 callers using BIOMEDICAL / get_profile / list_profiles
    keep working after the Step B refactor."""
    from agent import domain_evidence as de
    # Module-level lazy attribute → adapter
    assert de.BIOMEDICAL.name == "biomedical"
    assert de.ECONOMICS.name == "economics"
    # Function aliases
    assert de.get_profile("biomedical").name == "biomedical"
    assert "biomedical" in de.list_profiles()
    # DomainProfile alias → DomainAdapter
    assert de.DomainProfile is DomainAdapter


# ---------- reload + new-domain extensibility -------------------------

def test_new_domain_can_be_added_via_toml(tmp_path, monkeypatch):
    """Drop a new domain TOML in domains/ and reload_registry picks
    it up — no Python changes needed. Universality proof."""
    fake_dir = tmp_path / "domains"
    fake_dir.mkdir()
    (fake_dir / "fictional_field.toml").write_text(
        '[domain]\nname = "fictional_field"\n'
        'evidence_hierarchy = ["foo", "bar"]\n'
        'outcome_classes = ["x", "y"]\n'
        'required_context_fields = ["thing"]\n'
        'core_clinical_signals = ["foo signal"]\n'
        'mechanism_signals = []\n',
    )
    import agent.domain_evidence as de
    monkeypatch.setattr(de, "_DOMAINS_DIR", fake_dir)
    de.reload_registry()
    try:
        adapter = de.get_adapter("fictional_field")
        assert adapter.evidence_hierarchy == ("foo", "bar")
        assert adapter.outcome_classes == ("x", "y")
    finally:
        de.reload_registry()  # restore real registry
