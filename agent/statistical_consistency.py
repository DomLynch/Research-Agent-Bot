"""Shared deterministic p-value wording checks and repairs."""
from __future__ import annotations

import re

_ADJUSTED_RE = re.compile(
    r"\b(?:bonferroni|holm|false discovery|fdr|multiplicity|multiple[- ]testing|"
    r"prespecified alpha|significance threshold|adjusted (?:alpha|p[- ]?value|threshold|significance))\b",
    re.I,
)
_NON_SIGNIFICANT_RE = re.compile(
    r"\b(?:non[- ]?significant(?:ly)?|not\s+(?:statistically\s+)?significant(?:ly)?|"
    r"did\s+not\s+reach\s+significance)\b",
    re.I,
)
_WEAK_RE = re.compile(
    r"\b(?:marginal(?:ly)?|borderline|non\s*-?\s*significan\w*|"
    r"not(?:\s+\w+){0,2}\s+significan\w*|trend(?:ing|ed|s)?\s+to(?:ward|wards)?|a\s+trend)\b",
    re.I,
)
_P_RE = re.compile(r"\bp\s*(=|<=?|≤)\s*(0?\.\d+)", re.I)


def has_adjusted_significance_threshold(text: str) -> bool:
    return bool(_ADJUSTED_RE.search(text))


def nominal_verification_statement(source: str, p_text: str, feedback: str) -> str | None:
    match = re.search(r"0?\.\d+", p_text)
    if not match or float(match.group()) >= 0.05:
        return None
    qualifier = (
        "did not cross the stated adjusted significance threshold"
        if has_adjusted_significance_threshold(feedback)
        else "was nominally statistically significant"
    )
    return f"Numeric verification note: {source} reported a mapped comparison ({p_text}) that {qualifier}."


def significance_wording_mismatch(sentence: str) -> bool:
    return any(_clause_mismatch(clause) for clause in re.split(
        r"\n|\||;|\b(?:while|whereas|but)\b", sentence, flags=re.I,
    ))


def _clause_mismatch(clause: str) -> bool:
    values = [(operator, float(value)) for operator, value in _P_RE.findall(clause)]
    if not values:
        return False
    adjusted = has_adjusted_significance_threshold(clause)
    strong = not adjusted and bool(_WEAK_RE.search(clause)) and any(
        value < 0.01 or operator == "<" and value <= 0.01 for operator, value in values
    )
    nominal = (
        bool(_NON_SIGNIFICANT_RE.search(clause))
        and not adjusted
        and all(value < 0.05 or operator == "<" and value <= 0.05 for operator, value in values)
    )
    return strong or nominal


def repair_unqualified_non_significant_p_values(text: str) -> tuple[str, int]:
    match = re.search(r"^##\s+References\b", text, flags=re.I | re.M)
    body, references = (text[:match.start()], text[match.start():]) if match else (text, "")
    chunks = re.split(r"(?<=[.!?])(\s+)", body)
    changed = 0
    for index, sentence in enumerate(chunks):
        values = [(operator, float(value)) for operator, value in _P_RE.findall(sentence)]
        if (
            not values or not _NON_SIGNIFICANT_RE.search(sentence)
            or has_adjusted_significance_threshold(sentence)
            or not all(value < 0.05 or operator == "<" and value <= 0.05 for operator, value in values)
        ):
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
