"""Tests for agent/domain_evidence.py — Wave 7 Evidence Factory
slice 5. Verifies that domain profiles are first-class data objects
the pipeline can read instead of hardcoded biomedical signal lists.
"""
from __future__ import annotations

from agent.domain_evidence import (
    BIOMEDICAL, CS_AI, ECONOMICS, MANAGEMENT,
    get_profile, list_profiles,
)


# ---------- profile sanity ------------------------------------------

def test_biomedical_profile_complete():
    assert BIOMEDICAL.name == "biomedical"
    assert "A1" in BIOMEDICAL.tier_hierarchy
    assert "direct" in BIOMEDICAL.directness_levels
    assert any(
        "randomized controlled trial" in s
        for s in BIOMEDICAL.core_clinical_signals
    )


def test_economics_profile_uses_econ_specific_hierarchy():
    """Economics evidence pyramid: RCT > DiD > IV > Obs > Theory.
    Distinct from biomedical A1/A2/B/C tier names."""
    assert ECONOMICS.name == "economics"
    assert "DiD" in ECONOMICS.tier_hierarchy
    assert "RCT" in ECONOMICS.tier_hierarchy
    # Economics core signals point to causal-inference techniques
    assert any(
        "diff-in-diff" in s.lower()
        or "regression discontinuity" in s.lower()
        for s in ECONOMICS.core_clinical_signals
    )


def test_management_profile_uses_field_experiment_top():
    """Management hierarchy: FieldExp > Panel > Case > Survey > Opinion."""
    assert MANAGEMENT.name == "management"
    assert MANAGEMENT.tier_hierarchy[0] == "FieldExp"
    assert "case_study" in MANAGEMENT.directness_levels


def test_cs_ai_profile_centers_on_ablation_benchmarks():
    """CS/AI hierarchy puts ablation+held-out at top, position
    papers at the bottom."""
    assert CS_AI.name == "cs_ai"
    assert "AblationBench" in CS_AI.tier_hierarchy
    assert any(
        "ablation" in s for s in CS_AI.core_clinical_signals
    )


# ---------- get_profile + list_profiles ------------------------------

def test_get_profile_resolves_known_names():
    assert get_profile("biomedical") is BIOMEDICAL
    assert get_profile("economics") is ECONOMICS
    assert get_profile("management") is MANAGEMENT
    assert get_profile("cs_ai") is CS_AI


def test_get_profile_case_insensitive():
    assert get_profile("BIOMEDICAL") is BIOMEDICAL
    assert get_profile("Economics") is ECONOMICS


def test_get_profile_unknown_falls_back_to_biomedical():
    """Unknown / None / empty → biomedical (platform default).
    No exception — fail-soft on legacy topic packs without `domain`."""
    assert get_profile(None) is BIOMEDICAL
    assert get_profile("") is BIOMEDICAL
    assert get_profile("xxx_unknown") is BIOMEDICAL


def test_list_profiles_returns_all_four():
    profiles = list_profiles()
    assert set(profiles) == {
        "biomedical", "economics", "management", "cs_ai",
    }


# ---------- is_high_tier --------------------------------------------

def test_is_high_tier_works_for_each_domain():
    """Each profile decides 'high tier' from its own hierarchy.
    Top two slots = high; lower slots = not high."""
    assert BIOMEDICAL.is_high_tier("A1")
    assert BIOMEDICAL.is_high_tier("A2")
    assert not BIOMEDICAL.is_high_tier("B1")
    assert not BIOMEDICAL.is_high_tier("C1")
    assert ECONOMICS.is_high_tier("RCT")
    assert ECONOMICS.is_high_tier("DiD")
    assert not ECONOMICS.is_high_tier("Obs")
    assert MANAGEMENT.is_high_tier("FieldExp")
    assert MANAGEMENT.is_high_tier("Panel")
    assert not MANAGEMENT.is_high_tier("Survey")
    assert CS_AI.is_high_tier("AblationBench")
    assert not CS_AI.is_high_tier("Demo")


def test_is_high_tier_handles_empty_or_unknown():
    assert not BIOMEDICAL.is_high_tier("")
    assert not BIOMEDICAL.is_high_tier("X9")


# ---------- DomainProfile is frozen ---------------------------------

def test_profile_dataclass_is_frozen():
    from dataclasses import FrozenInstanceError
    import pytest
    with pytest.raises(FrozenInstanceError):
        BIOMEDICAL.name = "other"  # type: ignore[misc]
