from __future__ import annotations

import re
from typing import Any

from agent.citation_roles import ROLE_LANGUAGE_RULES


_CITATION_RE = re.compile(r"\[(\d+)\]")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_NUMERIC_EFFECT_STAT_RE = re.compile(
    r"(?:95%\s*ci|confidence interval|p\s*[<=>]|hazard ratio|odds ratio|\bor\b|\brr\b|\d+(?:\.\d+)?\s*%)",
    re.IGNORECASE,
)
_COMPARATOR_NUMBER_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\b[^.]{0,40}\b(?:vs\.?|versus)\b|\b(?:vs\.?|versus)\b[^.]{0,40}\b\d+(?:\.\d+)?\b)",
    re.IGNORECASE,
)
_MEAN_MEDIAN_NUMBER_RE = re.compile(
    r"\b(?:mean|median)\b[^.]{0,40}\b\d+(?:\.\d+)?\b",
    re.IGNORECASE,
)
_NUMERIC_SECTIONS = {"Key Findings", "Conclusion"}
_REQUIRED_CITATION_SECTIONS = {"Key Findings"}
_RAW_EXTRACTION_RE = re.compile(r"\b(?:Published results|Meta-analysis)\s+\[\d+\]\s+(?:report|reported)\b", re.IGNORECASE)
_RAW_EXTRACTION_VALUE_RE = re.compile(r"\b(?:mean|median|sd|n=|95%\s*ci|p\s*[<=>]|change from baseline)\b", re.IGNORECASE)
_TOPIC_FROM_TITLE_RE = re.compile(r"^Rapid Evidence Synthesis:\s*(.+)$")
_INTERVENTION_SIGNAL_RE = re.compile(
    r"\b(?:glp-?1(?:ras?)?|sglt2|dpp-?4|semaglutide|liraglutide|tirzepatide|acarbose|"
    r"everolimus|sirolimus|rapamycin|metformin|statin(?:s)?|gliflozin(?:s)?)\b",
    re.IGNORECASE,
)
_CONTRAST_CUE_RE = re.compile(r"\b(?:not|rather than|instead of|contextual only|did not establish|supporting context)\b", re.IGNORECASE)


def _window(text: str, start: int, end: int, *, radius: int = 120) -> str:
    return " ".join(text[max(0, start - radius): min(len(text), end + radius)].split())


def _severity(issue: str) -> str:
    return {
        "forbidden_phrase": "high",
        "missing_inline_citation": "high",
        "citation_out_of_range": "low",
        "abstract_missing_numeric_effect": "high",
        "raw_extraction_template": "high",
        "missing_topic_distinction": "medium",
    }.get(issue, "medium")


def _topic_terms(draft: dict[str, Any]) -> set[str]:
    title = str(draft.get("title") or "")
    match = _TOPIC_FROM_TITLE_RE.match(title)
    topic = match.group(1) if match else title
    return {
        token
        for token in re.findall(r"[a-z0-9\-]+", topic.lower())
        if len(token) > 3 and token not in {"aging", "older", "adults", "adult", "longevity", "rapid", "evidence", "synthesis"}
    }


def _has_structured_effects(source_bundle: list[dict[str, Any]]) -> bool:
    for entry in source_bundle:
        if str(entry.get("role") or "") not in {"published_results", "meta_analysis"}:
            continue
        extraction = entry.get("extraction") or {}
        if extraction.get("effects"):
            return True
        claim = entry.get("claim") or {}
        if any(claim.get(field) for field in ("effect", "metric", "p_value", "n")):
            return True
        if _has_numeric_effect_surface(str(claim.get("source_span") or "")):
            return True
        if _has_numeric_effect_surface(str(entry.get("excerpt") or "")):
            return True
    return False


def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+", text):
        end = match.start()
        sentence = text[start:end].strip()
        if sentence:
            spans.append((start, end, sentence))
        start = match.end()
    tail = text[start:].strip()
    if tail:
        spans.append((start, len(text), tail))
    return spans


def _has_numeric_effect_surface(text: str) -> bool:
    stripped = re.sub(r"\[\d+\]", "", text)
    return bool(
        _NUMBER_RE.search(stripped)
        and (
            _NUMERIC_EFFECT_STAT_RE.search(stripped)
            or _COMPARATOR_NUMBER_RE.search(stripped)
            or _MEAN_MEDIAN_NUMBER_RE.search(stripped)
        )
    )


def validate_draft_quality(draft: dict[str, Any], source_bundle: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    abstract = str(draft.get("abstract") or "")
    sections = draft.get("sections") or {}
    topic_terms = _topic_terms(draft)

    if source_bundle and _has_structured_effects(source_bundle) and abstract.strip() and not _has_numeric_effect_surface(abstract):
        violations.append(
            {
                "section": "Abstract",
                "severity": _severity("abstract_missing_numeric_effect"),
                "issue": "abstract_missing_numeric_effect",
                "window": _window(abstract, 0, min(len(abstract), 160)),
            }
        )

    for heading in ("Abstract", "Key Findings", "Conclusion"):
        body = abstract if heading == "Abstract" else str(sections.get(heading) or "")
        if not body:
            continue
        for start, end, sentence in _sentence_spans(body):
            if _RAW_EXTRACTION_RE.search(sentence) and _RAW_EXTRACTION_VALUE_RE.search(sentence):
                severity = "high" if heading in {"Abstract", "Conclusion"} else "medium"
                violations.append(
                    {
                        "section": heading,
                        "severity": severity,
                        "issue": "raw_extraction_template",
                        "window": _window(body, start, end),
                    }
                )
            refs = [int(match.group(1)) for match in _CITATION_RE.finditer(sentence)]
            if not refs or not topic_terms:
                continue
            cited = [source_bundle[ref - 1] for ref in refs if 1 <= ref <= len(source_bundle)]
            if not cited:
                continue
            support_only = all(
                str(entry.get("role") or "") in {"meta_analysis", "review"}
                or str(entry.get("evidence_tier") or "").startswith("Tier B")
                or str(entry.get("evidence_tier") or "").startswith("Tier C")
                for entry in cited
            )
            if not support_only:
                continue
            if not _INTERVENTION_SIGNAL_RE.search(sentence):
                continue
            if any(term in sentence.lower() for term in topic_terms):
                continue
            if _CONTRAST_CUE_RE.search(sentence):
                continue
            violations.append(
                {
                    "section": heading,
                    "severity": _severity("missing_topic_distinction"),
                    "issue": "missing_topic_distinction",
                    "window": _window(body, start, end),
                }
            )
    return violations


def validate_citations(draft: dict[str, Any], source_bundle: list[dict[str, Any]], *, strict: bool = False) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    sections = draft.get("sections") or {}
    for heading, text in sections.items():
        body = str(text or "")
        if (
            heading in _REQUIRED_CITATION_SECTIONS
            and source_bundle
            and body.strip()
            and not _CITATION_RE.search(body)
        ):
            violations.append(
                {
                    "section": heading,
                    "severity": _severity("missing_inline_citation"),
                    "issue": "missing_inline_citation",
                    "window": _window(body, 0, min(len(body), 120)),
                }
            )
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
