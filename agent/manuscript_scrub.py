"""Manuscript scrubber — universal post-render correctness layer.

Stdlib-only, no LLM. Runs AFTER the LLM writer + appendix splice and
BEFORE the public_manuscript_contract gate. Applies bounded reversible
fixes for the failure classes the writer cannot self-correct:

  1. truncate_abstract        — caps the Abstract at N words at the
                                first sentence boundary, so introduction
                                prose can't bleed into the abstract.
  2. dedupe_included_studies  — collapses byte-identical or same-
                                citation rows in the Included Studies
                                table; keeps the row with the highest
                                evidence tier.
  3. scrub_engine_residue     — removes residual engine-internal
                                phrases from the public MD body
                                (defence-in-depth: source fixes already
                                landed in framework_section.py +
                                paper_writer_deterministic.py, but a
                                paper rendered against a stale cache
                                or alternative writer must not leak).

Universal: all rules are domain-agnostic. The scrubber takes the
public MD as input and returns the scrubbed MD; it never adds new
content, only removes/truncates known regressions.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass

# Same forbidden-phrase list the contract uses, expressed as regex
# patterns so we can also strip a leading marker (e.g. "Tournament
# selector: " or "(Tournament selector)") universally. Keep entries
# non-overlapping (no entry should be a strict prefix of another).
_RESIDUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Bracketed/parenthesised "Tournament selector" markers.
    re.compile(r"\s*[\(\[\s]\s*Tournament\s+selector\s*[\)\]\s]?\s*", re.I),
    # Bare residue strings that escape into prose.
    re.compile(
        r"no\s+matched\s+source\s+in\s+the\s+accepted\s+evidence"
        r"(?:\s+registry)?",
        re.I,
    ),
    re.compile(r"deterministic\s+evidence\s+summary", re.I),
    re.compile(r"LLM\s+proposes,\s+code\s+disposes", re.I),
    re.compile(r"no\s+LLM\s+authorship", re.I),
)


@dataclass(frozen=True, slots=True)
class ScrubReport:
    """Summary of what the scrubber removed/changed. Universal — fields
    are counters, not topic-specific."""

    abstract_words_before: int
    abstract_words_after: int
    duplicate_rows_removed: int
    residue_phrases_scrubbed: int


def scrub_engine_residue(md: str) -> tuple[str, int]:
    """Strip known engine-internal residue phrases from the public MD.

    Universal — domain-agnostic. These phrases are pipeline jargon
    that should never reach a journal reader.
    """
    n = 0
    for pat in _RESIDUE_PATTERNS:
        md, k = pat.subn("", md)
        n += k
    # Collapse any stray double spaces left after scrubbing.
    md = re.sub(r"  +", " ", md)
    return md, n


_ABSTRACT_HEADING_RE = re.compile(
    r"^(#{1,4}\s*Abstract\b[^\n]*\n)", re.I | re.M,
)


def truncate_abstract(md: str, *, cap: int = 500) -> tuple[str, int, int]:
    """Cap the Abstract section at `cap` words at the first sentence
    boundary at-or-after the cap. Returns (new_md, words_before,
    words_after). Universal — works for any topic.

    Algorithm:
      - Locate '## Abstract' heading and the next '##/#'-level heading
        (Introduction, Background, etc.).
      - Take the body between them. Split on sentence-end punctuation.
      - Accumulate sentences until adding the next one would exceed
        the cap. The remainder of the original section is dropped.
      - If the abstract is already <= cap, no-op.
    """
    m = _ABSTRACT_HEADING_RE.search(md)
    if not m:
        return md, 0, 0
    abs_start = m.end()
    nxt = re.search(r"^#{1,4}\s+\S", md[abs_start:], re.M)
    abs_end = abs_start + nxt.start() if nxt else len(md)
    abs_body = md[abs_start:abs_end]
    n_words_before = len(abs_body.split())
    if n_words_before <= cap:
        return md, n_words_before, n_words_before
    sents = re.split(r"(?<=[.!?])\s+", abs_body)
    kept: list[str] = []
    word_count = 0
    for s in sents:
        s_words = len(s.split())
        if not s.strip():
            continue
        if word_count + s_words > cap and kept:
            break
        kept.append(s)
        word_count += s_words
    new_body = " ".join(kept).rstrip() + "\n\n"
    new_md = md[:abs_start] + new_body + md[abs_end:]
    return new_md, n_words_before, len(new_body.split())


# Wave 24: dedupe runs across ALL public evidence tables, not just
# Included Studies. Walton 2019 was duplicating in Table 4 (Risk of
# Bias) too. Universal: every topic's tables follow the same
# `## Table N: ...` schema with a citation_token in the first cell.
_EVIDENCE_TABLE_HEADING_RE = re.compile(
    r"^(#{1,4}\s*(?:Included\s+Studies|Studies\s+Included|"
    r"Table\s+\d+(?:\s*\([^)]+\))?\s*:?[^\n]*|"
    r"Risk\s+of\s+Bias[^\n]*|"
    r"Per[- ]Study\s+Endpoint[^\n]*|"
    r"Numeric\s+Index[^\n]*|"
    r"Quantitative\s+Evidence\s+Index[^\n]*)\n)",
    re.I | re.M,
)
_INCLUDED_HEADING_RE = _EVIDENCE_TABLE_HEADING_RE  # back-compat alias
# First-cell citation-token pattern: "Surname 2019" / "Surname et al. 2020"
# / "Surname & Other 2018".
_CITE_FIRST_CELL_RE = re.compile(
    r"^\s*\|\s*([A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}[a-z]?)"
    r"\s*\|",
)
# Tier convention: "A1" .. "C3"; the higher A1 sorts before B2.
_TIER_ORDER = {f"{lvl}{n}": i for i, (lvl, n) in enumerate(
    sum(([(lvl, n) for n in (1, 2, 3)] for lvl in "ABCD"), [])
)}


def _row_tier(row: str) -> int:
    """Return tier rank (0=A1 best, 11=D3 worst) for a table row, or 999
    if no tier cell. Used to break ties when collapsing duplicate rows."""
    cells = [c.strip() for c in row.split("|")[1:-1]]
    for cell in cells[1:5]:  # tier conventionally lives in cols 2-4
        if cell in _TIER_ORDER:
            return _TIER_ORDER[cell]
    return 999


def _dedupe_one_table(md: str, start: int, end: int) -> tuple[str, int]:
    """Dedupe rows of a single table block by citation_token (first
    cell). Helper shared across all evidence tables."""
    section = md[start:end]
    lines = section.split("\n")
    out_lines: list[str] = []
    rows_by_cite: "OrderedDict[str, str]" = OrderedDict()
    n_removed = 0
    in_data_block = False
    for line in lines:
        if not line.startswith("|"):
            if rows_by_cite:
                out_lines.extend(rows_by_cite.values())
                rows_by_cite.clear()
                in_data_block = False
            out_lines.append(line)
            continue
        if "---" in line or re.match(
            r"\s*\|\s*Citation\s*\|", line, re.I,
        ):
            in_data_block = True
            out_lines.append(line)
            continue
        if not in_data_block:
            out_lines.append(line)
            continue
        cite_match = _CITE_FIRST_CELL_RE.match(line)
        if not cite_match:
            out_lines.append(line)
            continue
        cite = cite_match.group(1).strip()
        if cite not in rows_by_cite:
            rows_by_cite[cite] = line
        else:
            existing = rows_by_cite[cite]
            if _row_tier(line) < _row_tier(existing):
                rows_by_cite[cite] = line
            n_removed += 1
    if rows_by_cite:
        out_lines.extend(rows_by_cite.values())
    new_section = "\n".join(out_lines)
    return md[:start] + new_section + md[end:], n_removed


def dedupe_included_studies(md: str) -> tuple[str, int]:
    """Collapse duplicate rows across ALL public evidence tables (Wave
    24): Included Studies, Per-Study Endpoint, Cross-Domain Tensions,
    Risk of Bias, Numeric Index, etc.

    Two rows are considered duplicates iff their first cell (the
    citation_token) matches. Among duplicates, keep the row with the
    best evidence tier (A1 > A2 > ... > D3); ties go to the first
    encountered. Universal — every topic uses the same `## Table N`
    schema with citation_token first cell.
    """
    n_removed_total = 0
    # Iterate non-overlapping table sections; each pass shifts offsets,
    # so we walk fresh on the updated MD until no more matches.
    while True:
        # Find the first table whose body still contains duplicate cites.
        m = _EVIDENCE_TABLE_HEADING_RE.search(md)
        if not m:
            break
        start = m.end()
        nxt = re.search(r"^#{1,4}\s+\S", md[start:], re.M)
        end = start + nxt.start() if nxt else len(md)
        new_md, n_removed = _dedupe_one_table(md, start, end)
        n_removed_total += n_removed
        # Mark this heading as processed by replacing the leading hashes
        # with a sentinel so the next search skips it. After all passes
        # complete, restore.
        sentinel = "@@PMC_DEDUPED@@"
        head = md[m.start():m.end()]
        # Only mutate the heading text in the working copy; restoration
        # happens after the loop.
        md = new_md.replace(head, head.replace("##", sentinel, 1), 1)
    md = md.replace("@@PMC_DEDUPED@@", "##")
    return md, n_removed_total


def scrub_paper(
    md: str, *, abstract_cap: int = 500,
) -> tuple[str, ScrubReport]:
    """Apply all scrubber rules in order. Returns (new_md, report).

    Order: residue first (lexical strip), abstract truncation second
    (preserves remaining prose intent), dedupe last (operates on table
    structure that the previous passes leave intact)."""
    md, n_residue = scrub_engine_residue(md)
    md, abs_before, abs_after = truncate_abstract(md, cap=abstract_cap)
    md, n_dup = dedupe_included_studies(md)
    return md, ScrubReport(
        abstract_words_before=abs_before,
        abstract_words_after=abs_after,
        duplicate_rows_removed=n_dup,
        residue_phrases_scrubbed=n_residue,
    )
