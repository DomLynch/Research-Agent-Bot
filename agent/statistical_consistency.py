"""Shared deterministic p-value wording checks and repairs."""
from __future__ import annotations

import re

_ADJUSTED_RE = re.compile(
    r"\b(?:bonferroni|holm|false discovery|fdr|multiplicity|multiple[- ]testing|"
    r"prespecified alpha|significance threshold|adjusted (?:alpha|p[- ]?value|threshold|significance))\b",
    re.I,
)
_NON_SIGNIFICANT_RE = re.compile(
    r"\b(?:non[- ]?significant(?:ly)?|(?:not|no)\s+(?:statistically\s+)?significant(?:ly)?|"
    r"did\s+not\s+reach\s+significance)\b",
    re.I,
)
_WEAK_RE = re.compile(
    r"\b(?:marginal(?:ly)?|borderline|non\s*-?\s*significan\w*|"
    r"not(?:\s+\w+){0,2}\s+significan\w*|trend(?:ing|ed|s)?\s+to(?:ward|wards)?|a\s+trend)\b",
    re.I,
)
_P_RE = re.compile(r"\bp\s*(<=|>=|[=<>≤≥])\s*(\d*\.?\d+(?:e[-+]?\d+)?)", re.I)
_SIGNIFICANT_RE = re.compile(r"\b(?:nominally\s+)?(?:statistically\s+)?significant\b", re.I)
_CLAUSE_BOUNDARY = r"\n|\||;|\b(?:while|whereas|but)\b"


def nominal_significance(p_text: str) -> bool | None:
    """Classify one p-value at alpha=.05; loose bounds remain indeterminate."""
    match = _P_RE.search(p_text)
    if not match:
        return None
    operator, raw = match.groups()
    value = float(raw)
    if not 0 <= value <= 1:
        return None
    if operator == "=":
        return value < 0.05
    if operator == "<" and value <= 0.05 or operator in {"<=", "≤"} and value < 0.05:
        return True
    if operator in {">", ">=", "≥"} and value >= 0.05:
        return False
    return None


def has_adjusted_significance_threshold(text: str) -> bool:
    return bool(_ADJUSTED_RE.search(text))


def nominal_verification_statement(source: str, p_text: str, feedback: str) -> str | None:
    if nominal_significance(p_text) is not True:
        return None
    qualifier = (
        "did not cross the stated adjusted significance threshold"
        if has_adjusted_significance_threshold(feedback)
        else "was nominally statistically significant"
    )
    return f"Numeric verification note: {source} reported a mapped comparison ({p_text}) that {qualifier}."


def significance_wording_mismatch(sentence: str) -> bool:
    return any(_clause_mismatch(clause) for clause in re.split(
        _CLAUSE_BOUNDARY, sentence, flags=re.I,
    ))


def _clause_mismatch(clause: str) -> bool:
    values = list(_P_RE.finditer(clause))
    if not values:
        return False
    adjusted = has_adjusted_significance_threshold(clause)
    strong = not adjusted and bool(_WEAK_RE.search(clause)) and any(
        nominal_significance(match.group()) is True
        and (float(match.group(2)) < 0.01 or match.group(1) == "<" and float(match.group(2)) <= 0.01)
        for match in values
    )
    nominal = (
        bool(_NON_SIGNIFICANT_RE.search(clause))
        and not adjusted
        and all(nominal_significance(match.group()) is True for match in values)
    )
    overstated = (
        not adjusted and bool(_SIGNIFICANT_RE.search(_NON_SIGNIFICANT_RE.sub("", clause)))
        and all(nominal_significance(match.group()) is False for match in values)
    )
    return strong or nominal or overstated


def repair_unqualified_non_significant_p_values(text: str) -> tuple[str, int]:
    match = re.search(r"^##\s+References\b", text, flags=re.I | re.M)
    body, references = (text[:match.start()], text[match.start():]) if match else (text, "")
    chunks = re.split(rf"({_CLAUSE_BOUNDARY}|(?<=[.!?])\s+)", body, flags=re.I)
    changed = 0
    in_qei = False
    for index, sentence in enumerate(chunks):
        if heading := re.match(r"^##\s+(.+)", sentence):
            in_qei = heading.group(1).startswith("Quantitative Evidence Index")
        if in_qei:  # Source quotations are evidence, not generated interpretation.
            continue
        values = [nominal_significance(match.group()) for match in _P_RE.finditer(sentence)]
        if not values or has_adjusted_significance_threshold(sentence):
            continue
        if all(value is False for value in values):
            if _NON_SIGNIFICANT_RE.search(sentence):
                continue
            chunks[index], n = _SIGNIFICANT_RE.subn("non-significant", sentence)
            changed += bool(n)
            continue
        if not all(value is True for value in values) or not _NON_SIGNIFICANT_RE.search(sentence):
            continue
        fixed = re.sub(
            r"\bdid\s+not\s+reach\s+significance\b",
            "was nominally statistically significant",
            sentence,
            flags=re.I,
        )
        chunks[index] = _NON_SIGNIFICANT_RE.sub("nominally statistically significant", fixed)
        changed += 1
    return "".join(chunks) + references, changed


def repair_for_feedback(text: str, _feedback: str) -> tuple[str, int]:
    return repair_unqualified_non_significant_p_values(text)
