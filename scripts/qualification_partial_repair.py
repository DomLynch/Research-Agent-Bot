"""Deterministic repair for source-exact partial qualification claims."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

ALLOWED_DIRECTIONS = {"increase", "decrease", "no_change"}
_CARRY_FORWARD_RE = re.compile(
    r"\b(?:median\s+survival|median\s+lifespan|life\s*span|lifespan|"
    r"the\s+treatment|treated\s+(?:mice|animals|patients)|"
    r"was\s+sufficient\s+to\s+extend|were\s+extended|was\s+extended)\b",
    re.IGNORECASE,
)
_DIRECTION_RE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "no_change",
        re.compile(
            r"\b(?:no\s+significant|not\s+significant|no\s+effect)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "decrease",
        re.compile(r"\b(?:decreas|reduc|lower|attenuat|suppress|slow)\w*", re.IGNORECASE),
    ),
    (
        "increase",
        re.compile(r"\b(?:increas|higher|extend|improv|enhanc|preserv)\w*", re.IGNORECASE),
    ),
)
_SPECIFIC_ARMS = (
    "mTOR inhibitor", "rapamycin", "sirolimus", "rapamune", "everolimus",
    "rad001", "rtb101", "erapa", "rapa", "rpm", "rap",
)
_ALLOWED_SOURCE_SECTIONS = {"abstract", "results"}
_REJECT_CONTEXT_RE = re.compile(
    r"\b(?:demographics?|gender\s+distribution|age\s+was\s+statistically|"
    r"BMI\s+was\s+similar|compounded\s+rapamycin|commercial\s+rapamycin|"
    r"dose-to-blood|blood\s+rapamycin\s+levels?)\b",
    re.IGNORECASE,
)


def norm(text: str) -> str:
    return " ".join(
        (text or "")
        .replace("\xa0", " ")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .split()
    )


def section_texts(parsed: dict[str, Any], max_chars: int) -> dict[str, str]:
    sections = parsed.get("sections") or {}
    out: dict[str, str] = {}
    budget = max_chars
    for name in ("abstract", "results", "discussion", "conclusion"):
        text = norm(str(sections.get(name) or ""))
        if not text or budget <= 0:
            continue
        out[name] = text[:budget]
        budget -= len(out[name])
    return out


def find_sentence(
    sections: dict[str, str], section: str, sentence: str,
) -> tuple[str, int] | None:
    wanted = norm(sentence)
    names = [section] if section in sections else list(sections)
    for name in names:
        idx = sections[name].find(wanted)
        if idx >= 0:
            return name, idx
    return None


def context_arm_supports(sentence: str, context: str, arm: str) -> bool:
    if not context or not arm or not _CARRY_FORWARD_RE.search(sentence):
        return False
    return re.search(
        rf"(?<![a-z0-9]){re.escape(arm)}(?![a-z0-9])",
        context,
        re.IGNORECASE,
    ) is not None


def _arm_hits(text: str, allowed_arms: set[str]) -> list[str]:
    low_allowed = {a.lower() for a in allowed_arms}
    hits: list[str] = []
    for arm in _SPECIFIC_ARMS:
        if arm not in low_allowed:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(arm)}(?![a-z0-9])", text, re.IGNORECASE):
            hits.append(arm)
    return hits


def _infer_arm(sentence: str, context: str, arm: str, allowed_arms: set[str]) -> str:
    arm = arm.lower().strip()
    if arm in allowed_arms and re.search(
        rf"(?<![a-z0-9]){re.escape(arm)}(?![a-z0-9])",
        sentence,
        re.IGNORECASE,
    ):
        return arm
    hits = _arm_hits(sentence, allowed_arms)
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return ""
    context_hits = _arm_hits(context, allowed_arms)
    if arm in allowed_arms and context_arm_supports(sentence, context, arm):
        return arm
    if len(context_hits) == 1 and context_arm_supports(sentence, context, context_hits[0]):
        return context_hits[0]
    return ""


def _infer_endpoint(
    sentence: str,
    endpoint: str,
    endpoint_map: dict[str, str],
    endpoint_patterns: dict[str, re.Pattern[str]],
) -> str:
    if endpoint in endpoint_map:
        pattern = endpoint_patterns.get(endpoint)
        if pattern is None or pattern.search(sentence):
            return endpoint
    matches = [
        label for label, pattern in endpoint_patterns.items()
        if label in endpoint_map and pattern.search(sentence)
    ]
    return matches[0] if len(matches) == 1 else ""


def _infer_direction(sentence: str, direction: str) -> str:
    if direction in ALLOWED_DIRECTIONS:
        return direction
    for label, pattern in _DIRECTION_RE:
        if pattern.search(sentence):
            return label
    return ""


def _context_before(section_text: str, offset: int, limit: int = 500) -> str:
    return "" if offset < 0 else norm(section_text[max(0, offset - limit): offset])


def propose_partial_repairs(
    paper: Any,
    *,
    parsed: dict[str, Any],
    quant_data: dict[str, Any],
    endpoint_map: dict[str, str],
    endpoint_patterns: dict[str, re.Pattern[str]],
    arms: set[str],
    max_chars: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    sections = section_texts(parsed, max_chars)
    accepted: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    for old in quant_data.get("claims") or []:
        if not isinstance(old, dict) or old.get("binding_confidence") == "high":
            continue
        sentence = norm(str(old.get("sentence") or ""))
        section = str(old.get("source_section") or "").strip().lower()
        found = find_sentence(sections, section, sentence)
        if found is None:
            rejected["sentence_not_in_source"] += 1
            continue
        section, offset = found
        if section not in _ALLOWED_SOURCE_SECTIONS:
            rejected["source_section_not_allowed"] += 1
            continue
        if _REJECT_CONTEXT_RE.search(sentence):
            rejected["background_or_demographic_context"] += 1
            continue
        context = _context_before(sections[section], offset)
        endpoint = _infer_endpoint(
            sentence, str(old.get("endpoint") or "").strip(),
            endpoint_map, endpoint_patterns,
        )
        arm = _infer_arm(sentence, context, str(old.get("arm") or ""), arms)
        direction = _infer_direction(sentence, str(old.get("direction") or ""))
        if not endpoint:
            rejected["no_endpoint_inference"] += 1
            continue
        if not arm:
            rejected["no_arm_inference"] += 1
            continue
        if not direction:
            rejected["no_direction_inference"] += 1
            continue
        raw = dict(old)
        raw.update({
            "source_sentence": sentence,
            "source_section": section,
            "source_context": context,
            "endpoint": endpoint,
            "arm": arm,
            "direction": direction,
        })
        accepted.append(raw)
    return accepted, rejected


__all__ = [
    "context_arm_supports",
    "propose_partial_repairs",
]
