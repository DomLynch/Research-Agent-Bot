"""Tests for the post-classifier endpoint→outcome_class remap.

2026-05-09 peer-review fix (Bug 2). The vocab files (in scripts/vocab/)
ship some demonstrably wrong endpoint→outcome_class mappings — most
notably "emotional well-being": "cognitive". The remap helper corrects
these without modifying the vocab files (owned by Codex's Phase 2 lane).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.outcome_class_remap import (
    ENDPOINT_REMAP,
    is_known_misclassification,
    outcome_display,
    outcome_key,
    refine_other_outcome_class,
    remap_outcome_class,
)
from agent.synthesis import detect_outcome_class
from agent.synthesis_schemas import OutcomeClass  # noqa: F401  (Literal import sanity)


# ---- Direct lookup -------------------------------------------------------


def test_emotional_well_being_remaps_to_healthspan_qol() -> None:
    """The headline bug: PEARL "emotional well-being" was tagged 'cognitive'."""
    assert remap_outcome_class("emotional well-being", "cognitive") == "healthspan_qol"


def test_general_health_remaps_to_healthspan_qol() -> None:
    """Vocab ships general health → frailty; correct is healthspan_qol."""
    assert remap_outcome_class("general health", "frailty") == "healthspan_qol"


def test_self_reported_pain_remaps_to_healthspan_qol() -> None:
    """Vocab ships pain → frailty; correct is healthspan_qol."""
    assert remap_outcome_class("self-reported pain", "frailty") == "healthspan_qol"


def test_quality_of_life_remaps_to_healthspan_qol() -> None:
    assert remap_outcome_class("quality of life", "other") == "healthspan_qol"


@pytest.mark.parametrize("endpoint", [
    "SF-36", "sf-36", "sf36", "SF 36",
])
def test_sf36_variants_all_remap(endpoint) -> None:
    assert remap_outcome_class(endpoint, "cognitive") == "healthspan_qol"


# ---- Case + whitespace tolerance -----------------------------------------


@pytest.mark.parametrize("endpoint", [
    "Emotional Well-Being",
    "EMOTIONAL WELL-BEING",
    "emotional   well-being",
    "  emotional well-being  ",
])
def test_case_and_whitespace_tolerance(endpoint) -> None:
    assert remap_outcome_class(endpoint, "cognitive") == "healthspan_qol"


# ---- Pattern-based fuzzy matches -----------------------------------------


def test_pattern_matches_emotional_wellbeing_no_hyphen() -> None:
    assert remap_outcome_class("emotional wellbeing score", "cognitive") == "healthspan_qol"


def test_pattern_matches_psychological_well_being() -> None:
    assert remap_outcome_class("psychological well-being", "cognitive") == "healthspan_qol"


def test_pattern_matches_patient_reported_outcome() -> None:
    assert remap_outcome_class("patient-reported outcome composite",
                               "other") == "healthspan_qol"


# ---- Pass-through (no false positives) -----------------------------------


@pytest.mark.parametrize("endpoint,current_class", [
    ("hba1c", "cardiometabolic"),
    ("mortality", "longevity"),
    ("lean tissue mass", "muscle_function"),
    ("cognitive decline", "cognitive"),
    ("MMSE score", "cognitive"),
    ("dementia", "cognitive"),
    ("blood pressure", "cardiometabolic"),
    ("LDL cholesterol", "cardiometabolic"),
    ("walk speed", "frailty"),
    ("cancer incidence", "oncology"),
    ("RTI rate", "immune"),
])
def test_unrelated_endpoints_pass_through_unchanged(endpoint, current_class) -> None:
    assert remap_outcome_class(endpoint, current_class) == current_class


def test_empty_endpoint_passes_through() -> None:
    assert remap_outcome_class("", "cognitive") == "cognitive"


def test_non_string_endpoint_passes_through() -> None:
    assert remap_outcome_class(None, "cognitive") == "cognitive"  # type: ignore[arg-type]


# ---- is_known_misclassification ------------------------------------------


def test_is_known_misclassification_true_when_remap_disagrees() -> None:
    assert is_known_misclassification("emotional well-being", "cognitive") is True


def test_is_known_misclassification_false_when_already_correct() -> None:
    assert is_known_misclassification("emotional well-being", "healthspan_qol") is False


def test_is_known_misclassification_false_for_unrelated_endpoint() -> None:
    assert is_known_misclassification("hba1c", "cardiometabolic") is False


# ---- ENDPOINT_REMAP contract ---------------------------------------------


def test_endpoint_remap_keys_are_lowercase_normalised() -> None:
    """Direct keys must already be in lookup-normalised form."""
    for key in ENDPOINT_REMAP:
        assert key == " ".join(key.lower().split()), f"key {key!r} not normalised"


def test_endpoint_remap_targets_are_valid_outcome_classes() -> None:
    """Every target must be a known OutcomeClass Literal value."""
    valid = {
        "muscle_function", "cardiometabolic", "cognitive", "frailty",
        "healthspan_qol", "longevity", "immune", "ophthalmologic",
        "oncology", "mechanism", "safety", "other",
    }
    for target in ENDPOINT_REMAP.values():
        assert target in valid, f"unknown class {target!r}"


# ---- Integration with detect_outcome_class -------------------------------


def test_detect_outcome_class_routes_qol_keywords_to_healthspan_qol() -> None:
    """The new keywords in agent.synthesis._OUTCOME_KEYWORDS route QoL
    phrases to healthspan_qol BEFORE the cognitive class can grab them."""
    text = "emotional well-being improved over 12 weeks"
    assert detect_outcome_class(text) == "healthspan_qol"


def test_detect_outcome_class_keeps_cognitive_for_actual_cognitive() -> None:
    """Regression: the new healthspan_qol class must not steal real cognitive."""
    text = "MMSE score and cognitive decline assessed"
    assert detect_outcome_class(text) == "cognitive"


def test_detect_outcome_class_qol_takes_priority_over_cognitive_when_both_present() -> None:
    """When a paper mentions both QoL and cognitive endpoints, the
    insertion order in _OUTCOME_KEYWORDS gives healthspan_qol priority
    (placed before cognitive in the dict). This is the policy choice
    that prevents the PEARL-style misclassification."""
    text = "SF-36 emotional well-being and cognitive function were both measured"
    # First-listed wins; healthspan_qol is before cognitive in the dict.
    assert detect_outcome_class(text) == "healthspan_qol"


def test_refine_other_splits_biomedical_junk_drawer() -> None:
    receipts = [
        SimpleNamespace(receipt_id="a", source_title="Vitamin D and bone fracture risk", population_summary=""),
        SimpleNamespace(receipt_id="b", source_title="All-cause mortality and survival", population_summary=""),
        SimpleNamespace(receipt_id="c", source_title="Vitamin D deficiency prevalence status", population_summary=""),
        SimpleNamespace(receipt_id="d", source_title="Sepsis inflammation and infection", population_summary=""),
        SimpleNamespace(receipt_id="e", source_title="Cholecalciferol pharmacokinetic dose study", population_summary=""),
    ]
    classes = {refine_other_outcome_class(r, "other") for r in receipts}
    assert len(classes) >= 4
    assert "contextual_other" not in classes


def test_refine_other_keeps_non_other_unchanged() -> None:
    receipt = SimpleNamespace(receipt_id="bone", source_title="Bone trial", population_summary="")
    assert refine_other_outcome_class(receipt, "longevity") == "longevity"


def test_refined_outcome_vocabulary_has_public_labels_and_keys() -> None:
    assert outcome_display("safety_comorbidity") == "Safety and Comorbidity"
    assert outcome_key("Safety and Comorbidity Outcomes") == "safety_comorbidity"
    assert outcome_key("skeletal fracture bone") == "skeletal_fracture_bone"


def test_refine_other_does_not_misfile_supplementation_as_pharmacokinetics() -> None:
    """Feedback #3: 'supplementation' is an intervention descriptor, not a
    pharmacokinetic outcome — it appears in nearly every supplement study's
    title. A supplement study with a non-PK focus that fell into 'other' must
    NOT be reclassified as dosing/pharmacokinetics."""
    receipt = SimpleNamespace(
        receipt_id="r",
        source_title="Resveratrol supplementation and cardiovascular outcomes",
        population_summary="older adults",
    )
    assert refine_other_outcome_class(receipt, "other") != "dosing_pharmacokinetics"


def test_refine_other_keeps_genuine_pharmacokinetics() -> None:
    """A genuine dose / pharmacokinetic study still routes correctly."""
    receipt = SimpleNamespace(
        receipt_id="r",
        source_title="Pharmacokinetic dose-response study",
        population_summary="",
    )
    assert refine_other_outcome_class(receipt, "other") == "dosing_pharmacokinetics"


def test_refine_other_does_not_misfile_skeletal_muscle_as_bone() -> None:
    """'Skeletal muscle' must route to muscle_function, not the bone class —
    the bare 'skeletal' needle previously substring-matched it as bone."""
    receipt = SimpleNamespace(
        receipt_id="r",
        source_title="Treadmill exercise alleviates methylglyoxal-induced skeletal muscle dysfunction",
        population_summary="aged mice",
    )
    result = refine_other_outcome_class(receipt, "other")
    assert result != "skeletal_fracture_bone"
    assert result == "muscle_function"


def test_refine_other_keeps_genuine_bone_as_bone() -> None:
    """A genuine bone-outcome study still routes to the bone class."""
    receipt = SimpleNamespace(
        receipt_id="r",
        source_title="Effect of the intervention on bone fracture risk and osteoporosis",
        population_summary="postmenopausal women",
    )
    assert refine_other_outcome_class(receipt, "other") == "skeletal_fracture_bone"


def test_immune_and_immune_inflammation_canonicalize_together() -> None:
    """The two near-duplicate immune classes collapse to one canonical key so a
    corpus does not fragment into two singleton sections."""
    assert outcome_key("immune") == outcome_key("immune_inflammation")
    assert outcome_key("immune") == "immune_inflammation"


def test_dosing_pharmacokinetics_needles_carry_no_topic_specific_compounds() -> None:
    """Universal-no-hardcoding: the dosing class must not bake in topic-specific
    drug/compound names (e.g. vitamin-D forms) — those belong in topic packs,
    not the universal outcome vocabulary."""
    from agent.outcome_class_remap import OUTCOME_VOCAB
    needles = OUTCOME_VOCAB["dosing_pharmacokinetics"][2]
    assert "cholecalciferol" not in needles
    assert "calcifediol" not in needles
    assert "supplementation" not in needles


def test_mechanistic_other_routes_to_mechanism_not_catchall() -> None:
    """5a: a mechanistic-directness source whose outcome WHAT is not classifiable
    becomes 'mechanism' (a real class), not the 'contextual_other' catch-all —
    draining the junk drawer. Non-mechanistic 'other' stays contextual_other,
    and non-'other' classes are never rewritten. Universal — directness only."""
    mech = SimpleNamespace(
        receipt_id="", source_title="murine BHB-chromatin study",
        population_summary="", directness="mechanistic",
    )
    assert refine_other_outcome_class(mech, "other") == "mechanism"
    obs = SimpleNamespace(
        receipt_id="", source_title="murine BHB-chromatin study",
        population_summary="", directness="indirect",
    )
    assert refine_other_outcome_class(obs, "other") == "contextual_other"
    assert refine_other_outcome_class(mech, "cardiometabolic") == "cardiometabolic"
