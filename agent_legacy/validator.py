from __future__ import annotations

import re
from typing import Any

from agent.citation_roles import ROLE_LANGUAGE_RULES


_CITATION_RE = re.compile(r"\[(\d+)\]")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_NUMERIC_SECTIONS = {"Key Findings", "Conclusion"}


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
