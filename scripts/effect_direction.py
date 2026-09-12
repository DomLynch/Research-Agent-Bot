"""Infer positive, negative, null, mixed, or unclear effect direction."""
from __future__ import annotations

import re
from typing import Any


# Significance threshold. Conservative (0.05) — this is the
# conventional bar; downstream callers can pass a tighter alpha if
# they want stricter classification.
_DEFAULT_ALPHA = 0.05


def _parse_p_value(raw_text: str) -> float | None:
    """Parse a reported p-value, preserving comparison semantics in the shared parser."""
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


_DIRECTION_TERM = r"(?:improv(?:e[ds]?|ing|ements?)|increas(?:e[ds]?|ing)|decreas(?:e[ds]?|ing)|reduc(?:e[ds]?|ing)|enhanc(?:e[ds]?|ing))"
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
    text = re.sub(r"\(\s*[pP]\s*[<=>≤≥][^)]*\)", "", text)
    text = re.sub(r";\s*(?:however,?\s*)?(?=the (?:increase|decrease|improvement) was significant)", " ", text, flags=re.I)
    clauses = re.split(r";(?![^()]*\))|(?<!\d)[.!?](?!\d)|,?\s+\b(?:but|while|whereas)\b\s+", text, flags=re.I)
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
    from quant_endpoints import match_direction, match_endpoint, _ENDPOINT_COMPILED
    claims = []
    for sentence in source_result_excerpts(record, require_numeric=False):
        for clause in re.split(r";(?![^()]*\))|\b(?:but|whereas|while|however)\b|\s+and (?=(?:greater|lower|higher|smaller)\b)", re.sub(r";\s*however,?\s*(?=the (?:increase|decrease|improvement) was significant)", " ", sentence, flags=re.I), flags=re.I):
            endpoint = match_endpoint(clause)
            matched = next((pattern.search(clause) for name, pattern in _ENDPOINT_COMPILED if name == endpoint and pattern.search(clause)), None)
            direction = match_direction(clause, anchor_offset=matched.start() if matched else None)
            if not endpoint or not direction or re.search(r"\b(?:may|might|could|hypothes\w*|baseline|previous|prior)\b", clause, re.I):
                continue
            p_values = list(re.finditer(r"\bp\s*(?:<=|>=|[<=>≤≥])\s*0?\.\d+", clause, re.I))
            own_p = _parse_p_comparison(p_values[0][0]) if len(p_values) == 1 and len({name for name, pattern in _ENDPOINT_COMPILED if pattern.search(clause)}) == 1 else None
            claims.append({"endpoint": endpoint, "direction": direction, "sentence": clause, "source_p_value": own_p,
                           "raw_text": matched[0] if matched else endpoint, "claim_role": "effect", "claim_type": "qualitative_outcome"})
    return claims


def infer_effect_direction(
    claims: list[dict],
    *,
    metformin_effect_fn: Any,
    alpha: float = _DEFAULT_ALPHA,
) -> str:
    """Aggregate source-owned outcomes with endpoint-specific significance.

    Unmeasured or unsigned outcomes remain unclear; significant effects and
    explicit null outcomes yield mixed. Qualitative claims need their own
    significance statement and cannot borrow a numeric endpoint's p-value.
    """
    # Baseline balance, dose and sample descriptors cannot establish an outcome.
    claims = [c for c in claims if c.get("claim_role") not in {"baseline", "population", "background", "dose", "duration", "sample_size", "protocol"}]
    if not claims:
        return "unclear"

    significance_by_endpoint = _significance_by_endpoint(claims, alpha)

    sig_positive = False
    sig_negative = False
    explicit_null = any(_reports_null(c, alpha) for c in claims)

    for c in claims:
        sign = metformin_effect_fn(c)
        endpoint = (c.get("endpoint") or "").strip()
        ctype = c.get("claim_type") or ""
        # Per-endpoint significance attribution. The signed claim
        # contributes to the significant tally ONLY IF its specific
        # endpoint has a significant p-value (paper-level signal is
        # not enough — the original bug we're fixing).
        if sign != 0 and (
            significance_by_endpoint.get(endpoint, False) and ctype != "qualitative_outcome"
            or (
                (endpoint not in significance_by_endpoint or ctype == "qualitative_outcome")
                and (_comparison_is_significant(c["source_p_value"][0], c["source_p_value"][1], alpha) if c.get("source_p_value") else _reports_significance(c))
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
    # Neither an unsigned claim nor a small number establishes a null outcome.
    null_endpoints = {c.get("endpoint") for c in claims if c.get("endpoint") and _reports_null(c, alpha)}
    if null_endpoints and {c.get("endpoint") for c in claims if c.get("endpoint")} <= null_endpoints and not any(significance_by_endpoint.values()) and not any(_reports_significance(c) for c in claims):
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
