"""Fix #22: Surface-render lint gate.

The Stage-2 consistency audit kept passing while a human reader could
see obvious "generated artifact" patterns:

  - orphan citation blocks (`_Cited: …_` between blank lines, no
    preceding sentence — the writer dropped the sentence but kept
    the citation block)
  - consecutive citation blocks separated by only blank lines (one
    sentence somehow attached to multiple cite blocks)
  - the Abstract has paragraphs that are nothing but a citation block
  - "Konopka et al. 2019." used as a sentence-ending standalone
    where "Konopka et al." mid-sentence would be more natural

This module provides pure-deterministic detection. Auto-fix lives in
scripts/apply_consistency_fixes.py via the public list returned by
detect_orphan_citations() — that fix simply strips orphan blocks
(safe: the receipt was already covered by the surrounding sentence
that the writer rendered, or the cite block has no anchor).

No LLM, no I/O, no project deps beyond stdlib. Operates on the
rendered full_paper.md."""
from __future__ import annotations

import re
from dataclasses import dataclass


# A `_Cited:` block looks like this in the rendered paper:
#     "  _Cited: `Walton 2019`, `Konopka 2019`_"
# We anchor on the line-start (with optional leading 2-space indent)
# and a closing underscore, capturing the entire match span so we can
# strip it.
_CITED_BLOCK_RE = re.compile(
    r"^[ \t]*_Cited:[^_\n]*_\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class SurfaceLintFinding:
    """One surface-lint finding. `kind` is the category (orphan_cite,
    consecutive_cites, abstract_cite_only, sentence_end_authoryear);
    `line_no` is 1-indexed; `evidence` is the offending substring
    capped at ~200 chars."""
    kind: str
    line_no: int
    evidence: str
    suggested_fix: str


def _line_indices(paper_md: str) -> list[int]:
    """Indices into paper_md where each line starts. Used to map a
    char offset back to a 1-indexed line number."""
    starts = [0]
    for i, ch in enumerate(paper_md):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _line_no_for_offset(line_starts: list[int], offset: int) -> int:
    """Binary search for the 1-indexed line number of a char offset."""
    import bisect
    idx = bisect.bisect_right(line_starts, offset) - 1
    return idx + 1


def _previous_non_blank_line(paper_md: str, before_offset: int) -> str:
    """Walk backwards from `before_offset` to find the previous
    non-blank line. Returns the line content (stripped). Empty string
    when at start-of-file."""
    # Walk lines backwards from the offset
    chunk = paper_md[:before_offset].rstrip("\n")
    for line in reversed(chunk.split("\n")):
        if line.strip():
            return line.strip()
    return ""


def _is_section_heading(line: str) -> bool:
    """A markdown heading like `## Abstract`, `### Foo`, `# Title`."""
    return bool(re.match(r"^\s*#{1,6}\s+\S", line))


def _is_cited_block_line(line: str) -> bool:
    """Whether `line` IS a `_Cited: …_` block."""
    return bool(re.match(r"^[ \t]*_Cited:[^_\n]*_\s*$", line))


def detect_orphan_citations(paper_md: str) -> list[SurfaceLintFinding]:
    """Find `_Cited: …_` blocks whose immediately-preceding non-blank
    line is NOT a real sentence (it's a heading, or another cite
    block, or the file start). These are the "generated artifact"
    blocks a reader notices — the sentence the writer attached them
    to was lost during validation/auto-fix and only the dangling
    cite remains."""
    line_starts = _line_indices(paper_md)
    findings: list[SurfaceLintFinding] = []
    for m in _CITED_BLOCK_RE.finditer(paper_md):
        line_no = _line_no_for_offset(line_starts, m.start())
        prev = _previous_non_blank_line(paper_md, m.start())
        if not prev:
            findings.append(SurfaceLintFinding(
                kind="orphan_cite",
                line_no=line_no,
                evidence=m.group(0)[:200],
                suggested_fix=(
                    "Citation block at start of file with no anchor "
                    "sentence — strip it."
                ),
            ))
            continue
        if _is_section_heading(prev):
            findings.append(SurfaceLintFinding(
                kind="orphan_cite",
                line_no=line_no,
                evidence=m.group(0)[:200],
                suggested_fix=(
                    "Citation block follows a section heading directly "
                    "(no preceding sentence) — strip it."
                ),
            ))
            continue
        if _is_cited_block_line(prev):
            findings.append(SurfaceLintFinding(
                kind="consecutive_cites",
                line_no=line_no,
                evidence=m.group(0)[:200],
                suggested_fix=(
                    "Two citation blocks separated only by blank lines "
                    "— merge into the preceding cite block, or strip if "
                    "duplicate."
                ),
            ))
    return findings


def detect_abstract_cite_only_paragraphs(
    paper_md: str,
) -> list[SurfaceLintFinding]:
    """Inside the Abstract section, find paragraphs that consist
    entirely of one or more cite blocks with no surrounding prose.
    (A normal paragraph has at least one non-cite line.)"""
    line_starts = _line_indices(paper_md)
    findings: list[SurfaceLintFinding] = []
    abstract_match = re.search(
        r"^##\s+Abstract\b", paper_md, re.MULTILINE,
    )
    if not abstract_match:
        return findings
    abs_start = abstract_match.end()
    next_section = re.search(
        r"^##\s+\w", paper_md[abs_start:], re.MULTILINE,
    )
    abs_end = abs_start + (next_section.start() if next_section else len(paper_md))
    abstract_md = paper_md[abs_start:abs_end]
    # Split into paragraphs (blank-line-separated).
    offset = abs_start
    for para in abstract_md.split("\n\n"):
        if not para.strip():
            offset += len(para) + 2
            continue
        para_lines = [ln for ln in para.split("\n") if ln.strip()]
        if para_lines and all(_is_cited_block_line(ln) for ln in para_lines):
            line_no = _line_no_for_offset(line_starts, offset)
            findings.append(SurfaceLintFinding(
                kind="abstract_cite_only",
                line_no=line_no,
                evidence=para.strip()[:200],
                suggested_fix=(
                    "Abstract paragraph is a citation block with no "
                    "surrounding prose — attach to the previous "
                    "sentence or strip."
                ),
            ))
        offset += len(para) + 2
    return findings


# A sentence-ending standalone "Konopka et al. 2019." (the period is
# the SENTENCE terminator, not the abbreviation period) is awkward.
# Captures the full token group so we can suggest the rewrite.
_SENTENCE_END_AUTHORYEAR_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+)\s+et\s+al\.\s+(\d{4})\.\s+(?=[A-Z]|$|\n)",
)


def detect_sentence_end_authoryear(paper_md: str) -> list[SurfaceLintFinding]:
    """Surface-lint per user spec: flag `Author et al. 2019.` patterns
    where the trailing period is a sentence terminator, NOT the
    abbreviation period. Reads better as `(Author et al., 2019)` mid-
    sentence or `Author et al.` mid-clause with a parenthesized year."""
    line_starts = _line_indices(paper_md)
    findings: list[SurfaceLintFinding] = []
    for m in _SENTENCE_END_AUTHORYEAR_RE.finditer(paper_md):
        author, year = m.group(1), m.group(2)
        line_no = _line_no_for_offset(line_starts, m.start())
        findings.append(SurfaceLintFinding(
            kind="sentence_end_authoryear",
            line_no=line_no,
            evidence=paper_md[max(0, m.start() - 30):m.end() + 30].strip(),
            suggested_fix=(
                f"`{author} et al. {year}.` ends a sentence with an "
                f"author-year token — prefer `({author} et al., {year})` "
                f"inline or `{author} et al.` mid-clause with the year "
                f"in parentheses."
            ),
        ))
    return findings


def detect_sentence_fragments(
    paper_md: str,
) -> list[SurfaceLintFinding]:
    """Fix #52: catch broken sentence-fragments left behind by
    upstream auto-strips or partial-text patches. Two patterns:

    Pattern A — single-letter sentence-start (truncated word leftover):
      "...lifespan extension) e when paired with exercise."
      The "e" is the last letter of "negative" with the preceding
      ~50 chars stripped by an over-aggressive regex.

    Pattern B — lowercase sentence-start (subject missing):
      "The findings showed no change. on 2019 in a healthier cohort."
      The "on 2019..." fragment lost its leading "Konopka" or
      "Walton" via a citation-strip pass.

    Severity P2 (cosmetic but obvious to a reader); auto-fixable
    via strip_sentence_fragments() — the fragment sentence is
    deleted; the surrounding prose holds the argument."""
    findings: list[SurfaceLintFinding] = []
    line_starts = _line_indices(paper_md)
    # Pattern A: " {single_letter} {word_starting_with_lowercase}"
    # Anchored to a sentence-like boundary — `.` OR `)` — so we
    # catch both "...end. e when..." (period) and "...extension) e
    # when..." (closing-paren) — the latter is common when an
    # over-aggressive strip eats most of a parenthetical-prefixed
    # sentence and leaves only the trailing word fragment.
    pat_a = re.compile(
        # `\.` (sentence-end period) OR `[a-z]{2}\)` (closing paren
        # of a real word, ≥2 letters before — excludes `(a)` `(b)`
        # enumeration markers which are only ONE letter inside parens)
        r"(?:\.|[a-z]{2}\))\s+([a-z])\s+([a-z]\w+)",
    )
    # Pattern B: ". <lowercase preposition/article> <Year-or-Word>"
    # Sentence ending with `. ` followed by a lowercase word that's
    # a typical truncation orphan ("on 2019", "in 2025", "of trial").
    # Whitelist common legitimate continuation patterns (e.g. "i.e.",
    # "vs.", "et al."). Restrict to known orphan-prone prepositions.
    pat_b = re.compile(
        r"\.\s+(on|in|at|by|of|for|with|to)\s+(\d{4}|[A-Z])",
    )
    for m in pat_a.finditer(paper_md):
        line_no = _line_no_for_offset(line_starts, m.start())
        snippet = paper_md[
            max(0, m.start() - 40):m.end() + 40
        ].strip()
        findings.append(SurfaceLintFinding(
            kind="sentence_fragment_single_letter",
            line_no=line_no,
            evidence=snippet[:200],
            suggested_fix=(
                f"Single-letter word {m.group(1)!r} starts a new "
                "sentence — likely truncated word leftover from an "
                "upstream strip. Delete the fragment sentence."
            ),
        ))
    for m in pat_b.finditer(paper_md):
        line_no = _line_no_for_offset(line_starts, m.start())
        snippet = paper_md[
            max(0, m.start() - 40):m.end() + 40
        ].strip()
        findings.append(SurfaceLintFinding(
            kind="sentence_fragment_lowercase_start",
            line_no=line_no,
            evidence=snippet[:200],
            suggested_fix=(
                f"Sentence begins with lowercase preposition "
                f"{m.group(1)!r} + {m.group(2)!r} — likely citation-"
                "prefix stripped by upstream pass. Delete the "
                "fragment sentence (subject missing)."
            ),
        ))
    return findings


def strip_sentence_fragments(paper_md: str) -> tuple[str, int]:
    """Fix #52 auto-fix: delete sentences flagged as fragments.
    Pure deletion — the fragment is by construction broken/
    meaningless; no scientific content lost. Surrounding
    paragraph survives.

    Returns (new_md, n_stripped)."""
    findings = detect_sentence_fragments(paper_md)
    if not findings:
        return paper_md, 0
    # Build the strip targets: each finding tells us where the
    # fragment STARTS. Walk forward to the next sentence terminator
    # to identify the FULL fragment span. Then delete it.
    out = paper_md
    n = 0
    # Re-derive offsets from the regexes (cleaner than re-using
    # the SurfaceLintFinding which only carries line numbers).
    pat_a = re.compile(
        r"(?:\.|[a-z]{2}\))\s+([a-z])\s+([a-z]\w+)",
    )
    pat_b = re.compile(
        r"\.\s+(on|in|at|by|of|for|with|to)\s+(\d{4}|[A-Z])",
    )
    spans: list[tuple[int, int]] = []
    for pat in (pat_a, pat_b):
        for m in pat.finditer(out):
            # Fragment starts at m.start()+1 (right after the period
            # of the GOOD prior sentence) and ends at the next
            # period (inclusive) — that's the broken sentence.
            frag_start = m.start() + 1
            # Find the next sentence terminator
            next_period = out.find(".", m.end())
            if next_period == -1:
                continue
            frag_end = next_period + 1  # include the period
            spans.append((frag_start, frag_end))
    if not spans:
        return paper_md, 0
    # Coalesce overlapping spans + apply in reverse order so
    # offsets stay stable.
    spans.sort()
    coalesced: list[tuple[int, int]] = []
    for s, e in spans:
        if coalesced and s <= coalesced[-1][1]:
            coalesced[-1] = (coalesced[-1][0], max(coalesced[-1][1], e))
        else:
            coalesced.append((s, e))
    for s, e in reversed(coalesced):
        out = out[:s] + out[e:]
        n += 1
    # Collapse double spaces / triple newlines that the deletion
    # may have left behind.
    out = re.sub(r"  +", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out, n


def run_surface_lint(paper_md: str) -> list[SurfaceLintFinding]:
    """Full surface-render lint. Returns ALL findings, ordered by
    line_no for reader-friendly diagnostic output."""
    findings: list[SurfaceLintFinding] = []
    findings.extend(detect_orphan_citations(paper_md))
    findings.extend(detect_abstract_cite_only_paragraphs(paper_md))
    findings.extend(detect_sentence_end_authoryear(paper_md))
    findings.extend(detect_sentence_fragments(paper_md))  # Fix #52
    findings.sort(key=lambda f: f.line_no)
    return findings


def strip_orphan_citation_blocks(paper_md: str) -> tuple[str, int]:
    """Auto-fix: strip cited-blocks that are orphans, consecutive
    duplicates, OR abstract paragraph cite-onlys. Returns
    (new_md, n_stripped). Safe by construction:

      - orphan_cite: NO preceding sentence in the same paragraph,
        so no anchor was lost
      - consecutive_cites: the preceding cite block already credits
        the citations
      - abstract_cite_only: the abstract is a summary — citation info
        is non-load-bearing here (Tables + References + body cite the
        same receipts again with full anchor sentences)

    We pool ALL finding line numbers from orphan + abstract-cite-only
    detectors and strip every cite block that lands on one of those
    lines."""
    orphan = detect_orphan_citations(paper_md)
    abstract_only = detect_abstract_cite_only_paragraphs(paper_md)
    if not orphan and not abstract_only:
        return paper_md, 0
    finding_lines = {f.line_no for f in orphan + abstract_only}
    line_starts = _line_indices(paper_md)
    matches = list(_CITED_BLOCK_RE.finditer(paper_md))
    to_strip = []
    for m in matches:
        ln = _line_no_for_offset(line_starts, m.start())
        if ln in finding_lines:
            to_strip.append(m)
    if not to_strip:
        return paper_md, 0
    out = paper_md
    for m in reversed(to_strip):
        # Strip the match AND the trailing blank line if present (so
        # we don't leave an awkward double-blank gap).
        end = m.end()
        if end < len(out) and out[end:end + 1] == "\n":
            end += 1
        out = out[:m.start()] + out[end:]
    # Collapse 3+ consecutive newlines to 2 (paragraph break).
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out, len(to_strip)


__all__ = [
    "SurfaceLintFinding",
    "detect_abstract_cite_only_paragraphs",
    "detect_orphan_citations",
    "detect_sentence_end_authoryear",
    "run_surface_lint",
    "strip_orphan_citation_blocks",
]
