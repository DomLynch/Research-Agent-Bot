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
_FILE_EXTENSIONS = {"md", "json", "py", "toml", "csv", "tsv", "xml", "txt"}


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


def _fragment_scan_text(text: str) -> str:
    """Mask table rows and abbreviation periods without changing offsets."""
    text = re.sub(r"(?m)^[ \t]*\|[^\n]*", lambda m: " " * len(m[0]), text)
    return re.sub(r"\b(?:vs|e\.g|i\.e|et al|etc|Dr|No)\.",
                  lambda m: m[0].replace(".", "_"), text, flags=re.I)


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
    paper_md = _fragment_scan_text(paper_md)
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
    pat_c = re.compile(r"(?:\b[A-Za-z]{4,}|\))\.([a-z]{2,})(?:[,\s])")
    pat_d = re.compile(
        r"(?m)^(?![ \t]*(?:[|#*_\\-]|\d+\.))"
        r"((?:ing|ed|cy|tion|ment|ness|ity))\b[^\n]*"
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
    for m in pat_c.finditer(paper_md):
        if m.group(1).lower() in _FILE_EXTENSIONS:
            continue
        line_no = _line_no_for_offset(line_starts, m.start())
        snippet = paper_md[
            max(0, m.start() - 40):m.end() + 40
        ].strip()
        findings.append(SurfaceLintFinding(
            kind="sentence_fragment_spliced_word",
            line_no=line_no,
            evidence=snippet[:200],
            suggested_fix=(
                "A lowercase fragment is spliced directly after a "
                "sentence-ending period — delete the fragment sentence."
            ),
        ))
    for m in pat_d.finditer(paper_md):
        if m.group(1).lower() in {"mtor", "ph"}:
            continue
        line_no = _line_no_for_offset(line_starts, m.start())
        findings.append(SurfaceLintFinding(
            kind="sentence_fragment_lowercase_line_start",
            line_no=line_no,
            evidence=m.group(0).strip()[:200],
            suggested_fix=(
                "Paragraph starts with a lowercase fragment — delete "
                "the broken sentence."
            ),
        ))
    return findings


def strip_sentence_fragments(paper_md: str) -> tuple[str, int]:
    """Remove detected prose fragments without crossing lines or table cells."""
    findings = detect_sentence_fragments(paper_md)
    if not findings:
        return paper_md, 0
    # Build the strip targets: each finding tells us where the
    # fragment STARTS. Walk forward to the next sentence terminator
    # to identify the FULL fragment span. Then delete it.
    out = paper_md
    scan = _fragment_scan_text(paper_md)
    n = 0
    # Re-derive offsets from the regexes (cleaner than re-using
    # the SurfaceLintFinding which only carries line numbers).
    pat_a = re.compile(
        r"(?:\.|[a-z]{2}\))\s+([a-z])\s+([a-z]\w+)",
    )
    pat_b = re.compile(
        r"\.\s+(on|in|at|by|of|for|with|to)\s+(\d{4}|[A-Z])",
    )
    pat_c = re.compile(r"(?:\b[A-Za-z]{4,}|\))\.([a-z]{2,})(?:[,\s])")
    pat_d = re.compile(
        r"(?m)^(?![ \t]*(?:[|#*_\\-]|\d+\.))"
        r"((?:ing|ed|cy|tion|ment|ness|ity))\b[^\n]*"
    )
    spans: list[tuple[int, int]] = []
    for pat in (pat_a, pat_b):
        for m in pat.finditer(scan):
            end = re.search(r"[.!?](?!\d)|\n", scan[m.end():])
            if end is None or end[0] == "\n":
                continue
            spans.append((m.start(1), m.end() + end.end()))
    for m in pat_c.finditer(scan):
        if m.group(1).lower() in _FILE_EXTENSIONS:
            continue
        frag_start = m.start(1)
        end = re.search(r"[.!?](?!\d)|\n", scan[m.end():])
        if end is None or end[0] == "\n":
            continue
        spans.append((frag_start, m.end() + end.end()))
    for m in pat_d.finditer(scan):
        if m.group(1).lower() in {"mtor", "ph"}:
            continue
        end = re.search(r"[.!?](?!\d)|\n", scan[m.start():])
        if end is None or end[0] == "\n":
            continue
        spans.append((m.start(), m.start() + end.end()))
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
    out = "\n".join(line if line.lstrip().startswith("|") else re.sub(r"  +", " ", line) for line in out.split("\n"))
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out, n


def detect_blank_table_rows(paper_md: str) -> list[SurfaceLintFinding]:
    findings: list[SurfaceLintFinding] = []
    line_starts = _line_indices(paper_md)
    for m in re.finditer(r"(?m)^[ \t]*\|(?:[ \t]*\|)*[ \t]*$", paper_md):
        findings.append(SurfaceLintFinding(
            kind="blank_table_row",
            line_no=_line_no_for_offset(line_starts, m.start()),
            evidence=m.group(0),
            suggested_fix="Blank markdown table row — strip it.",
        ))
    return findings


def strip_blank_table_rows(paper_md: str) -> tuple[str, int]:
    out, n = re.subn(
        r"(?m)^[ \t]*\|(?:[ \t]*\|)*[ \t]*$\n?",
        "",
        paper_md,
    )
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out, n


def detect_malformed_table_rows(paper_md: str) -> list[SurfaceLintFinding]:
    findings: list[SurfaceLintFinding] = []
    line_starts = _line_indices(paper_md)
    lines = paper_md.splitlines()
    expected: int | None = None
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            expected = None
            continue
        cells = line.count("|") - 1
        stripped = line.strip()
        if expected is None:
            expected = cells
            continue
        if re.fullmatch(r"\|[\s:|\-]+\|", stripped):
            expected = cells
            continue
        if expected is not None and cells != expected:
            offset = sum(len(ln) + 1 for ln in lines[:i])
            findings.append(SurfaceLintFinding(
                kind="malformed_table_row",
                line_no=_line_no_for_offset(line_starts, offset),
                evidence=line.strip()[:200],
                suggested_fix=(
                    "Markdown table row has the wrong cell count — "
                    "strip it from the public table."
                ),
            ))
    return findings


def strip_malformed_table_rows(paper_md: str) -> tuple[str, int]:
    lines = paper_md.splitlines()
    out: list[str] = []
    expected: int | None = None
    n = 0
    for line in lines:
        if not line.lstrip().startswith("|"):
            expected = None
            out.append(line)
            continue
        cells = line.count("|") - 1
        stripped = line.strip()
        if expected is None:
            expected = cells
            out.append(line)
            continue
        if re.fullmatch(r"\|[\s:|\-]+\|", stripped):
            expected = cells
            out.append(line)
            continue
        if expected is not None and cells != expected:
            n += 1
            continue
        out.append(line)
    cleaned = "\n".join(out)
    if paper_md.endswith("\n"):
        cleaned += "\n"
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def strip_empty_qei_rows(paper_md: str) -> tuple[str, int]:
    """Remove public QEI rows whose numeric payload was emptied by a
    later repair/reviewer pass. Pre-render QEI filtering already
    blocks these; this is the post-render defense."""
    lines = paper_md.splitlines()
    out: list[str] = []
    in_qei = False
    n = 0
    for line in lines:
        if re.match(r"^##\s+Quantitative Evidence Index\b", line):
            in_qei = True
            out.append(line)
            continue
        if in_qei and re.match(r"^##\s+", line):
            in_qei = False
            out.append(line)
            continue
        if in_qei and line.startswith("|") and "---" not in line:
            cells = [c.strip().lower() for c in line.strip().strip("|").split("|")]
            if cells[:6] == [
                "study", "endpoint", "arm", "value", "type", "statistic",
            ]:
                out.append(line)
                continue
            if len(cells) >= 6:
                payload = cells[3:6]
                if all(c in {"", "-", "—", "–", "none", "n/a"} for c in payload):
                    n += 1
                    continue
        out.append(line)
    cleaned = "\n".join(out)
    if paper_md.endswith("\n"):
        cleaned += "\n"
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def detect_unterminated_paragraphs(paper_md: str) -> list[SurfaceLintFinding]:
    findings: list[SurfaceLintFinding] = []
    offset = 0
    for para in re.split(r"(\n\s*\n)", paper_md):
        if not para.strip():
            offset += len(para)
            continue
        stripped = para.strip()
        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        first = lines[0] if lines else ""
        is_structural = (
            first.startswith(("#", "|", "-", "*"))
            or re.match(r"^\d+\.", first) is not None
            or any(ln.startswith("|") for ln in lines)
        )
        if (
            not is_structural
            and len(lines) >= 2
            and len(stripped.split()) >= 8
            and not re.search(r"[.!?][\"')\]]?$", stripped)
        ):
            findings.append(SurfaceLintFinding(
                kind="unterminated_paragraph",
                line_no=_line_no_for_offset(_line_indices(paper_md), offset),
                evidence=stripped[:200],
                suggested_fix=(
                    "Paragraph has no sentence terminator — strip the "
                    "fragment paragraph."
                ),
            ))
        offset += len(para)
    return findings


def strip_unterminated_paragraphs(paper_md: str) -> tuple[str, int]:
    parts = re.split(r"(\n\s*\n)", paper_md)
    out: list[str] = []
    n = 0
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        stripped = para.strip()
        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        first = lines[0] if lines else ""
        is_structural = (
            first.startswith(("#", "|", "-", "*"))
            or re.match(r"^\d+\.", first) is not None
            or any(ln.startswith("|") for ln in lines)
        )
        if (
            stripped
            and not is_structural
            and len(lines) >= 2
            and len(stripped.split()) >= 8
            and not re.search(r"[.!?][\"')\]]?$", stripped)
        ):
            n += 1
            continue
        out.append(para)
        if sep:
            out.append(sep)
    cleaned = "".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def run_surface_lint(paper_md: str) -> list[SurfaceLintFinding]:
    """Full surface-render lint. Returns ALL findings, ordered by
    line_no for reader-friendly diagnostic output."""
    findings: list[SurfaceLintFinding] = []
    findings.extend(detect_orphan_citations(paper_md))
    findings.extend(detect_abstract_cite_only_paragraphs(paper_md))
    findings.extend(detect_sentence_end_authoryear(paper_md))
    findings.extend(detect_sentence_fragments(paper_md))  # Fix #52
    findings.extend(detect_blank_table_rows(paper_md))
    findings.extend(detect_malformed_table_rows(paper_md))
    findings.extend(detect_unterminated_paragraphs(paper_md))
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
