"""Shared prose count for writer targets and manuscript gates."""
from __future__ import annotations

import re

_NAME = r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+"
_YEAR = r"(?:19|20)\d{2}[a-z]?"
_AUTHOR_YEAR = rf"{_NAME}(?:\s+(?:et al\.?|&\s+{_NAME}|and\s+{_NAME}))?\s*,?\s*{_YEAR}"
_TITLE_YEAR = rf"{_NAME}(?:\s+(?:(?:to|of|and|for|the)\s+)?{_NAME}){{1,5}}\s+{_YEAR}"
_ABSTRACT_CITATION_RE = re.compile(
    rf"\[(?:bundle:\d+|exact source:\s*https?://[^\]\n]+|{_AUTHOR_YEAR}(?:;\s*{_AUTHOR_YEAR})*|{_TITLE_YEAR})\]"
)
_RENDERED_CITED_RE = re.compile(r"(?m)^[ \t]*_Cited:\s*`[^`\n]+`(?:\s*,\s*`[^`\n]+`)*_[ \t]*\n?")


def manuscript_word_count(body: str) -> int:
    """Count prose and link labels; URL destinations do not contribute words."""
    return len(re.findall(r"\b\w+\b", re.sub(r"https?://[^\s\]<>)]*", "", body)))


def section_prose_word_count(body: str, heading: str) -> int:
    """Exclude citation metadata, while retaining scientific bracketed findings."""
    body = _RENDERED_CITED_RE.sub("", body)
    if heading.removeprefix("## ") == "Abstract":
        body = _ABSTRACT_CITATION_RE.sub("", body)
    return manuscript_word_count(body)
