"""Fix #5: Effect-direction inference with null and mixed states.

Pre-fix `_aggregate_paper` collapsed all per-claim signs into a single
sum and emitted `positive | negative | unclear`. This had two real
bugs:

  1. **Null was missing.** A trial reporting 0.001 m/s walk-speed
     improvement (p=0.96) — the literal MET-PREVENT (Witham 2025)
     primary outcome — got tagged `unclear` rather than `null`,
     which then propagated to the synthesis as either ambiguous or
     mis-grouped under positive/negative effect classes.

  2. **Mixed was missing.** A paper reporting both significant
     positive (HbA1c improvement) AND significant negative
     (resistance-training adaptation blunting) findings collapsed
     to whichever sign won the sum, hiding the conflict.

Fix: deterministic per-claim significance + sign aggregation,
producing one of {positive, negative, null, mixed, unclear}.

  - `null`     : no statistically-significant claim AND any signed
                 claims have negligible magnitude
  - `mixed`    : significant signed claims disagree across endpoints
  - `positive` : significant signed claims agree positive
  - `negative` : significant signed claims agree negative
  - `unclear`  : signed claims with no significance signal AND no
                 negligible-magnitude evidence (legacy behaviour)

Acceptance is about source validity, not benefit direction. A null
or mixed result is a valid SHIPPED state — the writer can then
truthfully report 'no improvement' or 'context-dependent effect'.

Architecture: pure deterministic, no LLM. Operates on the same
claim-dict shape `_aggregate_paper` already builds."""
from __future__ import annotations

import re
from typing import Any


# Significance threshold. Conservative (0.05) — this is the
# conventional bar; downstream callers can pass a tighter alpha if
# they want stricter classification.
_DEFAULT_ALPHA = 0.05


def _parse_p_value(raw_text: str) -> float | None:
    """Best-effort p-value extraction from a claim's raw_text. Returns
    None when nothing parseable.

    Handles common shapes:
      'p < 0.05', 'p=0.0007', 'P = 0.96', 'p<.001', 'p < 0.001',
      'p = 1.2e-5' (scientific notation, P1 reviewer fix), 'P ≤ 0.01',
      'Padj < 0.05', 'p_corr < 0.05' (subscripted P variants).
    """
    if not raw_text:
        return None
    s = raw_text.replace("\xa0", " ").strip()
    # Allow word-suffix on P (Padj, p_corr, P-value, P_adjusted) —
    # consume letters/underscores/hyphens until we hit a separator.
    # Two acceptable separators: `[<>=≤≥]` (with optional space) or a
    # bare `:` (for 'P-value: 0.05'). Scientific notation tried FIRST
    # so `1.2e-5` doesn't get truncated to 1.2.
    m = re.search(
        r"[Pp][_\-a-zA-Z]*\s*(?:[<>=≤≥]|:)\s*"
        r"(\d+\.?\d*[eE][+-]?\d+|0?\.\d+|\d+\.\d+|\d+)",
        s,
    )
    if not m:
        return None
    try:
        val = float(m.group(1))
    except (ValueError, TypeError):
        return None
    # Sanity: a parsed p-value should be in (0, 1]. Outside that range
    # is almost certainly a parsing collision (a non-p-value number).
    if not (0.0 <= val <= 1.0):
        return None
    return val


# Endpoints whose effect magnitudes are reported in units where
# |v| < 0.01 reliably indicates a negligible change. Walk speed (m/s),
# HbA1c (%), body composition (kg), continuous biomarkers — magnitudes
# below 0.01 in these units are clinically null. The whitelist exists
# because the negligible check is otherwise unit-blind: a hazard ratio
# of 0.005 or a fold-change of 0.008 would falsely test as null.
_NEGLIGIBLE_CHECK_ENDPOINTS: frozenset[str] = frozenset({
    "walk speed", "VO2max", "thigh muscle mass", "lean body mass",
    "muscle hypertrophy", "muscle strength", "body weight",
    "body mass index", "HbA1c", "fasting glucose", "blood glucose",
    "blood pressure", "cardiorespiratory fitness", "frailty",
    "sarcopenia", "protein synthesis",
})

# Claim types whose numeric_values represent EFFECT magnitudes (not
# p-values, not sample sizes). Used to filter noise out of the
# negligible check. Pre-fix `numeric_values` from `sample_size` claims
# (n=120) defeated the negligibility check for the Witham case.
_EFFECT_MAGNITUDE_CLAIM_TYPES: frozenset[str] = frozenset({
    "effect", "endpoint_change", "outcome", "endpoint",
})


def _negligible(values: list[float]) -> bool:
    """True if every value is essentially zero (|v| < 0.01). Caller is
    responsible for filtering values to the appropriate units (use
    `_NEGLIGIBLE_CHECK_ENDPOINTS` to gate). Empty list → False."""
    if not values:
        return False
    return all(abs(v) < 0.01 for v in values)


def infer_effect_direction(
    claims: list[dict],
    *,
    metformin_effect_fn: Any,
    alpha: float = _DEFAULT_ALPHA,
) -> str:
    """Aggregate per-claim signs + significance into one of:
    positive | negative | null | mixed | unclear.

    Caller passes `metformin_effect_fn(claim) -> int` (the existing
    polarity-aware sign function in run_v06_synthesis); this lets the
    inference work for any drug pack without importing the polarity
    table here.

    Algorithm (P1 reviewer fix — per-endpoint significance):
      1. Build {endpoint: any_significant_p} map from p_value claims.
      2. For each signed effect claim, check ITS endpoint's significance
         (NOT paper-level). This prevents an unrelated significant
         secondary endpoint from re-classifying a null primary outcome
         as positive.
      3. If any significant sign exists:
            - all positive → positive
            - all negative → negative
            - both         → mixed
      4. No significant signs:
            - signed-but-negligible-magnitude (whitelisted endpoints) → null
            - claims exist but all unsigned → null
            - signed with non-negligible magnitude → unclear

    Empty claims list returns "unclear" (no information, NOT a null
    measurement) per reviewer P3."""
    if not claims:
        return "unclear"

    significance_by_endpoint = _significance_by_endpoint(claims, alpha)

    sig_positive = False
    sig_negative = False
    any_signed = False
    effect_magnitudes_whitelisted: list[float] = []

    for c in claims:
        sign = metformin_effect_fn(c)
        if sign != 0:
            any_signed = True
        endpoint = (c.get("endpoint") or "").strip()
        ctype = c.get("claim_type") or ""
        # Magnitude collection: ONLY from effect-type claims AND only
        # for endpoints whose units make the negligible check meaningful.
        if (
            ctype in _EFFECT_MAGNITUDE_CLAIM_TYPES
            and endpoint in _NEGLIGIBLE_CHECK_ENDPOINTS
        ):
            for v in c.get("numeric_values") or []:
                try:
                    effect_magnitudes_whitelisted.append(float(v))
                except (ValueError, TypeError):
                    continue
        # Per-endpoint significance attribution. The signed claim
        # contributes to the significant tally ONLY IF its specific
        # endpoint has a significant p-value (paper-level signal is
        # not enough — the original bug we're fixing).
        if sign != 0 and significance_by_endpoint.get(endpoint, False):
            if sign > 0:
                sig_positive = True
            elif sign < 0:
                sig_negative = True

    if sig_positive and sig_negative:
        return "mixed"
    if sig_positive:
        return "positive"
    if sig_negative:
        return "negative"
    # No significant signed evidence.
    if not any_signed:
        return "null"
    if effect_magnitudes_whitelisted and _negligible(
        effect_magnitudes_whitelisted
    ):
        return "null"
    return "unclear"


def _significance_by_endpoint(
    claims: list[dict], alpha: float,
) -> dict[str, bool]:
    """Build {endpoint: True} for every endpoint that has at least
    one significant p-value (p < alpha). Used by the per-endpoint
    significance attribution in infer_effect_direction."""
    has_sig: dict[str, bool] = {}
    for c in claims:
        if c.get("claim_type") != "p_value":
            continue
        endpoint = (c.get("endpoint") or "").strip()
        # numeric_values takes precedence
        sig = False
        for v in c.get("numeric_values") or []:
            try:
                p = float(v)
            except (ValueError, TypeError):
                continue
            if 0.0 < p < alpha:
                sig = True
                break
        # Fallback to raw_text parsing
        if not sig:
            p = _parse_p_value(c.get("raw_text") or "")
            if p is not None and 0.0 < p < alpha:
                sig = True
        if sig:
            has_sig[endpoint] = True
    return has_sig
