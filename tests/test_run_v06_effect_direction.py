from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_v06_synthesis as run_v06  # noqa: E402


def test_blank_arm_uses_active_topic_sentence_context() -> None:
    run_v06._set_topic("creatine")
    claim = {
        "claim_type": "unit_value",
        "endpoint": "muscle strength",
        "direction": "increase",
        "arm": "",
        "numeric_values": [1.37],
        "sentence": (
            "Creatine supplementation resulted in greater increases in "
            "lean tissue mass and strength."
        ),
    }

    assert run_v06._claim_topic_effect(claim) == 1


def test_blank_arm_without_active_context_is_unclear_not_negative() -> None:
    run_v06._set_topic("creatine")
    claim = {
        "claim_type": "unit_value",
        "endpoint": "muscle strength",
        "direction": "increase",
        "arm": "",
        "numeric_values": [1.37],
        "sentence": "Participants showed greater increases in lean tissue mass.",
    }

    assert run_v06._claim_topic_effect(claim) == 0


def test_placebo_arm_is_comparator_context_not_treatment_direction() -> None:
    run_v06._set_topic("creatine")
    claim = {
        "claim_type": "unit_value",
        "endpoint": "muscle strength",
        "direction": "increase",
        "arm": "placebo",
        "numeric_values": [1.37],
        "sentence": "The placebo group changed during follow-up.",
    }

    assert run_v06._claim_topic_effect(claim) == 0


def test_placebo_arm_comparison_phrase_can_anchor_active_effect() -> None:
    run_v06._set_topic("creatine")
    claim = {
        "claim_type": "unit_value",
        "endpoint": "muscle strength",
        "direction": "increase",
        "arm": "placebo",
        "numeric_values": [1.0],
        "sentence": (
            "The increase in leg muscle mass translated to a significant "
            "increase in leg muscle strength for the intervention group, "
            "which was also greater than that of the placebo group."
        ),
    }

    assert run_v06._claim_topic_effect(claim) == 1


def test_effect_p_value_with_direction_can_anchor_effect_direction() -> None:
    run_v06._set_topic("creatine")
    claim = {
        "claim_type": "p_value",
        "claim_role": "effect",
        "endpoint": "muscle strength",
        "direction": "increase",
        "arm": "placebo",
        "numeric_values": [0.0007],
        "sentence": (
            "Creatine supplementation resulted in greater increases than "
            "placebo for chest press strength."
        ),
    }

    assert run_v06._claim_topic_effect(claim) == 1


def test_non_effect_p_value_stays_unsigned() -> None:
    run_v06._set_topic("creatine")
    claim = {
        "claim_type": "p_value",
        "claim_role": "population",
        "endpoint": "muscle strength",
        "direction": "increase",
        "arm": "creatine",
        "numeric_values": [0.0007],
        "sentence": "Baseline groups differed by age.",
    }

    assert run_v06._claim_topic_effect(claim) == 0
