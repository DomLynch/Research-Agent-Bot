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


def test_binding_confidence_high_when_all_three_bound() -> None:
    assert quant_endpoints.binding_confidence_for(
        endpoint="VO2max", arm="metformin", direction="decrease",
    ) == "high"


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
    'thigh' position so direction is bound to 'gained' (increase)."""
    sentence = (
        "Placebo gained more lean body mass and thigh muscle mass "
        "than metformin (p = .003)."
    )
    # Anchor: the 'thigh muscle mass' position
    binding = quant_endpoints.bind_claim(
        sentence, source_offset_in_section=sentence.find("thigh"),
    )
    # Endpoint: thigh muscle mass wins over plain lean body mass
    assert binding.endpoint == "thigh muscle mass"
    # Arm: metformin (first match — first metformin entry is the
    # 'metformin group' modified-noun pattern, which doesn't fire
    # here, then placebo group, then bare metformin/placebo)
    assert binding.arm in ("metformin", "placebo")
    assert binding.direction == "increase"
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


def test_arm_bare_keyword_at_later_sentence_position_loses_to_earlier() -> None:
    """Reviewer HIGH 2 regression: any sentence with both bare
    metformin AND placebo must bind to the EARLIER-mentioned arm.
    Pre-fix arbitrarily returned metformin via vocab order; this
    test pins the corpus rebalance."""
    cases = [
        ("Placebo had higher VO2max than metformin (p = 0.04).", "placebo"),
        ("Metformin had lower VO2max than placebo (p = 0.04).", "metformin"),
        ("Compared to placebo, metformin reduced HbA1c.", "placebo"),
        ("Compared to metformin, placebo had no benefit.", "metformin"),
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
