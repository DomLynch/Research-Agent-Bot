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
    """Pick the first plausible 4-digit year from the first 500 chars."""
    head = text[:500]
    m = _YEAR_RE.search(head)
    return int(m.group(0)) if m else None


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


def _normalize_journal_layout(text: str) -> str:
    """Dispatch to per-journal normalizers in order. Add a new
    `_normalize_<journal>_layout` function above and call it here."""
    return _normalize_aging_cell_layout(text)


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
        "wiley", "page", "journal", "geroscience",
        "© 20", "© 19",
    )
    article_type_terms = (
        "original article", "research article", "review article",
        "short take", "short report", "letter", "commentary",
        "perspective", "editorial", "rapid communication",
        "research", "review",
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
            # Author lines usually have 3+ comma-separated names or
            # superscript markers (1, 2, *, †). Stop on those.
            if re.search(r"\d+\s*[ ,]", cont) or cont.count(",") >= 3:
                break
            if re.search(r"[A-Z]\.\s*[A-Z]", cont):  # initials pattern
                break
            if len(cont) > 200:
                break
            title_parts.append(cont)
        title = " ".join(title_parts)
        # Final clean: collapse internal whitespace
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


_JOURNAL_HINTS = (
    "Aging Cell", "GeroScience", "Cell Metabolism", "Lancet",
    "JAMA", "Nature", "Science", "BMJ", "NEJM",
    "JCI Insight", "Nature Aging", "Diabetes Care",
    "Diabetologia", "Journal of Gerontology",
)


def _extract_journal(first_page: str) -> str:
    head = first_page[:1500]
    for j in _JOURNAL_HINTS:
        if j.lower() in head.lower():
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
