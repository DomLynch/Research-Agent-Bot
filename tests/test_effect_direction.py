"""Fix #5: effect direction with null + mixed states.

Discriminating tests: each test isolates one verdict path so a
regression in the inference logic is immediately attributable. The
load-bearing case is the MET-PREVENT (Witham 2025) null result —
0.001 m/s walk speed difference, p=0.96 — pre-fix this got
classified as 'unclear' or worse, masking the trial's actual null
finding."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import effect_direction as ed  # noqa: E402


def _const(sign: int):
    """Stub `metformin_effect_fn` that always returns the given sign."""
    return lambda c: sign


def _per_claim(signs: list[int]):
    """Stub that returns sign[i] for the i-th claim by index attr."""
    def _fn(c: dict) -> int:
        return signs[c.get("idx", 0)]
    return _fn


def test_no_signed_claims_no_p_values_returns_null() -> None:
    """A paper with no signed claims and no p-values reports nothing
    measurable → null (no movement reported anywhere)."""
    claims: list[dict[str, Any]] = [
        {"claim_type": "endpoint", "endpoint": "VO2max"},
    ]
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(0))
    assert result == "null"


def test_significant_unsigned_claim_returns_unclear_not_null() -> None:
    """A significant source statistic without a signed effect claim is
    ambiguous, not null. This prevents papers from saying "11/13 null"
    while source excerpts show significant associations."""
    claims = [
        {
            "claim_type": "p_value",
            "endpoint": "estimated pulse wave velocity",
            "raw_text": "p < 0.001",
            "numeric_values": [0.001],
        },
    ]
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(0))
    assert result == "unclear"


def test_witham_met_prevent_null_walk_speed_returns_null() -> None:
    """The load-bearing case. MET-PREVENT (Witham 2025) primary
    outcome: walk speed difference 0.001 m/s, p=0.96. Pre-fix this
    got `positive` (sign != 0) or `unclear` (sign == 0). Now: null."""
    claims = [
        # Walk speed effect statement: tiny magnitude, no significant p
        {
            "claim_type": "effect",
            "endpoint": "walk speed",
            "direction": "increase",  # nominally up by 0.001
            "arm": "metformin",
            "numeric_values": [0.001],
        },
        # Reported p-value
        {
            "claim_type": "p_value",
            "endpoint": "walk speed",
            "raw_text": "p = 0.96",
            "numeric_values": [0.96],
        },
    ]
    # Stub returns the actual sign from polarity*direction (positive=+1
    # since walk_speed polarity is +1 and direction=increase, arm=metformin)
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(1))
    assert result == "null", (
        f"MET-PREVENT walk speed must classify as null, got {result!r}"
    )


def test_significant_positive_only_returns_positive() -> None:
    """A paper with significant positive claims only → positive."""
    claims: list[dict[str, Any]] = [
        {"claim_type": "effect", "endpoint": "HbA1c", "direction": "decrease",
         "arm": "metformin"},
        {"claim_type": "p_value", "raw_text": "p < 0.001",
         "numeric_values": [0.001]},
    ]
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(1))
    assert result == "positive"


def test_significant_negative_only_returns_negative() -> None:
    """All significant negative → negative."""
    claims: list[dict[str, Any]] = [
        {"claim_type": "effect", "endpoint": "lean body mass",
         "direction": "decrease", "arm": "metformin"},
        {"claim_type": "p_value", "raw_text": "p < 0.01",
         "numeric_values": [0.005]},
    ]
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(-1))
    assert result == "negative"


def test_mixed_directions_significant_returns_mixed() -> None:
    """A paper with significant positive (HbA1c improved) AND
    significant negative (lean mass blunted) findings — both backed
    by their own significant p-values per endpoint — must classify
    as 'mixed'."""
    claims: list[dict[str, Any]] = [
        # HbA1c significant positive
        {"claim_type": "effect", "idx": 0, "endpoint": "HbA1c",
         "direction": "decrease", "arm": "metformin"},
        {"claim_type": "p_value", "endpoint": "HbA1c",
         "raw_text": "p < 0.001", "numeric_values": [0.0001]},
        # Lean body mass significant negative
        {"claim_type": "effect", "idx": 1, "endpoint": "lean body mass",
         "direction": "decrease", "arm": "metformin"},
        {"claim_type": "p_value", "endpoint": "lean body mass",
         "raw_text": "p < 0.001", "numeric_values": [0.0001]},
    ]
    # _per_claim is INDEXED by `idx` field. HbA1c effect has idx=0,
    # lean body mass effect has idx=1. p_value claims have no idx
    # (default 0). Want: signs[0]=+1 (HbA1c), signs[1]=-1 (lean mass).
    result = ed.infer_effect_direction(
        claims, metformin_effect_fn=_per_claim([+1, -1]),
    )
    assert result == "mixed"


def test_signed_but_no_significance_signal_returns_unclear() -> None:
    """Signs exist but no p-values and effect magnitude not negligible
    → unclear (legacy fallback)."""
    claims: list[dict[str, Any]] = [
        {
            "claim_type": "effect",
            "endpoint": "VO2max",
            "direction": "increase",
            "arm": "metformin",
            "numeric_values": [3.5],  # non-negligible
        },
    ]
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(1))
    assert result == "unclear"


def test_negligible_signed_no_p_values_returns_null() -> None:
    """Signs exist BUT all magnitudes negligible (≈ 0) AND no p-values
    → null (the change is too small to matter)."""
    claims = [
        {
            "claim_type": "effect",
            "endpoint": "walk speed",
            "direction": "increase",
            "arm": "metformin",
            "numeric_values": [0.001],
        },
    ]
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(1))
    assert result == "null"


def test_p_value_above_alpha_does_not_count_as_significant() -> None:
    """`p = 0.08` is not significant at the default α=0.05; signed
    claims are reported but no significance signal → unclear (or null
    if magnitudes negligible)."""
    claims = [
        {
            "claim_type": "effect", "endpoint": "VO2max",
            "direction": "increase", "arm": "metformin",
            "numeric_values": [2.5],
        },
        {
            "claim_type": "p_value", "raw_text": "p = 0.08",
            "numeric_values": [0.08],
        },
    ]
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(1))
    assert result == "unclear"


def test_lower_bound_p_value_does_not_count_as_significant() -> None:
    claims = [
        {
            "claim_type": "effect", "endpoint": "VO2max",
            "direction": "increase", "arm": "metformin",
            "numeric_values": [2.5],
        },
        {
            "claim_type": "p_value", "endpoint": "VO2max",
            "raw_text": "p > 0.001", "numeric_values": [0.001],
            "comparator": ">",
        },
    ]

    assert ed.infer_effect_direction(
        claims, metformin_effect_fn=_const(1),
    ) == "unclear"


def test_alpha_can_be_tightened() -> None:
    """Caller can pass a stricter alpha for sensitivity-analysis runs."""
    claims = [
        {
            "claim_type": "effect", "endpoint": "VO2max",
            "direction": "increase", "arm": "metformin",
            "numeric_values": [2.5],
        },
        {
            "claim_type": "p_value", "raw_text": "p = 0.04",
            "numeric_values": [0.04],
        },
    ]
    # At α=0.05: significant → positive
    result_default = ed.infer_effect_direction(
        claims, metformin_effect_fn=_const(1),
    )
    assert result_default == "positive"
    # At α=0.01: NOT significant → unclear
    result_strict = ed.infer_effect_direction(
        claims, metformin_effect_fn=_const(1), alpha=0.01,
    )
    assert result_strict == "unclear"


def test_p_value_extraction_from_raw_text_handles_variants() -> None:
    """Robustness: p-value parser must handle 'p < 0.05', 'p=0.0007',
    'P = 0.96', 'p<.001', 'P ≤ 0.01' (the conventional shapes)."""
    assert ed._parse_p_value("p < 0.05") == 0.05
    assert ed._parse_p_value("p=0.0007") == 0.0007
    assert ed._parse_p_value("P = 0.96") == 0.96
    assert ed._parse_p_value("p<.001") == 0.001
    assert ed._parse_p_value("p > 0.99") == 0.99


def test_p_value_extraction_returns_none_on_unparseable() -> None:
    assert ed._parse_p_value("") is None
    assert ed._parse_p_value("not a p-value") is None
    assert ed._parse_p_value("HR 0.85") is None


def test_negligible_threshold_is_001() -> None:
    """Magnitudes < 0.01 are treated as negligible (Witham case at
    0.001). Magnitudes >= 0.01 are not."""
    assert ed._negligible([0.001, 0.005, -0.003]) is True
    assert ed._negligible([0.001, 0.05]) is False  # 0.05 not negligible
    assert ed._negligible([]) is False  # empty list = no evidence


# ----- Reviewer-fix discriminating tests (post-2x review) ---------------


def test_per_endpoint_significance_does_not_bleed_across_endpoints() -> None:
    """P1 reviewer-flagged regression: paper-level significance attribution
    re-classified the Witham null as positive when an unrelated secondary
    endpoint had p<0.05. Now significance must be per-endpoint."""
    claims = [
        # Witham primary: walk_speed null (sign=+1 nominally, but no
        # significance for THIS endpoint)
        {
            "claim_type": "effect", "endpoint": "walk speed",
            "direction": "increase", "arm": "metformin",
            "numeric_values": [0.001],
        },
        {
            "claim_type": "p_value", "endpoint": "walk speed",
            "raw_text": "p = 0.96", "numeric_values": [0.96],
        },
        # Hypothetical secondary endpoint with significant p (HbA1c
        # improvement on the same paper, sign=+1)
        {
            "claim_type": "effect", "endpoint": "HbA1c",
            "direction": "decrease", "arm": "metformin",
            "numeric_values": [0.4],
        },
        {
            "claim_type": "p_value", "endpoint": "HbA1c",
            "raw_text": "p < 0.001", "numeric_values": [0.0001],
        },
    ]
    # The HbA1c claim is significant → contributes to sig_positive.
    # Walk_speed claim is NOT significant for ITS endpoint → does NOT
    # contribute. Net: one significant positive claim, no negative
    # claims → "positive" (the HbA1c improvement). Walk_speed null is
    # NOT misattributed.
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(1))
    assert result == "positive"


def test_only_significant_negative_endpoint_returns_negative_not_mixed() -> None:
    """Reviewer P1 follow-up: one significant negative + one signed-but-
    not-significant positive must return 'negative' (only the
    significant one counts), NOT 'mixed' (which would require BOTH to
    be significant)."""
    claims: list[dict[str, Any]] = [
        # Significant negative (lean mass blunting)
        {
            "claim_type": "effect", "idx": 0, "endpoint": "lean body mass",
            "direction": "decrease", "arm": "metformin",
            "numeric_values": [-2.5],
        },
        {
            "claim_type": "p_value", "endpoint": "lean body mass",
            "raw_text": "p < 0.001", "numeric_values": [0.0001],
        },
        # Non-significant positive (HbA1c trend)
        {
            "claim_type": "effect", "idx": 1, "endpoint": "HbA1c",
            "direction": "decrease", "arm": "metformin",
            "numeric_values": [0.1],
        },
        {
            "claim_type": "p_value", "endpoint": "HbA1c",
            "raw_text": "p = 0.4", "numeric_values": [0.4],
        },
    ]
    # First claim sign -1 (negative), second sign +1 (positive but
    # not significant for its endpoint).
    result = ed.infer_effect_direction(
        claims, metformin_effect_fn=_per_claim([-1, +1]),
    )
    assert result == "negative"


def test_sample_size_numeric_does_not_defeat_negligibility() -> None:
    """Reviewer P1 ship-blocker: pre-fix `_aggregate_paper` shipped
    `n=120` (sample_size) into `numeric_values`. The prior
    `_negligible` collected ALL non-p_value numerics; n=120 made
    every paper non-negligible → MET-PREVENT regressed to 'unclear'.
    Now: only effect-type claims with whitelisted-endpoint contribute."""
    claims = [
        {
            "claim_type": "effect", "endpoint": "walk speed",
            "direction": "increase", "arm": "metformin",
            "numeric_values": [0.001],
        },
        {
            "claim_type": "sample_size", "endpoint": "walk speed",
            "numeric_values": [120],  # sample size, not effect
        },
    ]
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(1))
    assert result == "null"


def test_p_value_extraction_handles_scientific_notation() -> None:
    """Reviewer P2: extract p=1.2e-5 correctly (pre-fix returned 1.2)."""
    assert ed._parse_p_value("p = 1.2e-5") == 1.2e-5
    assert ed._parse_p_value("p < 5.4E-08") == 5.4e-08
    assert ed._parse_p_value("P = 1e-6") == 1e-6


def test_p_value_extraction_handles_subscripted_p() -> None:
    """Reviewer P2: 'Padj < 0.05' and 'p_corr < 0.05' are conventional
    multi-comparison-corrected p-values."""
    assert ed._parse_p_value("Padj < 0.05") == 0.05
    assert ed._parse_p_value("p_corr < 0.01") == 0.01
    assert ed._parse_p_value("P-value: 0.03") == 0.03


def test_p_value_extraction_rejects_out_of_range() -> None:
    """Sanity: parsed values outside (0, 1] are not p-values — likely
    a parsing collision with HR / OR / RR numerics. Return None."""
    # Confirm 1.5 (invalid p) returns None
    assert ed._parse_p_value("p = 1.5") is None
    # 0.0 is a degenerate value (parser failures often produce it)
    # but the lower bound of [0, 1] accepts it. Confirm it's accepted
    # for completeness (caller's significance check uses 0 < p < alpha).
    assert ed._parse_p_value("p = 0") == 0.0


def test_negligible_check_only_fires_for_whitelisted_endpoints() -> None:
    """Reviewer P2: '_negligible' is unit-blind. Now restricted to a
    whitelist of endpoints whose units make the < 0.01 threshold
    meaningful. A non-whitelisted endpoint's tiny numeric value does
    NOT trigger null."""
    claims = [
        # AMPK signaling fold-change reported as 0.005 — NOT a
        # whitelisted endpoint, so don't auto-null it.
        {
            "claim_type": "effect", "endpoint": "AMPK signaling",
            "direction": "increase", "arm": "metformin",
            "numeric_values": [0.005],
        },
    ]
    result = ed.infer_effect_direction(claims, metformin_effect_fn=_const(1))
    # Signed but no significance → unclear (not null, because endpoint
    # is not whitelisted for negligibility check)
    assert result == "unclear"


def test_empty_claims_returns_unclear_not_null() -> None:
    """Reviewer P3: an empty claims list = 'no information', NOT
    'measured null'. Pre-fix returned null which silently classified
    a paper-with-zero-bound-claims as a real null result."""
    assert ed.infer_effect_direction(
        [], metformin_effect_fn=_const(0),
    ) == "unclear"
