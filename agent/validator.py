from __future__ import annotations

import re
from typing import Any

from agent.citation_roles import ROLE_LANGUAGE_RULES


_CITATION_RE = re.compile(r"\[(\d+)\]")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_NUMERIC_SECTIONS = {"Key Findings", "Conclusion"}
_NEGATIVE_EFFECT_RE = re.compile(r"\b(no significant|no difference|did not (?:improve|reduce|increase)|not significant)\b", re.IGNORECASE)
_POSITIVE_EFFECT_RE = re.compile(r"\b(improved|reduced|increased|lowered|raised|benefit|significant(?:ly)?)\b", re.IGNORECASE)
_SIGNIFICANT_P_RE = re.compile(r"\bp\s*(?:=|<)\s*0\.0[0-4]\d*\b", re.IGNORECASE)
_RAW_EXTRACTION_RE = re.compile(r"\bPublished results \[\d+\] report\b", re.IGNORECASE)


def _window(text: str, start: int, end: int, *, radius: int = 120) -> str:
    return " ".join(text[max(0, start - radius): min(len(text), end + radius)].split())


def _severity(issue: str) -> str:
    return {"forbidden_phrase": "high", "citation_out_of_range": "low"}.get(issue, "medium")


def validate_citations(draft: dict[str, Any], source_bundle: list[dict[str, Any]], *, strict: bool = False) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    sections = draft.get("sections") or {}
    for heading, text in sections.items():
        body = str(text or "")
        for match in _CITATION_RE.finditer(body):
            ref = int(match.group(1))
            if ref < 1 or ref > len(source_bundle):
                violations.append(
                    {
                        "section": heading,
                        "citation": ref,
                        "severity": _severity("citation_out_of_range"),
                        "issue": "citation_out_of_range",
                        "window": _window(body, match.start(), match.end()),
                    }
                )
                continue
            source = source_bundle[ref - 1]
            role = str(source.get("role") or "unknown")
            rules = ROLE_LANGUAGE_RULES.get(role, {})
            window = _window(body, match.start(), match.end())
            lowered = window.lower()

            for phrase in rules.get("forbidden", []):
                if phrase.lower() in lowered:
                    violations.append(
                        {
                            "section": heading,
                            "citation": ref,
                            "role": role,
                            "severity": _severity("forbidden_phrase"),
                            "issue": "forbidden_phrase",
                            "phrase": phrase,
                            "window": window,
                        }
                    )

            hedge_re = rules.get("requires_hedge")
            if hedge_re and not re.search(str(hedge_re), lowered, re.IGNORECASE):
                violations.append(
                    {
                        "section": heading,
                        "citation": ref,
                        "role": role,
                        "severity": _severity("missing_hedge"),
                        "issue": "missing_hedge",
                        "window": window,
                    }
                )

            if rules.get("requires_numeric") and (strict or heading in _NUMERIC_SECTIONS):
                if not _NUMBER_RE.search(re.sub(r"\[\d+\]", "", window)):
                    violations.append(
                        {
                            "section": heading,
                            "citation": ref,
                            "role": role,
                            "severity": _severity("missing_numeric"),
                            "issue": "missing_numeric",
                            "window": window,
                        }
                    )
    return violations


def _cited_windows(text: str) -> dict[int, list[str]]:
    windows: dict[int, list[str]] = {}
    for match in _CITATION_RE.finditer(text):
        windows.setdefault(int(match.group(1)), []).append(_window(text, match.start(), match.end()))
    return windows


def validate_draft_quality(draft: dict[str, Any], source_bundle: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    sections = draft.get("sections") or {}
    if source_bundle and not _CITATION_RE.search(str(sections.get("Key Findings") or "")):
        violations.append(
            {
                "section": "Key Findings",
                "severity": "high",
                "issue": "missing_inline_citations",
                "window": str(sections.get("Key Findings") or "")[:240],
            }
        )
    for heading in ("Abstract", "Conclusion"):
        text = str(draft.get("abstract") if heading == "Abstract" else sections.get(heading) or "")
        if _RAW_EXTRACTION_RE.search(text):
            violations.append(
                {
                    "section": heading,
                    "severity": "high",
                    "issue": "raw_extraction_leak",
                    "window": _RAW_EXTRACTION_RE.search(text).group(0),
                }
            )

    findings = str(sections.get("Key Findings") or "")
    conclusion = str(sections.get("Conclusion") or "")
    positive_refs: set[int] = set()
    for ref, windows in _cited_windows(findings).items():
        if any(_POSITIVE_EFFECT_RE.search(window) and _SIGNIFICANT_P_RE.search(window) for window in windows):
            positive_refs.add(ref)
    conclusion_windows = _cited_windows(conclusion)
    for ref in positive_refs:
        if any(_NEGATIVE_EFFECT_RE.search(window) for window in conclusion_windows.get(ref, [])):
            violations.append(
                {
                    "section": "Conclusion",
                    "citation": ref,
                    "severity": "high",
                    "issue": "conclusion_contradicts_positive_finding",
                    "window": " | ".join(conclusion_windows.get(ref, []))[:300],
                }
            )
    return violations
