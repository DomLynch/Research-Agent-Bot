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
  4. scrub_rejected_evidence  — removes SPAR-rejected citation tokens
                                from main-body prose/table rows while
                                preserving the quarantine appendix and
                                References audit trail.

Universal: all rules are domain-agnostic. The scrubber takes the
public MD as input and returns the scrubbed MD; it never adds new
content, only removes/truncates known regressions.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

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
    re.compile(r"\bH3:\s*", re.I),
    re.compile(r"\*{0,2}Selected\s+thesis:\*{0,2}\s*", re.I),
    re.compile(r"\bsource-context\s+sentence\b", re.I),
    re.compile(r"\bunsupported\s+sentence\b", re.I),
    re.compile(r"\bIn\s+the\s+Conclusion,\s+this\s+framing\b", re.I),
    re.compile(r"\bIn\s+the\s+Limitations,\s+this\s+framing\b", re.I),
    re.compile(r"\bThe\s+surviving\s+section\s+therefore\b", re.I),
    re.compile(
        r"\bsource\s+passage\s+cannot\s+support\s+its\s+own\s+specificity\b",
        re.I,
    ),
    re.compile(r"\bCochrane\s+RoB-2\b", re.I),
    re.compile(r"\bROBINS-I\b", re.I),
    re.compile(r"\brisk-of-bias\s+roll-up\b", re.I),
    re.compile(r"\btaken\s+together,\s*", re.I),
)


@dataclass(frozen=True, slots=True)
class ScrubReport:
    """Summary of what the scrubber removed/changed. Universal — fields
    are counters, not topic-specific."""

    abstract_words_before: int
    abstract_words_after: int
    duplicate_rows_removed: int
    residue_phrases_scrubbed: int
    broken_effect_sentences_removed: int = 0
    rejected_evidence_rows_removed: int = 0
    rejected_evidence_sentences_removed: int = 0


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


# ---- Wave 25: References dedupe + QEI title row-count repair -----------


_REFERENCES_HEADING_RE = re.compile(
    r"^(##\s+References\b[^\n]*\n)", re.I | re.M,
)
# Reference entries follow the pattern '- **Author Year.** _Title._ Venue, ...'
# with the citation token in bold at the start. Universal across topics.
_REF_ENTRY_LEAD_RE = re.compile(
    r"^[-*]\s*\*\*([A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}[a-z]?)\.?\*\*",
)


def dedupe_references_section(md: str) -> tuple[str, int]:
    """Collapse duplicate citation entries in the References section.

    Two entries are duplicates iff their bold-leading citation_token
    matches. Same paper retrieved under different identifiers (PMID
    vs DOI vs manual ID) produces multiple receipt rows but should
    appear once in References. Universal — every topic uses the same
    bibliography format. Keeps first occurrence; second+ are dropped.
    """
    m = _REFERENCES_HEADING_RE.search(md)
    if not m:
        return md, 0
    start = m.end()
    nxt = re.search(r"^##\s+\S", md[start:], re.M)
    end = start + nxt.start() if nxt else len(md)
    section = md[start:end]
    # Each reference entry is a contiguous block starting with '- **'.
    # Split by lookahead so blank lines / inline content are kept.
    entries = re.split(r"(?m)(?=^[-*]\s*\*\*[A-Z])", section)
    seen: set[str] = set()
    out_entries: list[str] = []
    n_removed = 0
    for entry in entries:
        m2 = _REF_ENTRY_LEAD_RE.match(entry)
        if not m2:
            out_entries.append(entry)
            continue
        cite = m2.group(1).strip()
        if cite in seen:
            n_removed += 1
            continue
        seen.add(cite)
        out_entries.append(entry)
    new_section = "".join(out_entries)
    return md[:start] + new_section + md[end:], n_removed


_QEI_HEADING_RE = re.compile(
    r"^(##\s+Quantitative\s+Evidence\s+Index[^\n]*\n)", re.I | re.M,
)
# Title pattern: "Top N high-confidence ..." or "_Top N ..._" — count
# claim that must match actual row count.
# Match "Top N" without `\b` because `_` is a word character in Python
# regex — and the QEI title commonly wraps in `_Top N high-confidence_`
# markdown italics. A plain `Top\s+\d+` is precise enough since this
# pattern only runs inside the QEI section.
_TOP_N_RE = re.compile(r"Top\s+(\d+)", re.I)


def fix_qei_title_count(md: str) -> tuple[str, bool]:
    """Repair the QEI title's "Top N" count to match the actual number
    of data rows in the QEI table. Universal — every topic's QEI uses
    the same `Top N` title pattern."""
    m = _QEI_HEADING_RE.search(md)
    if not m:
        return md, False
    start = m.end()
    nxt = re.search(r"^##\s+\S", md[start:], re.M)
    end = start + nxt.start() if nxt else len(md)
    section = md[start:end]
    rows = []
    for line in section.split("\n"):
        if not line.strip().startswith("|") or "---" in line:
            continue
        cells = [c.strip().lower() for c in line.split("|")[1:-1]]
        if cells and cells[0] not in {"study", "citation"}:
            rows.append(line)
    actual_n = len(rows)
    if actual_n == 0:
        return md, False
    # Replace the first "Top N" in the section with the actual count.
    title_m = _TOP_N_RE.search(section)
    if not title_m:
        return md, False
    claimed_n = int(title_m.group(1))
    if claimed_n == actual_n:
        return md, False
    new_section = section[:title_m.start()] + f"Top {actual_n}" + section[title_m.end():]
    return md[:start] + new_section + md[end:], True


_QEI_CLINICAL_ENDPOINT_RE = re.compile(
    r"weight|mass|lean|fat|bmi|body mass|strength|grip|gait|bone|density|"
    r"blood pressure|systolic|diastolic|crp|tnf|inflamm|hba1c|glucose|"
    r"insulin|lipid|cholesterol|mortality|adherence",
    re.I,
)
_QEI_EXCLUDED_TYPES = {"sample size"}


def filter_qei_clinical_rows(md: str, *, max_rows: int = 20) -> tuple[str, int]:
    """Keep journal-facing QEI rows clinically interpretable.

    Universal rendering rule: sample sizes and generic extracted values
    belong in the full supplement tables, while QEI should foreground
    effect-like rows for outcomes a reader can interpret clinically.
    """
    lines = md.splitlines()
    out: list[str] = []
    kept = removed = 0
    in_table = False
    for line in lines:
        if not line.strip().startswith("|"):
            out.append(line)
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not cells or cells[0].lower() == "study" or "---" in line:
            out.append(line)
            in_table = True
            continue
        if in_table:
            endpoint = cells[1] if len(cells) > 1 else ""
            value_type = cells[4].lower() if len(cells) > 4 else ""
            keep = (
                kept < max_rows
                and value_type not in _QEI_EXCLUDED_TYPES
                and bool(_QEI_CLINICAL_ENDPOINT_RE.search(endpoint))
            )
            if keep:
                out.append(line)
                kept += 1
            else:
                removed += 1
    new_md = "\n".join(out) + ("\n" if md.endswith("\n") else "")
    new_md, _ = fix_qei_title_count(new_md)
    return new_md, removed


# ---- Wave 26: SPAR-source deterministic leak scrub ----------------------


_BROKEN_EFFECT_SENTENCE_RE = re.compile(
    r"(^|(?<=[.!?])\s+)([^.\n]*\breported\s+an\s+effect\s+estimate"
    r"(?:\s+of\s+[^.!?\n]+)?\.)\s*",
    re.I | re.M,
)
_PROTECTED_REJECT_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:Rejected\s*/?\s*Contested\s+Evidence|"
    r"Quarantined\s+Evidence|Quarantined\s+Receipts|References\b)[^\n]*\n",
    re.I | re.M,
)


def rejected_citation_tokens_from_artifacts(
    manifest: Mapping[str, Any],
    spar_cache: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return citation_tokens whose receipt_id has a SPAR reject verdict.

    Universal — uses only the manifest receipt schema and spar_cache
    verdict schema. The public scrubber then removes those tokens from
    main-body evidence surfaces while preserving the quarantine appendix
    and References.
    """
    verdicts = spar_cache.get("verdicts")
    if not isinstance(verdicts, Mapping):
        return ()
    rejected_ids = {
        str(rid)
        for rid, verdict_obj in verdicts.items()
        if isinstance(verdict_obj, Mapping)
        and str(verdict_obj.get("verdict") or "").lower().startswith("reject")
    }
    if not rejected_ids:
        return ()
    receipts = manifest.get("receipts")
    if not isinstance(receipts, Iterable):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            continue
        if str(receipt.get("receipt_id") or "") not in rejected_ids:
            continue
        token = str(receipt.get("citation_token") or "").strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return tuple(out)


def scrub_broken_effect_estimates(md: str) -> tuple[str, int]:
    """Remove truncated placeholder sentences such as
    'UKPDS 1998 reported an effect estimate.'.

    Delete-only: no attempt is made to invent a replacement estimate.
    """
    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        n += 1
        return m.group(1)

    return _BROKEN_EFFECT_SENTENCE_RE.sub(repl, md), n


def _protected_spans_for_rejected(md: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in _PROTECTED_REJECT_HEADING_RE.finditer(md):
        nxt = re.search(r"^#{1,4}\s+\S", md[m.end():], re.M)
        end = m.end() + nxt.start() if nxt else len(md)
        spans.append((m.start(), end))
    return spans


def _compile_token_re(tokens: Iterable[str]) -> re.Pattern[str] | None:
    clean = [re.escape(t.strip()) for t in tokens if t and t.strip()]
    if not clean:
        return None
    return re.compile(r"\b(?:" + "|".join(clean) + r")\b")


def _scrub_rejected_segment(
    segment: str,
    token_re: re.Pattern[str],
) -> tuple[str, int, int]:
    rows_removed = 0
    lines: list[str] = []
    for line in segment.splitlines(keepends=True):
        if line.lstrip().startswith("|") and token_re.search(line):
            rows_removed += 1
            continue
        lines.append(line)
    segment = "".join(lines)

    sentences_removed = 0
    chunks = re.split(r"(\n\s*\n)", segment)
    out_chunks: list[str] = []
    for chunk in chunks:
        if not chunk or re.fullmatch(r"\n\s*\n", chunk):
            out_chunks.append(chunk)
            continue
        parts = re.split(r"(?<=[.!?])(\s+)", chunk)
        kept: list[str] = []
        i = 0
        while i < len(parts):
            sentence = parts[i]
            sep = parts[i + 1] if i + 1 < len(parts) else ""
            if token_re.search(sentence):
                sentences_removed += 1
                i += 2
                continue
            kept.append(sentence)
            kept.append(sep)
            i += 2
        out_chunks.append("".join(kept))
    return "".join(out_chunks), rows_removed, sentences_removed


def scrub_rejected_evidence_leaks(
    md: str,
    rejected_citation_tokens: Iterable[str],
) -> tuple[str, int, int]:
    """Delete SPAR-rejected citations from main evidence surfaces.

    Preserves the dedicated Rejected / Contested Evidence quarantine
    section and References. Outside those audit-only zones, removes
    full markdown table rows and full prose sentences containing a
    rejected citation token. It never rewrites claims.
    """
    token_re = _compile_token_re(rejected_citation_tokens)
    if token_re is None:
        return md, 0, 0
    spans = _protected_spans_for_rejected(md)
    if not spans:
        segment, rows, sentences = _scrub_rejected_segment(md, token_re)
        return re.sub(r"\n{3,}", "\n\n", segment), rows, sentences
    out: list[str] = []
    rows_total = 0
    sentences_total = 0
    cursor = 0
    for start, end in spans:
        segment, rows, sentences = _scrub_rejected_segment(
            md[cursor:start], token_re,
        )
        out.append(segment)
        out.append(md[start:end])
        rows_total += rows
        sentences_total += sentences
        cursor = end
    segment, rows, sentences = _scrub_rejected_segment(md[cursor:], token_re)
    out.append(segment)
    rows_total += rows
    sentences_total += sentences
    return re.sub(r"\n{3,}", "\n\n", "".join(out)), rows_total, sentences_total


def scrub_paper(
    md: str, *, abstract_cap: int = 500,
    rejected_citation_tokens: Iterable[str] = (),
) -> tuple[str, ScrubReport]:
    """Apply all scrubber rules in order. Returns (new_md, report).

    Order:
      1. residue (lexical strip)
      2. abstract truncation (preserves remaining prose intent)
      3. table dedupe (operates on table structure)
      4. references dedupe (Wave 25)
      5. rejected evidence leak deletion (Wave 26)
      6. QEI title row-count fix (Wave 25/26)"""
    md, n_residue = scrub_engine_residue(md)
    md, abs_before, abs_after = truncate_abstract(md, cap=abstract_cap)
    md, n_broken_effect = scrub_broken_effect_estimates(md)
    md, n_dup_tables = dedupe_included_studies(md)
    md, n_dup_refs = dedupe_references_section(md)
    md, n_reject_rows, n_reject_sentences = scrub_rejected_evidence_leaks(
        md, rejected_citation_tokens,
    )
    md, _qei_fixed = fix_qei_title_count(md)
    return md, ScrubReport(
        abstract_words_before=abs_before,
        abstract_words_after=abs_after,
        duplicate_rows_removed=n_dup_tables + n_dup_refs,
        residue_phrases_scrubbed=n_residue,
        broken_effect_sentences_removed=n_broken_effect,
        rejected_evidence_rows_removed=n_reject_rows,
        rejected_evidence_sentences_removed=n_reject_sentences,
    )
