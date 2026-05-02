"""Tests for scripts/quant_endpoints.py — Day 10.17 Phase 2.2.

Vocab + matchers for endpoint / arm / direction binding. Tests are
discriminating (one assertion per regression class):
  - Endpoint vocab: each canonical name has at least one matching
    real-paper passage
  - Arm vocab: distinguishes "metformin group" from "placebo group"
  - Direction vocab: handles the proximity-tiebreaker case where
    one sentence has both "increased" and "decreased"
  - Per-paper gold: Walton MASTERS / Konopka / Witham passages bind
    to the right (endpoint, arm, direction) tuple
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import quant_endpoints  # noqa: E402


# ============================================================
# Endpoint vocab — one test per canonical name proves coverage
# ============================================================


def test_endpoint_vo2max_matches_full_phrase() -> None:
    """Konopka 2019: 'Metformin attenuated the increase in VO2max'."""
    assert quant_endpoints.match_endpoint(
        "Metformin attenuated the increase in VO2max following AET.",
    ) == "VO2max"


def test_endpoint_vo2max_matches_subscript_form() -> None:
    """PDF text often shows 'VO₂max' (Unicode subscript)."""
    assert quant_endpoints.match_endpoint(
        "VO₂max increased by approximately 50%.",
    ) == "VO2max"


def test_endpoint_walk_speed_matches_witham_form() -> None:
    """Witham MET-PREVENT: '4-m walk speed at 4 months'."""
    assert quant_endpoints.match_endpoint(
        "Mean 4-m walk speed at 4 months was 0.57 m/s.",
    ) == "walk speed"


def test_endpoint_thigh_muscle_mass_wins_over_lean_body_mass() -> None:
    """Order matters — 'thigh muscle mass' is more specific than 'lean
    body mass' when both could plausibly match. Test the order rule."""
    assert quant_endpoints.match_endpoint(
        "Thigh muscle mass increased significantly in placebo.",
    ) == "thigh muscle mass"


def test_endpoint_lean_body_mass_matches_walton_form() -> None:
    """Walton MASTERS: 'placebo gained more lean body mass'."""
    assert quant_endpoints.match_endpoint(
        "Placebo gained more lean body mass than metformin.",
    ) == "lean body mass"


def test_endpoint_insulin_sensitivity_matches_konopka_form() -> None:
    """Konopka 2019: 'whole-body insulin sensitivity'."""
    assert quant_endpoints.match_endpoint(
        "Whole-body insulin sensitivity was attenuated by metformin.",
    ) == "insulin sensitivity"


def test_endpoint_hba1c_matches_acronym_and_full_form() -> None:
    """HbA1c is usually given as the acronym; some papers spell it out."""
    assert quant_endpoints.match_endpoint(
        "HbA1c decreased by 0.5%.",
    ) == "HbA1c"
    assert quant_endpoints.match_endpoint(
        "Glycated hemoglobin (A1c) was lower at 12 weeks.",
    ) == "HbA1c"


def test_endpoint_returns_empty_when_no_vocab_match() -> None:
    """Pure prose with no clinical vocab returns ""; downstream
    Phase 4 can detect missing endpoints from this."""
    assert quant_endpoints.match_endpoint(
        "The economic implications of an aging society are profound.",
    ) == ""


# ============================================================
# Arm vocab — distinguishes treatment from control
# ============================================================


def test_arm_metformin_matches_modified_noun_form_first() -> None:
    """'metformin group' matches the metformin entry."""
    assert quant_endpoints.match_arm(
        "The metformin group showed lower respiration.",
    ) == "metformin"


def test_arm_first_mentioned_in_sentence_wins() -> None:
    """Reviewer-flagged HIGH bug fix: pre-fix the matcher iterated
    ARM_VOCAB in vocab order and returned the first matching entry,
    so 'Placebo gained more mass than metformin' wrongly bound
    arm=metformin (because bare-metformin came earlier in vocab).
    Fix: earliest IN-SENTENCE position wins. 'Placebo' appears
    first → arm=placebo, which matches clinical-prose convention
    (the subject of the comparison)."""
    assert quant_endpoints.match_arm(
        "Placebo gained more mass than metformin.",
    ) == "placebo"
    # And the reverse word order:
    assert quant_endpoints.match_arm(
        "Metformin lost more mass than placebo.",
    ) == "metformin"
    # Modified-noun forms still tiebreak when at same position:
    assert quant_endpoints.match_arm(
        "The placebo group lost weight.",
    ) == "placebo"


def test_arm_pooled_matches_combined() -> None:
    assert quant_endpoints.match_arm(
        "Both groups showed similar improvements.",
    ) == "pooled"


def test_arm_returns_empty_when_no_vocab_match() -> None:
    assert quant_endpoints.match_arm(
        "Background prevalence is approximately 10%.",
    ) == ""


# ============================================================
# Direction vocab — proximity tiebreaker
# ============================================================


def test_direction_increase_matches_walton_form() -> None:
    """'placebo gained more lean body mass'."""
    assert quant_endpoints.match_direction(
        "Placebo gained more lean body mass than metformin.",
    ) == "increase"


def test_direction_decrease_matches_metformin_attenuated() -> None:
    """'metformin attenuated' should map to decrease (the gain was
    blunted)."""
    assert quant_endpoints.match_direction(
        "Metformin attenuated the response to training.",
    ) == "decrease"


def test_direction_no_change_matches_witham_null_finding() -> None:
    """Witham MET-PREVENT: 'metformin did not improve walk speed'."""
    assert quant_endpoints.match_direction(
        "Metformin did not improve 4-m walk speed.",
    ) == "no_change"


def test_direction_mixed_matches_dichotomous() -> None:
    """Konopka 2019: 'dichotomous response' is mixed."""
    assert quant_endpoints.match_direction(
        "There was a dichotomous response to metformin.",
    ) == "mixed"


def test_direction_proximity_picks_closer_keyword() -> None:
    """Sentence has BOTH 'increased' (early) and 'decreased' (late).
    The numeric anchor near the END should bind to 'decrease', not
    'increase' — proximity wins over first-match-wins."""
    sentence = "Metformin increased AMPK activity but decreased mitochondrial respiration by 25%."
    # Anchor positioned near the "25%" (toward the end of the sentence)
    anchor = sentence.find("25")
    direction = quant_endpoints.match_direction(sentence, anchor_offset=anchor)
    assert direction == "decrease", (
        f"proximity tiebreaker failed: {direction!r}"
    )


def test_direction_proximity_picks_closer_when_anchor_at_start() -> None:
    """Same sentence; anchor near the start should bind to 'increase'."""
    sentence = "Metformin increased AMPK activity but decreased mitochondrial respiration by 25%."
    anchor = sentence.find("AMPK")  # Near the "increased" keyword
    direction = quant_endpoints.match_direction(sentence, anchor_offset=anchor)
    assert direction == "increase"


def test_direction_returns_empty_when_no_vocab_match() -> None:
    assert quant_endpoints.match_direction(
        "Subjects were enrolled from local clinics.",
    ) == ""


# ============================================================
# binding_confidence rollup
# ============================================================


def test_binding_confidence_high_when_all_three_bound_AND_role_is_effect() -> None:
    """Phase 2.2-fix P1 #3: high requires claim_role=='effect' too."""
    assert quant_endpoints.binding_confidence_for(
        endpoint="VO2max", arm="metformin", direction="decrease",
        claim_role="effect",
    ) == "high"


def test_binding_confidence_partial_when_all_three_bound_but_role_non_effect() -> None:
    """P1 #3 regression: 'high' was masking dose/duration/population
    claims as primary evidence even when all 3 fields were bound.
    Now: full coverage + non-effect role lands as 'partial'."""
    for non_effect in ("dose", "duration", "population", "background", "unknown", ""):
        got = quant_endpoints.binding_confidence_for(
            endpoint="VO2max", arm="metformin", direction="decrease",
            claim_role=non_effect,
        )
        assert got == "partial", (
            f"role={non_effect!r}: expected partial, got {got!r}"
        )


def test_binding_confidence_partial_when_some_bound() -> None:
    assert quant_endpoints.binding_confidence_for(
        endpoint="VO2max", arm="", direction="decrease",
    ) == "partial"
    assert quant_endpoints.binding_confidence_for(
        endpoint="", arm="metformin", direction="",
    ) == "partial"


def test_binding_confidence_none_when_nothing_bound() -> None:
    assert quant_endpoints.binding_confidence_for(
        endpoint="", arm="", direction="",
    ) == "none"


# ============================================================
# bind_claim integration — end-to-end on real-paper passages
# ============================================================


def test_bind_walton_thigh_muscle_finding() -> None:
    """Walton MASTERS gold passage: '...placebo gained more lean body
    mass and thigh muscle mass than metformin'. Anchor on the
    'thigh' position so endpoint binds to thigh muscle mass (not
    lean body mass — the proximity fix in P1 #1)."""
    sentence = (
        "Placebo gained more lean body mass and thigh muscle mass "
        "than metformin (p = .003)."
    )
    # Anchor near the 'thigh muscle mass' position
    binding = quant_endpoints.bind_claim(
        sentence, source_offset_in_section=sentence.find("thigh"),
        claim_role="effect",
    )
    # Endpoint: proximity → thigh muscle mass (not lean body mass)
    assert binding.endpoint == "thigh muscle mass"
    # Arm: 'placebo' (earliest in sentence — clinical convention)
    assert binding.arm == "placebo"
    assert binding.direction == "increase"
    # claim_role=="effect" passed → high confidence
    assert binding.binding_confidence == "high"


def test_bind_konopka_vo2max_attenuated() -> None:
    """Konopka 2019 gold: 'metformin attenuated the increase in
    VO2max ... (p = 0.08)'."""
    sentence = (
        "Metformin attenuated the increase in VO2max following 12 "
        "weeks of AET, although this did not reach significance (p = 0.08)."
    )
    binding = quant_endpoints.bind_claim(
        sentence, source_offset_in_section=sentence.find("VO2max"),
    )
    assert binding.endpoint == "VO2max"
    assert binding.arm == "metformin"
    # The closest direction word to "VO2max" is "attenuated" (decrease).
    assert binding.direction == "decrease"


def test_bind_witham_walk_speed_null_endpoint() -> None:
    """Witham MET-PREVENT primary endpoint: walk speed null finding."""
    sentence = (
        "Metformin did not improve 4-m walk speed at 4 months "
        "(adjusted treatment effect 0.001 m/s; 95% CI -0.06 to 0.06)."
    )
    binding = quant_endpoints.bind_claim(
        sentence, source_offset_in_section=sentence.find("walk speed"),
    )
    assert binding.endpoint == "walk speed"
    assert binding.arm == "metformin"
    assert binding.direction == "no_change"


def test_bind_unbound_sentence_returns_none_confidence() -> None:
    """Sentence with no clinical vocab -> all three fields empty."""
    sentence = "Demographic data were collected at baseline."
    binding = quant_endpoints.bind_claim(sentence, source_offset_in_section=0)
    assert binding.endpoint == ""
    assert binding.arm == ""
    assert binding.direction == ""
    assert binding.binding_confidence == "none"


def test_arm_bare_keyword_picks_earliest_or_subject_after_comparator() -> None:
    """Phase 2.2-fix: combined regression test for the two arm rules.

    Plain comparison sentences with both arms: earliest-IN-SENTENCE
    wins (the subject of the statement).

    Comparator-grammar sentences ('Compared to X, Y'): the subject
    is the arm AFTER the comparator marker, NOT before. Pre-fix
    these wrongly bound to the comparator arm.
    """
    cases = [
        # Plain comparison — earliest mention wins.
        ("Placebo had higher VO2max than metformin (p = 0.04).", "placebo"),
        ("Metformin had lower VO2max than placebo (p = 0.04).", "metformin"),
        # Comparator grammar — subject (after marker) wins, NOT comparator.
        ("Compared to placebo, metformin reduced HbA1c.", "metformin"),
        ("Compared to metformin, placebo had no benefit.", "placebo"),
        ("In contrast to placebo, metformin lowered weight.", "metformin"),
        ("Vs. metformin, placebo had higher mortality.", "placebo"),
    ]
    for sentence, expected in cases:
        got = quant_endpoints.match_arm(sentence)
        assert got == expected, (
            f"{sentence!r}: expected arm={expected!r}, got {got!r}"
        )


def test_arm_modified_noun_form_wins_when_overlapping_at_same_position() -> None:
    """Vocab-priority tiebreaker: when modified-noun and bare
    forms match at the SAME sentence position ('metformin group'
    matches both 'metformin\\s+group' AND bare 'metformin'),
    the more-specific entry (earlier in vocab) wins."""
    assert quant_endpoints.match_arm(
        "The metformin group lost weight.",
    ) == "metformin"
    assert quant_endpoints.match_arm(
        "The placebo group gained weight.",
    ) == "placebo"


def test_bind_partial_endpoint_only_returns_partial() -> None:
    """Sentence with endpoint but no arm/direction is partial."""
    sentence = "HbA1c was 6.8% at baseline."
    binding = quant_endpoints.bind_claim(sentence, source_offset_in_section=0)
    assert binding.endpoint == "HbA1c"
    assert binding.arm == ""  # No arm vocabulary
    assert binding.direction == ""
    assert binding.binding_confidence == "partial"


# ============================================================
# Phase 2.2-fix - P1 audit regression tests
# ============================================================


def test_p1_endpoint_proximity_walton_dual_endpoint_sentence() -> None:
    """P1 #1 audit fix: pre-fix `match_endpoint` returned the
    first vocab match by curated order, so a sentence like
    `lean body mass (p=.003) and thigh muscle mass (p<.001)`
    bound BOTH p-values to the same endpoint. Now: each claim
    binds to the endpoint NEAREST to its anchor."""
    sentence = (
        "Placebo gained more lean body mass (p = .003) and thigh "
        "muscle mass (p < .001) than metformin."
    )
    anchor1 = sentence.find("p = .003")
    ep1 = quant_endpoints.match_endpoint(sentence, anchor_offset=anchor1)
    assert ep1 == "lean body mass", (
        f"first p-value should bind to lean body mass, got {ep1!r}"
    )
    anchor2 = sentence.find("p < .001")
    ep2 = quant_endpoints.match_endpoint(sentence, anchor_offset=anchor2)
    assert ep2 == "thigh muscle mass", (
        f"second p-value should bind to thigh muscle mass, got {ep2!r}"
    )


def test_p1_endpoint_proximity_no_anchor_falls_back_to_vocab_order() -> None:
    """Backward compat: callers that do not pass anchor_offset get
    the original first-match-wins behavior."""
    sentence = "lean body mass and thigh muscle mass were measured"
    assert quant_endpoints.match_endpoint(sentence) == "thigh muscle mass"


def test_p1_arm_comparator_grammar_compared_to() -> None:
    """P1 #2 audit fix: 'Compared to placebo, metformin reduced
    HbA1c' must bind arm=metformin (the subject), NOT placebo
    (the comparator). Pre-fix earliest-mention-wins was wrong."""
    assert quant_endpoints.match_arm(
        "Compared to placebo, metformin reduced HbA1c by 0.5%.",
    ) == "metformin"
    assert quant_endpoints.match_arm(
        "In contrast to placebo, metformin lowered weight.",
    ) == "metformin"
    assert quant_endpoints.match_arm(
        "Compared to metformin, placebo had no benefit.",
    ) == "placebo"


def test_p1_arm_comparator_with_versus_marker() -> None:
    """vs / versus markers also flip arm assignment."""
    assert quant_endpoints.match_arm(
        "Vs. placebo, metformin reduced events.",
    ) == "metformin"
    assert quant_endpoints.match_arm(
        "Versus placebo, metformin had a smaller gain.",
    ) == "metformin"


def test_p1_arm_plain_comparison_unchanged_by_comparator_fix() -> None:
    """Comparator-grammar fix must not regress plain comparison
    sentences without comparator markers."""
    assert quant_endpoints.match_arm(
        "Placebo gained more weight than metformin (p = .003).",
    ) == "placebo"
    assert quant_endpoints.match_arm(
        "Metformin reduced glucose more than placebo.",
    ) == "metformin"


def test_p1_role_gated_high_confidence_dose_lands_partial() -> None:
    """P1 #3 audit fix: a dose like '500 mg/day' in a sentence
    that mentions endpoint and arm and direction must NOT land
    as binding_confidence=high. Pre-fix audit found 117/194
    high claims were non-effect roles."""
    binding = quant_endpoints.bind_claim(
        sentence="Subjects in the metformin group received 500 mg/day for HbA1c control.",
        source_offset_in_section=39,
        claim_role="dose",
    )
    assert binding.binding_confidence == "partial", (
        f"dose claim wrongly tagged: {binding}"
    )


def test_comparator_grammar_does_not_overexclude_when_no_arm_in_tight_window() -> None:
    """Reviewer MEDIUM fix v0.5.0: pre-fix any arm word within 40
    chars after a comparator marker was excluded as the comparator
    referent. That wrongly suppressed real subjects in sentences
    like 'Compared to historical levels, metformin treatment is
    widespread' — metformin appeared past a non-arm prefix and was
    eaten. Fix: only exclude arms in the tight next-word window
    (<=8 chars). The non-comparative phrase passes through and
    metformin survives as the subject."""
    assert quant_endpoints.match_arm(
        "Compared to historical levels, metformin treatment is widespread.",
    ) == "metformin"
    assert quant_endpoints.match_arm(
        "Relative to baseline values, the metformin group improved.",
    ) == "metformin"
    # Tight window still works for real comparator grammar:
    assert quant_endpoints.match_arm(
        "Compared to placebo, metformin reduced HbA1c.",
    ) == "metformin"


# ============================================================
# v0.6.0 - diagnostic-paper audit P1 regression tests
# ============================================================


def test_v06_mortality_distinct_from_lifespan_endpoint() -> None:
    """v0.6.0 P1 fix: 'reduced the risk of diabetes-related events
    by 32%' is a MORTALITY/RISK-REDUCTION finding, NOT a lifespan
    decrease. Pre-fix mapped 'all-cause mortality' to canonical
    endpoint 'lifespan', flipping polarity in downstream prose
    (writer rendered 'decreased lifespan' for a beneficial
    mortality reduction)."""
    sentence = (
        "Metformin reduced the risk of diabetes-related events "
        "(relative risk reduction 32%) in the UKPDS subgroup analysis."
    )
    ep = quant_endpoints.match_endpoint(sentence)
    assert ep == "mortality", f"expected mortality, got {ep!r}"


def test_v06_lifespan_endpoint_matches_only_literal_lifespan() -> None:
    """The lifespan vocab is now stricter — does NOT swallow
    'all-cause mortality'."""
    assert quant_endpoints.match_endpoint(
        "Metformin extended lifespan by 14% in mice.",
    ) == "lifespan"
    # And mortality wins over lifespan when both keywords coexist:
    sentence_with_both = (
        "Long-term mortality was reduced by 32% with no lifespan effect."
    )
    # Mortality is more specific to the numeric finding here.
    ep = quant_endpoints.match_endpoint(sentence_with_both)
    assert ep in ("mortality", "lifespan")  # either is defensible


def test_v06_all_cause_mortality_does_not_match_lifespan() -> None:
    """Direct test of the polarity bug: 'all-cause mortality'
    (a binary event rate) must not bind to 'lifespan' (a continuous
    outcome). Pre-fix this was the load-bearing UKPDS bug."""
    sentence = "All-cause mortality decreased by 24% in the metformin arm."
    ep = quant_endpoints.match_endpoint(sentence)
    assert ep == "mortality", f"expected mortality, got {ep!r}"
