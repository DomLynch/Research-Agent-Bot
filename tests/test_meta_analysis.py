from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from meta_analysis import (  # noqa: E402
    forest_plot_contract,
    funnel_plot_contract,
    pool_fixed_effect,
)


def test_meta_analysis_fails_closed_with_insufficient_compatible_data() -> None:
    result = pool_fixed_effect("mortality", [
        {"outcome": "mortality", "effect_measure": "mean_difference", "effect": 0.2}
    ])

    assert result.fail_closed
    assert result.reason == "insufficient_compatible_effect_sizes"
    assert result.pooled_effect is None


def test_meta_analysis_fails_closed_for_mixed_effect_measures() -> None:
    result = pool_fixed_effect("mortality", [
        {
            "outcome": "mortality",
            "effect_measure": "mean_difference",
            "effect": 0.2,
            "standard_error": 0.1,
        },
        {
            "outcome": "mortality",
            "effect_measure": "odds_ratio",
            "effect": 1.1,
            "standard_error": 0.2,
        },
    ])

    assert result.fail_closed
    assert result.reason == "mixed_effect_measures"


def test_meta_analysis_pools_compatible_effects() -> None:
    result = pool_fixed_effect("mortality", [
        {
            "receipt_id": "a",
            "outcome": "mortality",
            "effect_measure": "mean_difference",
            "effect": 0.2,
            "standard_error": 0.1,
        },
        {
            "receipt_id": "b",
            "outcome": "mortality",
            "effect_measure": "mean_difference",
            "effect": 0.4,
            "standard_error": 0.1,
        },
    ])

    assert not result.fail_closed
    assert result.k == 2
    assert result.pooled_effect == 0.3


def test_high_risk_of_bias_is_excluded_and_blocks_pooling() -> None:
    result = pool_fixed_effect("mortality", [
        {
            "outcome": "mortality",
            "effect_measure": "mean_difference",
            "effect": 0.2,
            "standard_error": 0.1,
            "risk_of_bias": "high",
        },
        {
            "outcome": "mortality",
            "effect_measure": "mean_difference",
            "effect": 0.4,
            "standard_error": 0.1,
        },
    ])

    assert result.fail_closed
    assert result.reason == "high_risk_of_bias_excluded"


def test_plot_contracts_need_no_plotting_dependency() -> None:
    result = pool_fixed_effect("mortality", [])

    assert forest_plot_contract(result)["status"] == "placeholder_no_plotting_dependency"
    assert funnel_plot_contract(result)["requires"] == [
        "study_effect",
        "standard_error",
        "effect_measure",
    ]
