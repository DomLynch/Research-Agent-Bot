"""Infer positive, negative, null, mixed, or unclear effect direction."""
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
    parsed = _parse_p_comparison(raw_text)
    return parsed[1] if parsed else None


def _parse_p_comparison(raw_text: str) -> tuple[str, float] | None:
    """Return the normalized comparator and value for a p-value."""
    if not raw_text:
        return None
    s = raw_text.replace("\xa0", " ").strip()
    # Allow word-suffix on P (Padj, p_corr, P-value, P_adjusted) —
    # consume letters/underscores/hyphens until we hit a separator.
    # Two acceptable separators: `[<>=≤≥]` (with optional space) or a
    # bare `:` (for 'P-value: 0.05'). Scientific notation tried FIRST
    # so `1.2e-5` doesn't get truncated to 1.2.
    m = re.search(
        r"[Pp][_\-a-zA-Z]*\s*(<=|>=|[<>=≤≥]|:)\s*"
        r"(\d+\.?\d*[eE][+-]?\d+|0?\.\d+|\d+\.\d+|\d+)",
        s,
    )
    if not m:
        return None
    try:
        val = float(m.group(2))
    except (ValueError, TypeError):
        return None
    # Sanity: a parsed p-value should be in (0, 1]. Outside that range
    # is almost certainly a parsing collision (a non-p-value number).
    if not (0.0 <= val <= 1.0):
        return None
    comparator = {"≤": "<=", "≥": ">=", ":": "="}.get(
        m.group(1), m.group(1),
    )
    return comparator, val


def _comparison_is_significant(comparator: str, value: float, alpha: float) -> bool:
    if not (0.0 <= value <= 1.0):
        return False
    if comparator in ("<", "<="):
        return value <= alpha
    if comparator == "=":
        return value < alpha
    return False


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
    "effect", "endpoint_change", "outcome", "endpoint", "unit_value",
})
_DIRECTION_TERM = r"(?:improv(?:e[ds]?|ing|ements?)|increas(?:e[ds]?|ing)|decreas(?:e[ds]?|ing)|reduc(?:e[ds]?|ing))"
_SIGNIFICANCE_RE = re.compile(
    rf"\b(?:statistically\s+)?significant(?:ly)?\s+{_DIRECTION_TERM}\b"
    rf"|\b{_DIRECTION_TERM}\s+(?:was\s+)?(?:statistically\s+)?significant(?:ly)?\b",
    re.I,
)
_NEGATED_SIGNIFICANCE_RE = re.compile(
    r"\b(?:no|not|without|lack(?:ed|ing|s)?|absen(?:t|ce))\b"
    r"|\b(?:fail(?:ed|s)?|failure)\s+to\b|\bnon[-\s]?$",
    re.I,
)


def _reports_significance(claim: dict) -> bool:
    text = str(claim.get("sentence") or claim.get("context_window") or "")
    clauses = re.split(r";|(?<!\d)[.!?](?!\d)|,?\s+\b(?:but|while|whereas)\b\s+", text, flags=re.I)
    raw = str(claim.get("raw_text") or "").lower()
    endpoint = str(claim.get("endpoint") or "").lower()
    scores = [int(bool(raw and raw in part.lower())) + 2 * int(bool(endpoint and endpoint in part.lower())) for part in clauses]
    best = max(scores, default=0)
    if best and scores.count(best) != 1:
        return False
    scope = clauses[scores.index(best)] if best else text
    matches = list(_SIGNIFICANCE_RE.finditer(scope))
    if not matches:
        return False
    lower_scope = scope.lower()
    raw_positions = [match.start() for match in re.finditer(re.escape(raw), lower_scope)] if raw else []
    endpoint_positions = [match.start() for match in re.finditer(re.escape(endpoint), lower_scope)] if endpoint else []
    anchor = raw_positions[0] if len(raw_positions) == 1 else endpoint_positions[0] if len(endpoint_positions) == 1 else -1
    if anchor < 0:
        return False
    match = min(matches, key=lambda item: abs(item.start() - anchor))
    prefix = re.split(r",\s+and\s+", scope[:match.start()], flags=re.I)[-1]
    suffix = re.split(r",\s+and\s+", scope[match.end():], maxsplit=1, flags=re.I)[0]
    return not (_NEGATED_SIGNIFICANCE_RE.search(prefix) or re.search(r"\bclinically\s*$", prefix, re.I)
                or _NEGATED_SIGNIFICANCE_RE.search(suffix))


def _negligible(values: list[float]) -> bool:
    """True if every value is essentially zero (|v| < 0.01). Caller is
    responsible for filtering values to the appropriate units (use
    `_NEGLIGIBLE_CHECK_ENDPOINTS` to gate). Empty list → False."""
    if not values:
        return False
    return all(abs(v) < 0.01 for v in values)


def _reports_null(claim: dict, alpha: float) -> bool:
    if claim.get("claim_role") not in {None, "effect"}:
        return False
    if claim.get("direction") == "no_change":
        return True
    comparison = _parse_p_comparison(str(claim.get("raw_text") or ""))
    return bool(claim.get("claim_type") == "p_value" and claim.get("endpoint")
                and comparison and comparison[0] in {"=", ">", ">="} and comparison[1] >= alpha)


def source_outcome_claims(record: dict) -> list[dict]:
    """Retain qualitative own-study outcomes that numeric extraction cannot represent."""
    from quant_claim_extract import source_result_excerpts
    from quant_endpoints import match_direction, match_endpoint
    claims = []
    for sentence in source_result_excerpts(record, require_numeric=False):
        for clause in re.split(r";|\b(?:but|whereas|while|however)\b", sentence, flags=re.I):
            endpoint = match_endpoint(clause)
            direction = match_direction(clause, anchor_offset=clause.casefold().find(endpoint.casefold()))
            if not endpoint or not direction or re.search(r"\b(?:may|might|could|hypothes\w*|baseline|previous|prior)\b", clause, re.I):
                continue
            claims.append({"endpoint": endpoint, "direction": direction, "sentence": clause,
                           "raw_text": endpoint, "claim_role": "effect", "claim_type": "qualitative_outcome"})
    return claims


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
            - positive/negative alongside explicit null findings → mixed
            - otherwise positive only, negative only, or both → positive/negative/mixed
      4. No significant signs:
            - signed-but-negligible-magnitude (whitelisted endpoints) → null
            - claims exist but all unsigned → unclear
            - signed with non-negligible magnitude → unclear

    Empty claims list returns "unclear" (no information, NOT a null
    measurement) per reviewer P3."""
    # Baseline balance, dose and sample descriptors cannot establish an outcome.
    claims = [c for c in claims if c.get("claim_role") not in {"baseline", "population", "background", "dose", "duration", "sample_size", "protocol"}]
    if not claims:
        return "unclear"

    significance_by_endpoint = _significance_by_endpoint(claims, alpha)

    sig_positive = False
    sig_negative = False
    any_signed = False
    explicit_null = any(_reports_null(c, alpha) for c in claims)
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
        if sign != 0 and (
            significance_by_endpoint.get(endpoint, False) and ctype != "qualitative_outcome"
            or (
                (endpoint not in significance_by_endpoint or ctype == "qualitative_outcome")
                and _reports_significance(c)
            )
        ):
            if sign > 0:
                sig_positive = True
            elif sign < 0:
                sig_negative = True

    if (sig_positive and sig_negative) or (explicit_null and (sig_positive or sig_negative)):
        return "mixed"
    if sig_positive:
        return "positive"
    if sig_negative:
        return "negative"
    # Unsigned evidence is not a measured null result. Keep it ambiguous
    # unless an explicit negligible signed magnitude established nullity.
    if not any_signed:
        null_endpoints = {c.get("endpoint") for c in claims if c.get("endpoint") and _reports_null(c, alpha)}
        if null_endpoints and {c.get("endpoint") for c in claims if c.get("endpoint")} <= null_endpoints and not any(significance_by_endpoint.values()):
            return "null"
        return "unclear"
    # No significant signed evidence.
    if effect_magnitudes_whitelisted and _negligible(
        effect_magnitudes_whitelisted
    ):
        return "null"
    return "unclear"


def _significance_by_endpoint(
    claims: list[dict], alpha: float,
) -> dict[str, bool]:
    """Build endpoint significance while retaining explicit null p-values."""
    has_sig: dict[str, bool] = {}
    for c in claims:
        if c.get("claim_type") != "p_value":
            continue
        endpoint = (c.get("endpoint") or "").strip()
        parsed = _parse_p_comparison(c.get("raw_text") or "")
        comparator = str(c.get("comparator") or (parsed[0] if parsed else "="))
        values = c.get("numeric_values") or (() if parsed is None else (parsed[1],))
        sig = False
        valid = False
        for value in values:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            valid = True
            if _comparison_is_significant(comparator, numeric, alpha):
                sig = True
                break
        if valid:
            has_sig[endpoint] = has_sig.get(endpoint, False) or sig
    return has_sig
