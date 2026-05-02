"""Day 10.17 Path B-prime Phase 1 — full-text PDF ingestion.

Lives under scripts/ (not agent/) to preserve the AGENTS.md
"Runtime dep: httpx only" rule. The runtime synthesis pipeline
reads the produced JSON via stdlib; only this offline tool needs
PyMuPDF / pypdf / pdfplumber.

Output: paper_sections.json per PDF — structured fields the
downstream claim extractor (Phase 2) and ablation harness (Phase 5)
can consume without re-parsing PDFs every time.

Parser stack (per reviewer):
  Primary  : PyMuPDF (fitz) — fastest + best layout
  Fallback : pypdf — pure Python, lower quality but no system deps
  Tables   : pdfplumber when PyMuPDF text is insufficient

Success gate (per reviewer): for all 7 metformin reference PDFs,
title/abstract found, methods/results/discussion separated,
DOI/PMID/trial IDs found where present, tables/captions detected
or warned, no PDFs committed.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

__all__ = [
    "PaperSections",
    "Table",
    "Figure",
    "ExtractionQuality",
    "ingest_pdf",
    "main",
]


# --- Schema --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Table:
    """One detected table with caption + raw text + structured rows."""
    label: str             # e.g. "Table 1"
    caption: str           # text immediately after the label
    page: int              # 1-indexed
    raw_text: str          # full text of the table block
    rows: tuple[tuple[str, ...], ...] = ()  # parsed rows when available


@dataclass(frozen=True, slots=True)
class Figure:
    """One detected figure with caption + page number. No image bytes."""
    label: str
    caption: str
    page: int


@dataclass(frozen=True, slots=True)
class ExtractionQuality:
    """Self-reported parser confidence so downstream knows what it got."""
    section_coverage: tuple[str, ...]   # which sections were detected
    table_count: int
    figure_count: int
    reference_count: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Sections:
    """Plain-text content of each canonical paper section."""
    abstract: str = ""
    introduction: str = ""
    methods: str = ""
    results: str = ""
    discussion: str = ""
    limitations: str = ""
    conclusion: str = ""
    references: str = ""


@dataclass(frozen=True, slots=True)
class PaperSections:
    """Top-level artifact written to paper_sections.json per ingested PDF."""
    paper_id: str          # filename stem, used as the artifact key
    source_pdf: str        # absolute path of the input PDF
    title: str
    authors: tuple[str, ...]
    year: int | None
    journal: str
    doi: str
    pmid: str
    trial_ids: tuple[str, ...]   # NCT* / ISRCTN* / similar
    sections: Sections
    tables: tuple[Table, ...] = ()
    figures: tuple[Figure, ...] = ()
    extraction_quality: ExtractionQuality = field(
        default_factory=lambda: ExtractionQuality(
            section_coverage=(), table_count=0,
            figure_count=0, reference_count=0,
        ),
    )


# --- Metadata extractors -------------------------------------------------


_DOI_RE = re.compile(
    r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE,
)
# PMID format: bare integer, usually labelled "PMID:" or "PubMed:"; we
# accept either the label form OR a 7-9-digit run preceded by PMID/PubMed
# within ~40 chars of a journal-style citation block.
_PMID_RE = re.compile(
    r"\bPMID\s*[:#]?\s*(\d{7,9})\b", re.IGNORECASE,
)
_NCT_RE = re.compile(r"\b(NCT\d{8})\b")
_ISRCTN_RE = re.compile(r"\b(ISRCTN\d{6,10})\b")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _extract_doi(text: str) -> str:
    m = _DOI_RE.search(text)
    return m.group(1) if m else ""


def _extract_pmid(text: str) -> str:
    m = _PMID_RE.search(text)
    return m.group(1) if m else ""


def _extract_trial_ids(text: str) -> tuple[str, ...]:
    ids: list[str] = []
    ids.extend(m.group(1) for m in _NCT_RE.finditer(text))
    ids.extend(m.group(1) for m in _ISRCTN_RE.finditer(text))
    return tuple(sorted(set(ids)))


def _extract_year(text: str) -> int | None:
    """Find the publication year. Day 10.17 Phase 1.5: was 500-char
    head only — that missed Konopka/MILES/Mohammed/Witham whose year
    appears past the title block.

    Strategy (order matters — first match wins):
      1. Journal-citation patterns ("Aging Cell. YYYY;", "Lancet ... YYYY",
         "Frontiers ... YYYY") are the actual publication year — these
         must beat the copyright year, which is sometimes a year off
         (Konopka: © 2018 Authors, Aging Cell. 2019;18:e12880 — the
         pattern that wins must be the journal one).
      2. "Publication date:" / "Published YYYY" — explicit publication
         markers next.
      3. Copyright patterns © / (c) — usually the publication year, but
         can lag by a year for revised manuscripts.
      4. "Accepted YYYY" / "Received YYYY" — review-timeline years
         only — last resort, since "received 2018, published 2019"
         is the usual case.
      5. Fallback to the first plausible 4-digit year in 1990-2030
         range in the first 5000 chars.
    """
    high_precision_patterns = (
        r"Aging Cell\.\s*((?:19|20)\d{2})",
        r"Lancet[^\n]{0,40}((?:19|20)\d{2})",
        r"Frontiers[^\n]{0,60}((?:19|20)\d{2})",
        r"Publication date:\s*((?:19|20)\d{2})",
        r"Published(?:\s+online)?[:\s]*[A-Za-z]+\s*\d{0,2},?\s*((?:19|20)\d{2})",
        r"©\s*((?:19|20)\d{2})",
        r"\(c\)\s*((?:19|20)\d{2})",
        r"Accepted[^\n]{0,40}((?:19|20)\d{2})",
        r"Received[^\n]{0,40}((?:19|20)\d{2})",
    )
    # Reviewer flagged risk: a body-text "Frontiers ... 2018" citation
    # could match the journal pattern instead of the publication year.
    # Mitigation: the caller passes only `first_page` to this function
    # (see ingest_pdf), so we operate on a single page. Page-1 prose
    # is rarely a citation; the journal-citation block sits at the
    # bottom of page 1 for Aging Cell / Lancet (Konopka's lives at
    # char ~3800). We scan the whole first page rather than capping
    # at 2000 chars, since 2000 misses Konopka's "Aging Cell. 2019;"
    # block. The bare-year fallback runs only if no high-precision
    # pattern fired.
    head = text[:5000]
    for pat in high_precision_patterns:
        m = re.search(pat, head, re.IGNORECASE)
        if m:
            year = int(m.group(1))
            if 1990 <= year <= 2030:
                return year
    m = re.search(r"\b((?:19|20)\d{2})\b", head)
    if m:
        year = int(m.group(1))
        if 1990 <= year <= 2030:
            return year
    return None


# --- Section splitter ----------------------------------------------------


# Section headings vary in case + suffix + journal-specific layout
# (Aging Cell uses "N | HEADING" with the numeric prefix on a separate
# line that PyMuPDF places before the heading line). Each entry is
# (canonical_name, pattern). Patterns are case-insensitive; we look
# for them at line-start. The Aging Cell variant accepts a leading
# numeric prefix that's been stripped during normalization.
_SECTION_HEADERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Abstract / Summary — Lancet + Aging Cell short-takes use "Summary";
    # most other journals use "Abstract". Both canonicalize to `abstract`
    # in the output schema.
    ("abstract",     re.compile(r"^\s*(?:abstract|summary)\s*$", re.IGNORECASE | re.MULTILINE)),
    ("introduction", re.compile(r"^\s*(?:\d+\s*[.|]?\s*)?introduction\s*$", re.IGNORECASE | re.MULTILINE)),
    ("methods",      re.compile(r"^\s*(?:\d+\s*[.|]?\s*)?(?:materials\s*(?:and|&)\s*methods?|methods?|methodology|experimental(?:\s+procedures?)?|study\s+design)\s*$", re.IGNORECASE | re.MULTILINE)),
    ("results",      re.compile(r"^\s*(?:\d+\s*[.|]?\s*)?results?(?:\s*(?:and|&)\s*discussion)?\s*$", re.IGNORECASE | re.MULTILINE)),
    ("discussion",   re.compile(r"^\s*(?:\d+\s*[.|]?\s*)?discussion\s*$", re.IGNORECASE | re.MULTILINE)),
    ("limitations",  re.compile(r"^\s*(?:\d+\s*[.|]?\s*)?limitations?\s*$", re.IGNORECASE | re.MULTILINE)),
    ("conclusion",   re.compile(r"^\s*(?:\d+\s*[.|]?\s*)?conclusions?\s*$", re.IGNORECASE | re.MULTILINE)),
    ("references",   re.compile(r"^\s*(?:\d+\s*[.|]?\s*)?references?\s*$", re.IGNORECASE | re.MULTILINE)),
)


# Day 10.17 Phase 1 — Aging Cell normalizer. The journal's typesetting
# splits "N | HEADING" across multiple lines after PyMuPDF extraction:
#   "1\n|\nINTRODUCTION"
# Our line-anchored regexes don't match because INTRODUCTION is
# preceded by orphan "|" / digit lines. Normalize before splitting:
# collapse "<digit>\n|\n<HEADING>" → "<digit> | <HEADING>" so the
# regex (which already accepts the numeric prefix) matches cleanly.
_AGING_CELL_HEADING_RE = re.compile(
    r"^(\d+)\n\|\n([A-Z][A-Z\s&]+)$", re.MULTILINE,
)


# ADD NEW JOURNAL NORMALIZERS HERE — each handles ONE specific
# typesetting pattern that breaks our section-heading regex. Keep
# them per-journal so a new contributor knows to add their own
# rather than assume a generic normalizer exists.
def _normalize_aging_cell_layout(text: str) -> str:
    """Aging Cell typesets section headings as a triple-line block:
       <digit>\\n|\\n<HEADING>
    Collapse to "<digit> | <HEADING>" so the line-anchored regex
    (which already accepts a numeric prefix) matches cleanly."""
    return _AGING_CELL_HEADING_RE.sub(r"\1 | \2", text)


# Day 10.17 Phase 1.5 — Elsevier / Frontiers / SDU-Pure typeset
# section headings with single capital letters separated by spaces:
#   "A B S T R A C T", "M E T H O D S", "K E Y W O R D S".
# Collapse them so the line-anchored section regex matches.
_LETTER_SPACED_HEADER_RE = re.compile(
    r"^[ \t]*([A-Z](?:[ \t]+[A-Z]){4,})[ \t]*$", re.MULTILINE,
)


def _collapse_letter_spaced_headers(text: str) -> str:
    """Lines like 'A B S T R A C T' on their own line become 'ABSTRACT'.
    Pre-fix: Keys 2025 had its abstract heading typeset that way (Elsevier
    typesetting); the ^abstract$ regex couldn't match. Collapse before
    splitting so detection works."""
    def _collapse(m: re.Match[str]) -> str:
        return re.sub(r"[ \t]+", "", m.group(1))
    return _LETTER_SPACED_HEADER_RE.sub(_collapse, text)


def _normalize_journal_layout(text: str) -> str:
    """Dispatch to per-journal normalizers in order. Add a new
    `_normalize_<journal>_layout` function above and call it here."""
    text = _normalize_aging_cell_layout(text)
    text = _collapse_letter_spaced_headers(text)
    return text


def _split_sections(full_text: str) -> tuple[Sections, list[str]]:
    """Find canonical-section headings and split the body. Returns
    (Sections, detected_section_names_in_order). Sections not found
    stay empty; callers can read `extraction_quality.section_coverage`
    to see what was detected."""
    full_text = _normalize_journal_layout(full_text)
    matches: list[tuple[str, int, int]] = []  # (name, start, header_end)
    for name, pattern in _SECTION_HEADERS:
        for m in pattern.finditer(full_text):
            matches.append((name, m.start(), m.end()))
    matches.sort(key=lambda t: t[1])
    sections: dict[str, str] = {
        n: "" for n, _ in _SECTION_HEADERS
    }
    detected: list[str] = []
    for i, (name, _start, header_end) in enumerate(matches):
        next_start = matches[i + 1][1] if i + 1 < len(matches) else len(full_text)
        body = full_text[header_end:next_start].strip()
        if body and not sections[name]:  # first match wins
            sections[name] = body
            detected.append(name)
    return Sections(**sections), detected


# Day 10.17 Phase 1.5 — unlabeled abstract heuristic. Some Frontiers /
# review-style papers (Mohammed 2021) put the abstract immediately
# after the affiliations block with NO heading. The labeled-section
# splitter never finds it. Recover by scanning the prose between the
# title and the first detected section header.
_METADATA_LINE_PREFIXES = (
    "doi:", "published in:", "publication date:", "document version",
    "document license", "citation for", "go to publication",
    "terms of use", "this work is brought", "if you believe",
    "please direct", "received:", "accepted:", "revised:",
    "https://", "http://", "wileyonlinelibrary",
    "correspondence", "email:", "funding", "keywords",
    "k e y w o r d s",  # letter-spaced variant
    "edited by", "reviewed by",
)


def _looks_like_prose(text: str) -> bool:
    """Reject metadata blocks; require enough sentence-ending periods
    to look like multi-sentence prose."""
    stripped = text.strip()
    if len(stripped) < 200:
        return False
    if stripped.lstrip().lower().startswith(_METADATA_LINE_PREFIXES):
        return False
    # Must have at least 2 sentence-ending periods to look like prose
    if stripped.count(". ") < 2:
        return False
    return True


# Affiliation-line shape — these immediately follow authors and are
# characterized by leading numeric superscripts ("1 Department of...")
# or organization keywords near the start of the line. Reviewer fix:
# require the keyword to appear in the FIRST HALF of the line so
# legitimate abstract sentences with mid-clause "Centers for Disease
# Control..." or "Hospital admission rates declined..." pass through.
# Affiliations always have the org keyword early; prose mentions it
# mid-clause.
_AFFILIATION_KEYWORDS_RE = re.compile(
    r"\b(?:Department|Departments|Institute|School|Hospital|"
    r"Faculty|College|Centre|Center|Laboratory|Division|"
    r"University)\b",
    re.IGNORECASE,
)


def _looks_like_affiliation(line: str) -> bool:
    """True if `line` looks like an affiliation block (org keyword in
    first half of line). Avoids false-positives on abstract sentences
    that mention an org keyword in late-clause position."""
    m = _AFFILIATION_KEYWORDS_RE.search(line)
    if m is None:
        return False
    return m.start() < len(line) // 2


def _extract_unlabeled_abstract(
    full_text: str, title: str, sections: Sections,
    detected: list[str],
) -> str:
    """Return prose between title and first detected section that
    looks like an abstract — used when no labeled abstract heading
    was found. Empty string if no plausible candidate exists.

    Mohammed 2021 (Frontiers in Endocrinology) is the canonical
    target: abstract is unlabeled, sits between the affiliations
    block and a section heading. Pre-fix this paper had abstract=''
    even though prose was clearly present.

    The heuristic walks lines after the title:
      1. Skip blank lines, author-shaped lines, numbered affiliations
         and affiliation continuation lines (Department/University/
         Institute/...)
      2. The first line that passes those filters AND is substantive
         (>= 30 chars) is the abstract start
      3. Take from there to the end of the title-to-section region
      4. Final block must pass the prose sniff (>= 200 chars, multiple
         sentences, no metadata-prefix start)
    """
    if sections.abstract or not title or not detected:
        return ""
    # Use a SHORT title prefix (~30 chars) since the reassembled title
    # may span multiple lines in raw full_text — newlines between
    # title segments make a longer prefix fail to match.
    title_idx = full_text.find(title[:30])
    if title_idx < 0:
        return ""
    first_body = getattr(sections, detected[0], "")
    if not first_body:
        return ""
    anchor_idx = full_text.find(first_body[:80], title_idx)
    if anchor_idx < 0:
        return ""
    region = full_text[title_idx + len(title):anchor_idx]
    lines = region.split("\n")
    abstract_start = None
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or len(s) < 30:
            continue
        if _is_author_line(s):
            continue
        # Numbered affiliation marker at line start ("1 Department...")
        if re.match(r"^\d+\s+[A-Z]", s):
            continue
        if _INSTITUTIONAL_COVER_RE.match(s):
            continue
        if s.lower().startswith(_METADATA_LINE_PREFIXES):
            continue
        # Affiliation continuation lines (mid-line "Department" /
        # "Institute" / "University" tokens — Mohammed's affiliations
        # wrap across 4 lines without leading digits on the wrap).
        # Reviewer fix: only filter when the org keyword is in the
        # first half of the line — abstracts can mention orgs in
        # late-clause position.
        if _looks_like_affiliation(s):
            continue
        abstract_start = i
        break
    if abstract_start is None:
        return ""
    candidate = "\n".join(lines[abstract_start:]).strip()
    if not _looks_like_prose(candidate):
        return ""
    return candidate


# --- Table detection -----------------------------------------------------


_TABLE_LABEL_RE = re.compile(
    r"^\s*Table\s+(\d+|[IVX]+)[.:]?\s*(.*)$", re.IGNORECASE | re.MULTILINE,
)
_FIGURE_LABEL_RE = re.compile(
    r"^\s*(?:Figure|Fig\.?)\s+(\d+|[IVX]+)[.:]?\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def _detect_tables_via_pdfplumber(pdf_path: Path) -> tuple[Table, ...]:
    """Use pdfplumber for structured table extraction. Returns empty
    tuple if pdfplumber finds none — caller can still see captions
    via _detect_table_captions."""
    out: list[Table] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                for raw_table in page.extract_tables() or []:
                    rows = tuple(
                        tuple(cell or "" for cell in row) for row in raw_table
                    )
                    # Try to associate with the nearest preceding
                    # "Table N" caption on the same page.
                    caption_match = list(
                        _TABLE_LABEL_RE.finditer(page_text)
                    )
                    label = ""
                    caption_text = ""
                    if caption_match:
                        cm = caption_match[0]
                        label = f"Table {cm.group(1)}"
                        caption_text = cm.group(2).strip()
                    raw_text = "\n".join(
                        " | ".join(c.strip() for c in row) for row in raw_table
                    )
                    out.append(Table(
                        label=label or f"Table (page {page_idx})",
                        caption=caption_text, page=page_idx,
                        raw_text=raw_text, rows=rows,
                    ))
    except Exception:
        return ()
    return tuple(out)


def _detect_figures_via_captions(full_text: str) -> tuple[Figure, ...]:
    """Figures are detected only by their caption text — we don't
    extract image bytes."""
    out: list[Figure] = []
    for m in _FIGURE_LABEL_RE.finditer(full_text):
        out.append(Figure(
            label=f"Figure {m.group(1)}",
            caption=m.group(2).strip(),
            page=0,  # full-text scan — page boundary not preserved
        ))
    return tuple(out)


# --- Title + author best-effort -----------------------------------------


# Day 10.17 Phase 1.5 — author-line shape. Used by the title
# extractor to stop continuation when the next line is the authors
# block (rather than continuing prose). Each subpattern captures one
# common author-list shape we observed across the 7 reference PDFs:
#   - LastName + superscript digit ("Walton1", "Konopka1,2")
#   - Aging Cell pipe separator (" | " between authors)
#   - "et al."
#   - Semicolon-separated authors ("Keys, Matthew Thomas; Hallas, Jesper")
#     — Keys 2025 cover-page lists authors this way without superscripts
#
# Reviewer fix: initials pattern split out to require ≥2 instances on
# the line. A single `[A-Z]\.\s*[A-Z]` match false-positives on title
# tokens like "U.S. Adults" / "U.K. Biobank" / "P.D. Studies". Author
# lines almost always have multiple initial pairs (multi-author
# papers), so requiring 2+ catches authors without dropping titles.
_AUTHOR_LINE_RE = re.compile(
    r"(?:[A-Z][a-z]+\s*\d"
    r"|\s\|\s"
    r"|\bet\s+al\b"
    r"|;\s+[A-Z][a-z]+,\s+[A-Z])",
)
_INITIALS_PAIR_RE = re.compile(r"[A-Z]\.\s*[A-Z]")


def _is_author_line(line: str) -> bool:
    """Author-line detection. True if any of:
      1. `_AUTHOR_LINE_RE` matches (LastName+digit, " | ", "et al",
         "; LastName, F" semicolon-author).
      2. Line has 2+ initial pairs ("A. B. Smith and C. D. Jones" —
         the reviewer-flagged 'multiple initials' check that distinguishes
         author lines from title fragments containing "U.S. Adults" or
         "U.K. Biobank").
      3. Line has 4+ commas AND no English prose connectors. Witham 2025
         author line is a 9-name comma list with NO superscripts, NO
         pipes, NO et-al, and only single-initial middle names like
         "Miles D Witham" (no period after D). Author lists virtually
         never contain "the", "and", "of", "to", "in", "with", "for"
         — those are a strong negative signal for "this is just authors".
    """
    if _AUTHOR_LINE_RE.search(line):
        return True
    if len(_INITIALS_PAIR_RE.findall(line)) >= 2:
        return True
    if line.count(",") >= 4:
        # Tokenize lowercased words and check for prose connectors.
        # Author names get past this check easily ("Miles D Witham,
        # Claire McDonald" — no connector words).
        prose_connectors = {
            "the", "and", "of", "to", "in", "with", "for", "on", "at",
            "by", "from", "is", "are", "was", "were", "an", "as",
        }
        words = re.findall(r"[a-z]+", line.lower())
        if not (set(words) & prose_connectors):
            return True
    return False


# Day 10.17 Phase 1.5 — institutional cover-page lines that some
# repositories (e.g. SDU's Pure for Keys 2025) prepend before the
# real title. Skip lines that match this shape so the candidate-
# selection loop reaches the actual title line.
_INSTITUTIONAL_COVER_RE = re.compile(
    r"^(?:university|institute|department|school|college|hospital|"
    r"published in|publication date|document version|document license|"
    r"citation for pulished|citation for published|"
    r"this work is brought)",
    re.IGNORECASE,
)


# Day 10.17 Phase 1.5 — soft hyphens (­ / \xad) leak through
# PyMuPDF text extraction inside hyphenated words like
# "Geroscience-\xadguided" / "FDA-\xadapproved". Strip them from
# titles so downstream tools see clean ASCII-ish prose. We don't
# touch the body text (sections.*) since they may legitimately
# contain soft hyphens at line-break positions.
_SOFT_HYPHEN = "­"


def _extract_title(first_page: str) -> str:
    """Best-effort title: find the first plausible title line, then
    consume continuation lines until a stop signal (authors line,
    blank line, abstract heading). PyMuPDF gives layout-correct line
    order; titles often span 2-4 lines for long journal article names.

    Day 10.17 Phase 1 reviewer fix: skip journal article-type
    headers ("ORIGINAL ARTICLE" / "REVIEW" / "SHORT TAKE" — often
    rendered with letter-spacing artifacts like "O R I G I N A L")
    + reassemble multi-line titles instead of returning just the
    first line.
    """
    lines = first_page.split("\n")
    skip_terms = (
        "aging cell", "open access", "creative commons",
        "doi:", "received", "accepted", "first published",
        "wiley", "page", "© 20", "© 19", "©20", "©19",
        "lancet", "frontiers in", "ageing research",
        "elsevier", "springer", "publication date",
        "document license", "document version",
        "citation for pulished", "citation for published",
    )
    article_type_terms = (
        "original article", "original paper", "research article",
        "research paper", "review article", "review paper",
        "short take", "short report", "short communication",
        "letter", "commentary", "perspective", "editorial",
        "rapid communication", "research", "review", "opinion",
        "case study", "clinical trial", "meta-analysis",
        "systematic review",
    )
    for i, line in enumerate(lines):
        line = line.strip()
        if len(line) < 10 or len(line) > 250:
            continue
        low = line.lower()
        # Heavy letter-spacing artifact ("O R I G I N A L") — collapse
        # spaces and re-test.
        collapsed = re.sub(r"\s+", " ", low)
        if any(skip in low or skip in collapsed for skip in skip_terms):
            continue
        # Article type ("ORIGINAL ARTICLE") with or without spacing.
        compact = re.sub(r"\s+", "", collapsed)
        if any(re.sub(r"\s+", "", t) == compact for t in article_type_terms):
            continue
        # Day 10.17 Phase 1.5 — institutional cover-page wrapper
        # ("University of Southern Denmark" prefix on Keys 2025).
        # These ARE capitalized and pass the article-type filters
        # but precede the real title; skip them.
        if _INSTITUTIONAL_COVER_RE.match(line):
            continue
        # Day 10.17 Phase 1.5 — author-line shape on the candidate
        # itself (Kulkarni 2022 had the title detector pick up the
        # authors line "Ameya S. Kulkarni1 | Sandra Aleksic2 | ..."
        # because pre-fix logic only checked continuation lines).
        if _is_author_line(line):
            continue
        if not re.match(r"^[A-Z]", line):
            continue
        # Found a candidate title line — consume continuation lines.
        title_parts = [line.rstrip(":").rstrip()]
        for j in range(i + 1, min(i + 5, len(lines))):
            cont = lines[j].strip()
            if not cont:
                break
            if cont.lower().startswith(("abstract", "summary", "introduction")):
                break
            # Day 10.17 Phase 1.5 - replace the brittle comma-count
            # heuristic ("3 commas == authors") with author-line shape
            # detection. Pre-fix check false-positived on Walton 2019
            # line "randomized, double-blind, placebo-controlled,
            # multicenter trial:" - has 3 commas but is title prose.
            if _is_author_line(cont):
                break
            # Institutional cover lines after the title can also signal
            # we have left the title block (Keys "Published in:" etc).
            if _INSTITUTIONAL_COVER_RE.match(cont):
                break
            if len(cont) > 200:
                break
            title_parts.append(cont)
        title = " ".join(title_parts)
        # Day 10.17 Phase 1.5 - strip soft hyphens (PyMuPDF leaks them
        # inside hyphenated words like "Geroscience-\xadguided"). Then
        # collapse internal whitespace.
        title = title.replace(_SOFT_HYPHEN, "")
        title = re.sub(r"\s+", " ", title).strip()
        return title
    return ""


def _extract_authors(first_page: str) -> tuple[str, ...]:
    """Best-effort authors: typically a comma/and-separated list
    immediately after the title. We capture it as a single line then
    split on commas + 'and'."""
    title = _extract_title(first_page)
    if not title:
        return ()
    title_idx = first_page.find(title)
    if title_idx < 0:
        return ()
    rest = first_page[title_idx + len(title):].strip()
    # Take the next 2-3 lines and look for an authors-shaped block.
    candidate_lines = rest.split("\n")
    authors_block = ""
    for line in candidate_lines[:5]:
        line = line.strip()
        if not line:
            continue
        # Author lines usually have ", " and end with a period or
        # superscript-affiliation marker. Stop when we see Abstract /
        # Introduction.
        if line.lower().startswith(("abstract", "introduction", "summary")):
            break
        authors_block += " " + line
        if " and " in line.lower() or "," in line:
            break
    if not authors_block:
        return ()
    parts = re.split(r",\s*|\s+and\s+", authors_block.strip())
    cleaned = tuple(p.strip(" .,*†‡§¶") for p in parts if p.strip(" .,*†‡§¶"))
    # Keep only plausible author-name-shaped entries (≤ 5 words, ≤ 50 chars)
    plausible = tuple(
        a for a in cleaned
        if 3 <= len(a) <= 50 and len(a.split()) <= 5
    )
    return plausible


# Day 10.17 Phase 1.5 reviewer fix: word-boundary anchored AND
# longest-name first so "Aging Cell" matches before "Cell" and
# "Sports Science" doesn't false-match "Science". The ordering is
# load-bearing — first match wins.
_JOURNAL_HINTS = (
    "Lancet Healthy Longevity",
    "Ageing Research Reviews",
    "Journal of Gerontology",
    "Frontiers in Endocrinology",
    "Frontiers in Aging",
    "Nature Aging",
    "Cell Metabolism",
    "Diabetes Care",
    "Diabetologia",
    "JCI Insight",
    "Aging Cell",
    "GeroScience",
    "Lancet",
    "JAMA",
    "BMJ",
    "NEJM",
    "Nature",
    # "Science" intentionally NOT in the list — too short, too
    # ambiguous against "Sports Science" / "Computer Science" etc.
)


def _extract_journal(first_page: str) -> str:
    """Match journal name with word boundaries. Per reviewer pin:
    pre-fix substring match caught 'Science' inside 'Sports Science'
    affiliations. Now requires word-boundary match and prefers
    longer journal names (the _JOURNAL_HINTS tuple is ordered
    longest-first so first match wins).

    Day 10.17 Phase 1.5: scan the whole first page, not the first
    2500 chars. Konopka/MILES/Witham/Mohammed all place the journal
    name in the citation block past char 3000 (well past abstracts
    on the same page). Whole-first-page scan is fine — the journal
    name is unique enough that false positives are vanishingly rare,
    and `_JOURNAL_HINTS` is curated so word-boundary regex won't
    misfire on body prose."""
    for j in _JOURNAL_HINTS:
        pattern = r"\b" + re.escape(j) + r"\b"
        if re.search(pattern, first_page, re.IGNORECASE):
            return j
    return ""


# --- Top-level ingest ----------------------------------------------------


def ingest_pdf(pdf_path: Path) -> PaperSections:
    """Parse one PDF into a PaperSections artifact. Tries PyMuPDF
    first; falls back to pypdf if PyMuPDF can't open the file."""
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))

    full_text, page_texts, used_fallback = _extract_text(pdf_path)
    first_page = page_texts[0] if page_texts else ""

    title = _extract_title(first_page)
    authors = _extract_authors(first_page)
    year = _extract_year(first_page)
    journal = _extract_journal(first_page)
    # Day 10.17 Phase 1 reviewer-fix: scan full text for DOI, not
    # just front matter. Several Aging Cell PDFs place the DOI in
    # the running header beyond the first 3000 chars; Lancet /
    # Elsevier hide it in margins. Whole-text scan is fine — first
    # match wins, DOIs are unique enough that false positives are
    # vanishingly rare.
    doi = _extract_doi(full_text)
    pmid = _extract_pmid(full_text)
    trial_ids = _extract_trial_ids(full_text)

    sections, detected = _split_sections(full_text)
    # Day 10.17 Phase 1.5 — recover unlabeled abstracts (Mohammed
    # 2021 / Frontiers shape: prose between affiliations and
    # Introduction with no Abstract heading). Only fires when the
    # labeled splitter found nothing for `abstract`.
    if not sections.abstract:
        unlabeled = _extract_unlabeled_abstract(
            full_text, title, sections, detected,
        )
        if unlabeled:
            sections = Sections(
                abstract=unlabeled,
                introduction=sections.introduction,
                methods=sections.methods,
                results=sections.results,
                discussion=sections.discussion,
                limitations=sections.limitations,
                conclusion=sections.conclusion,
                references=sections.references,
            )
            detected = ["abstract"] + detected
    tables = _detect_tables_via_pdfplumber(pdf_path)
    figures = _detect_figures_via_captions(full_text)
    # Day 10.17 Phase 1 reviewer-fix: splitlines() correctly handles
    # final-line-without-trailing-newline (count("\n") was off-by-one
    # depending on how the PDF ended its references block).
    reference_count = (
        len(sections.references.splitlines())
        if sections.references else 0
    )

    warnings: list[str] = []
    if used_fallback:
        warnings.append("pymupdf failed; used pypdf fallback")
    if not title:
        warnings.append("title not detected")
    if not sections.abstract:
        warnings.append("abstract not detected")
    if not sections.methods:
        warnings.append("methods not detected")
    if not sections.results:
        warnings.append("results not detected")
    if not sections.discussion:
        warnings.append("discussion not detected")

    quality = ExtractionQuality(
        section_coverage=tuple(detected),
        table_count=len(tables),
        figure_count=len(figures),
        reference_count=reference_count,
        warnings=tuple(warnings),
    )

    return PaperSections(
        paper_id=pdf_path.stem,
        source_pdf=str(pdf_path),
        title=title, authors=authors, year=year, journal=journal,
        doi=doi, pmid=pmid, trial_ids=trial_ids,
        sections=sections, tables=tables, figures=figures,
        extraction_quality=quality,
    )


def _extract_text(pdf_path: Path) -> tuple[str, list[str], bool]:
    """Return (full_text, page_texts, used_fallback). Tries PyMuPDF
    first; falls back to pypdf on any failure."""
    try:
        doc = fitz.open(str(pdf_path))
        page_texts = [page.get_text() for page in doc]
        doc.close()
        return "\n\n".join(page_texts), page_texts, False
    except Exception:
        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf_path))
            page_texts = [p.extract_text() or "" for p in reader.pages]
            return "\n\n".join(page_texts), page_texts, True
        except Exception as e:
            raise RuntimeError(
                f"both PDF parsers failed for {pdf_path}: {e}",
            ) from e


def _to_json_dict(paper: PaperSections) -> dict:
    """Convert PaperSections to a JSON-serializable dict — tuples
    become lists, dataclasses become dicts."""
    d = asdict(paper)
    # asdict converts tuples to lists already, so the output is JSON-clean
    return d


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ingest one PDF, write paper_sections.json next to it
    (or to --out), print a one-line summary on stderr."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Ingest a PDF into structured paper_sections.json",
    )
    parser.add_argument("pdf", help="Path to the PDF")
    parser.add_argument(
        "--out", help="Output path (default: <pdf>.paper_sections.json)",
    )
    args = parser.parse_args(argv)
    pdf_path = Path(args.pdf).resolve()
    out_path = (
        Path(args.out).resolve() if args.out
        else pdf_path.with_suffix(".paper_sections.json")
    )
    paper = ingest_pdf(pdf_path)
    out_path.write_text(json.dumps(_to_json_dict(paper), indent=2))
    q = paper.extraction_quality
    summary = (
        f"{paper.paper_id}: title={'Y' if paper.title else 'N'} "
        f"abstract={'Y' if paper.sections.abstract else 'N'} "
        f"sections={len(q.section_coverage)} tables={q.table_count} "
        f"figures={q.figure_count} refs={q.reference_count} "
        f"warnings={len(q.warnings)}"
    )
    print(summary, file=sys.stderr)
    # Day 10.17 Phase 1 reviewer-fix: distinguish FATAL (script
    # couldn't extract anything load-bearing — title missing, or
    # zero sections detected, or no identifier at all) from
    # INFORMATIONAL (a specific section heading wasn't matched —
    # known limitation for review-style papers with unlabeled
    # prose abstracts; downstream Phase 2 still consumes the
    # artifact). Pre-fix, exit 1 on any "not detected" warning
    # caused CI/scripts to treat known limitations as failures.
    fatal = (
        not paper.title
        or not paper.extraction_quality.section_coverage
        or not (paper.doi or paper.pmid or paper.trial_ids)
    )
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
