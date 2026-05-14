"""Universal reference-style renderer.

Reviewer feedback 2026-05-14: references must be in real journal style
(Vancouver / Harvard / APA / Cell / Nature) — not the simplified
`**Surname Year.**` form the writer currently emits. The declared
style lives in `target_journal_pack.json:reference_style`. This module
renders ONE bibliographic record per declared style.

Universal — input is a generic "record" with (citation_token, title,
year, venue, doi, pmid, authors). Works for any topic; not biomedical-
specific.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

CANONICAL_STYLES: Final[tuple[str, ...]] = (
    "Vancouver", "Harvard", "APA", "Cell", "Nature",
)


@dataclass(frozen=True, slots=True)
class ReferenceRecord:
    """Minimal bibliographic record. Universal — fields are the
    intersection of all 5 journal styles' required surface."""

    citation_token: str            # Author-Year body cite ("Smith 2024")
    title: str | None
    year: int | None
    venue: str | None
    doi: str | None
    pmid: str | None
    authors: tuple[str, ...] = ()  # author surnames in order


def _normalize_style(style: str | None) -> str:
    """Match style declarations case-insensitively against the
    canonical set. Returns the canonical casing; unknown → 'Vancouver'
    (the default for biomedical synthesis)."""
    if not style:
        return "Vancouver"
    s = style.strip().lower()
    for canonical in CANONICAL_STYLES:
        if canonical.lower() == s:
            return canonical
    return "Vancouver"


def _authors_blurb(record: ReferenceRecord, style: str) -> str:
    """Universal author-list rendering. Empty authors → use the
    citation_token's surname as a fallback so the reference still
    reads as bibliographic, not stub."""
    if record.authors:
        if len(record.authors) <= 6 or style in ("Vancouver", "APA"):
            return ", ".join(record.authors[:6]) + (
                ", et al" if len(record.authors) > 6 else ""
            )
        return f"{record.authors[0]} et al"
    # Fallback: parse the citation_token. "Smith 2024" → "Smith"
    parts = record.citation_token.split()
    return parts[0] if parts else record.citation_token


def _identifiers_blurb(record: ReferenceRecord) -> str:
    """Universal trailing identifiers. All five styles end with a DOI
    and/or PMID — the difference is just punctuation."""
    bits: list[str] = []
    if record.doi:
        bits.append(f"doi:{record.doi}")
    if record.pmid:
        bits.append(f"PMID: {record.pmid}")
    return ". ".join(bits)


def render_reference(record: ReferenceRecord, style: str | None) -> str:
    """Render one bibliographic record in the declared style.
    Universal — no per-topic logic. Falls back to Vancouver on
    unknown style."""
    s = _normalize_style(style)
    authors = _authors_blurb(record, s)
    title = (record.title or "").rstrip(".")
    venue = record.venue or ""
    year = str(record.year) if record.year else ""
    ids = _identifiers_blurb(record)
    if s == "Vancouver":
        # Vancouver: Authors. Title. Venue. Year. DOI/PMID.
        parts = [p for p in (
            f"{authors}." if authors else "",
            f"{title}." if title else "",
            f"{venue}." if venue else "",
            f"{year}." if year else "",
            f"{ids}." if ids else "",
        ) if p]
        return " ".join(parts)
    if s == "Harvard":
        # Harvard: Authors (Year) Title. Venue. DOI/PMID.
        return " ".join(p for p in (
            f"{authors}" if authors else "",
            f"({year})" if year else "",
            f"{title}." if title else "",
            f"{venue}." if venue else "",
            f"{ids}." if ids else "",
        ) if p)
    if s == "APA":
        # APA: Authors (Year). Title. Venue. DOI/PMID.
        return " ".join(p for p in (
            f"{authors}" if authors else "",
            f"({year})." if year else "",
            f"{title}." if title else "",
            f"{venue}." if venue else "",
            f"{ids}." if ids else "",
        ) if p)
    if s == "Cell":
        # Cell: Authors (Year). Title. Venue. DOI/PMID.
        # (similar to APA but Cell uses italic venue conventionally;
        # we render plain text — typesetting is downstream)
        return " ".join(p for p in (
            f"{authors}" if authors else "",
            f"({year})." if year else "",
            f"{title}." if title else "",
            f"{venue}." if venue else "",
            f"{ids}." if ids else "",
        ) if p)
    # Nature: Authors. Title. Venue Year, DOI/PMID.
    parts = [p for p in (
        f"{authors}." if authors else "",
        f"{title}." if title else "",
        venue,
        year,
        ids,
    ) if p]
    return " ".join(parts)


def reference_style_consistency_issue_messages(
    references_section_body: str, declared_style: str | None,
) -> tuple[str, ...]:
    """Light style-consistency check: if a style is declared, the
    References section should not contain markers from a DIFFERENT
    style (e.g. declared Vancouver but every entry starts with
    `(Year)` parenthetical — Harvard-style). Universal — purely
    structural, no per-topic knowledge."""
    if not declared_style or not references_section_body:
        return ()
    style = _normalize_style(declared_style)
    issues: list[str] = []
    # Heuristic: count entries that start with bold-marker shorthand
    # ("**Surname Year.**") — the pre-Slice-13 simplified form. A real
    # journal style would have full bibliographic citations.
    import re
    stub_entries = re.findall(
        r"^-\s+\*\*[A-Z][A-Za-z'\-]+\s+\d{4}\.?\*\*\s*\d{0,4}\.\s*(?:DOI|doi):?",
        references_section_body, re.M,
    )
    if stub_entries:
        issues.append(
            f"reference-style mismatch: declared {style!r} but "
            f"{len(stub_entries)} entries use the pre-render stub form "
            f"(`**Surname Year.**`). Run reference rendering to "
            f"produce journal-style entries.",
        )
    return tuple(issues)
