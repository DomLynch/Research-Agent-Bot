"""Day 10.17 Phase 3 — corpus expansion via Europe PMC OA full text.

Goal: add 25+ metformin/aging papers to the quality-reference corpus
without manually downloading 25 PDFs. Europe PMC has full JATS XML
for every CC-BY / CC0 / PMC paper (~70-80% of recent metformin/aging
literature). This script fetches XML and emits paper_sections.json
files that are SCHEMA-IDENTICAL to the Phase 1.5 PDF-ingest output
(so quant_claim_extract.py and Phase 4 see them as just-more-papers).

Lives in scripts/ — uses httpx (already an agent/ dep) plus stdlib
xml.etree. No new runtime deps. AGENTS.md "code disposes" rule:
this is the corpus-build side, deterministic XML parsing, no LLM.

Pipeline:
  1. Search Europe PMC OR read curated PMCID manifest
  2. Fetch each PMCID's fullTextXML (cached to .cache/europepmc/)
  3. Parse JATS → paper_sections-compatible dict
  4. Write to docs/quality-reference/metformin/parsed/

JATS section mapping (sec-type → our schema):
  intro            → introduction
  materials|methods → methods
  results          → results
  discussion       → discussion
  conclusions      → conclusion
  supplementary-material → SKIP (not real claims)
  unlabeled        → title-keyword heuristic, else dropped
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx

__all__ = [
    "EUROPEPMC_SEARCH_URL",
    "EUROPEPMC_FULLTEXT_URL_TEMPLATE",
    "EuropePMCError",
    "PaperRecord",
    "search_oa_corpus",
    "fetch_full_text_xml",
    "parse_jats_to_paper_sections",
    "main",
]


EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPEPMC_FULLTEXT_URL_TEMPLATE = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
)
DEFAULT_CACHE_DIR = Path(".cache/europepmc")
DEFAULT_OUT_DIR = Path("docs/quality-reference/metformin/parsed")
# Be courteous to Europe PMC — bulk fetches at <2 req/s.
INTER_FETCH_DELAY_SECS = 0.6


# JATS sec-type → our paper_sections schema name. Sections not in this
# map (e.g. supplementary-material, COI-statement) are dropped — they
# don't carry quantitative claims.
_SEC_TYPE_MAP = {
    "intro": "introduction",
    "materials|methods": "methods",
    "methods": "methods",
    "materials": "methods",
    "results": "results",
    "discussion": "discussion",
    "conclusions": "conclusion",
    "conclusion": "conclusion",
    "limitations": "limitations",
    "abstract": "abstract",
}
# Title-keyword heuristic for sections without sec-type. Order matters —
# longer / more-specific keywords MUST come first (reviewer fix:
# pre-fix had "discussion" before "limitations", so a section titled
# "Discussion of Limitations" wrongly mapped to discussion). Always
# put the more-specific match earlier.
_TITLE_KEYWORDS = (
    ("introduction", "introduction"),
    ("background", "introduction"),
    ("materials and methods", "methods"),
    ("methods and materials", "methods"),
    ("methodology", "methods"),
    ("methods", "methods"),
    ("results and discussion", "results"),
    ("results", "results"),
    ("limitations", "limitations"),  # MUST precede "discussion"
    ("conclusions", "conclusion"),
    ("conclusion", "conclusion"),
    ("discussion", "discussion"),
    ("references", "references"),
)


class EuropePMCError(RuntimeError):
    """Raised when Europe PMC returns an unexpected response."""


@dataclass(frozen=True, slots=True)
class PaperRecord:
    """One Europe PMC search hit (search-result level, no full text yet)."""
    pmid: str
    pmcid: str
    doi: str
    title: str
    journal: str
    year: int | None


def search_oa_corpus(
    query: str, *, limit: int = 50, page_size: int = 25,
    client: httpx.Client | None = None,
) -> list[PaperRecord]:
    """Page through Europe PMC search and return the OA hits with PMCID
    (those have full text available). Caller owns the httpx client if
    passed; otherwise we open one with sane defaults."""
    own_client = False
    if client is None:
        client = httpx.Client(timeout=30.0)
        own_client = True
    try:
        out: list[PaperRecord] = []
        cursor = "*"
        while len(out) < limit:
            params = {
                "query": query,
                "format": "json",
                "pageSize": str(min(page_size, limit - len(out))),
                "resultType": "core",
                "cursorMark": cursor,
            }
            r = client.get(EUROPEPMC_SEARCH_URL, params=params)
            r.raise_for_status()
            data = r.json()
            hits = data.get("resultList", {}).get("result", [])
            if not hits:
                break
            for h in hits:
                pmcid = h.get("pmcid", "")
                if not pmcid:
                    continue  # no full text without PMCID
                out.append(PaperRecord(
                    pmid=h.get("pmid", ""),
                    pmcid=pmcid,
                    doi=h.get("doi", ""),
                    title=(h.get("title", "") or "").strip(),
                    journal=h.get("journalTitle", "") or h.get("journalInfo", {}).get("journal", {}).get("title", ""),
                    year=int(h["pubYear"]) if h.get("pubYear") else None,
                ))
            next_cursor = data.get("nextCursorMark")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return out[:limit]
    finally:
        if own_client:
            client.close()


def fetch_full_text_xml(
    pmcid: str, *, cache_dir: Path = DEFAULT_CACHE_DIR,
    client: httpx.Client | None = None,
) -> str:
    """Fetch JATS XML for a PMCID. Cached to disk so re-runs are free.
    Raises EuropePMCError on non-200 or empty response."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{pmcid}.xml"
    if cache_path.exists() and cache_path.stat().st_size > 200:
        return cache_path.read_text(encoding="utf-8")
    own_client = False
    if client is None:
        client = httpx.Client(timeout=60.0)
        own_client = True
    try:
        url = EUROPEPMC_FULLTEXT_URL_TEMPLATE.format(pmcid=pmcid)
        r = client.get(url)
        if r.status_code != 200:
            raise EuropePMCError(
                f"{pmcid}: HTTP {r.status_code} from Europe PMC fullTextXML",
            )
        # Europe PMC sometimes returns the XML with a DOCTYPE first
        # instead of the <?xml prolog — accept both. Reviewer-flagged
        # MEDIUM fix: pre-fix lenient `<!doctype` check would accept
        # an HTML error page (`<!DOCTYPE html>...`). Tightened to
        # require the article-specific DOCTYPE / root element.
        text_head = r.text.lstrip()[:120].lower()
        looks_like_jats = (
            text_head.startswith("<?xml")
            or text_head.startswith("<!doctype article")
            or text_head.startswith("<article")
        )
        if not looks_like_jats:
            raise EuropePMCError(
                f"{pmcid}: response is not JATS XML "
                f"(len={len(r.text)}, head={text_head[:80]!r})",
            )
        if len(r.text) < 500 or "</article>" not in r.text[-2000:]:
            raise EuropePMCError(
                f"{pmcid}: XML truncated or missing closing tag "
                f"(len={len(r.text)})",
            )
        cache_path.write_text(r.text, encoding="utf-8")
        return r.text
    finally:
        if own_client:
            client.close()


# --- JATS XML parsing ----------------------------------------------------


def _text_of(element: ET.Element | None) -> str:
    """Concatenate all text under an element, normalize whitespace."""
    if element is None:
        return ""
    parts: list[str] = []
    for piece in element.itertext():
        if piece:
            parts.append(piece)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _section_to_canonical(sec: ET.Element) -> str:
    """Map a JATS <sec> to our canonical section name. Uses sec-type
    attribute first (most reliable), then title keywords as fallback.

    Reviewer fix: title-keyword fallback uses `_text_of(title_el)`
    (NOT `title_el.text`). Pre-fix, a `<title>Materials and
    <italic>Methods</italic></title>` would yield only "Materials and "
    (text before the first child) and the substring match would fail.
    `_text_of` joins all itertext.
    """
    sec_type = (sec.attrib.get("sec-type") or "").lower().strip()
    if sec_type in _SEC_TYPE_MAP:
        return _SEC_TYPE_MAP[sec_type]
    title_el = sec.find("title")
    title = _text_of(title_el).lower() if title_el is not None else ""
    for keyword, canonical in _TITLE_KEYWORDS:
        if keyword in title:
            return canonical
    return ""  # unrecognized → drop (not a canonical section)


def _join_paragraph_text(sec: ET.Element) -> str:
    """Pull all <p> text out of a <sec>, separated by single newlines.
    Preserves paragraph breaks but flattens within-paragraph soft
    breaks (the quant extractor cares about sentences, not paragraphs)."""
    paragraphs: list[str] = []

    def visit(element: ET.Element) -> None:
        for child in element:
            if child.tag == "sec":
                continue
            if child.tag == "p":
                if text := _text_of(child):
                    paragraphs.append(text)
            else:
                visit(child)

    visit(sec)
    return "\n\n".join(paragraphs)


def _extract_doi(front: ET.Element) -> str:
    for el in front.iter("article-id"):
        if el.attrib.get("pub-id-type") == "doi":
            return (el.text or "").strip()
    return ""


def _extract_pmid(front: ET.Element) -> str:
    for el in front.iter("article-id"):
        if el.attrib.get("pub-id-type") == "pmid":
            return (el.text or "").strip()
    return ""


def _extract_year(front: ET.Element) -> int | None:
    # Prefer pub-date with pub-type="ppub" (print pub) > "epub" > any.
    for pub_type in ("ppub", "epub", "collection"):
        for el in front.iter("pub-date"):
            if el.attrib.get("pub-type") == pub_type:
                year_el = el.find("year")
                if year_el is not None and year_el.text:
                    try:
                        y = int(year_el.text)
                        if 1900 <= y <= 2100:
                            return y
                    except ValueError:
                        continue
    # Any pub-date as fallback.
    for el in front.iter("pub-date"):
        year_el = el.find("year")
        if year_el is not None and year_el.text:
            try:
                y = int(year_el.text)
                if 1900 <= y <= 2100:
                    return y
            except ValueError:
                continue
    return None


def _extract_journal(front: ET.Element) -> str:
    """Reviewer fix: use `_text_of` not `.text`. JATS often nests
    `<journal-title>` content with styled children (`<italic>` etc.);
    `.text` returns only the leading run before the first child or
    None. `_text_of` joins all itertext."""
    title_el = front.find(".//journal-title")
    return _text_of(title_el)


def _extract_authors(front: ET.Element, *, limit: int = 20) -> list[str]:
    out: list[str] = []
    for contrib in front.iter("contrib"):
        if contrib.attrib.get("contrib-type") not in (None, "author"):
            continue
        name_el = contrib.find("name")
        if name_el is None:
            continue
        surname = name_el.find("surname")
        given = name_el.find("given-names")
        s = (surname.text or "").strip() if surname is not None else ""
        g = (given.text or "").strip() if given is not None else ""
        if s:
            full = f"{g} {s}".strip()
            out.append(full)
        if len(out) >= limit:
            break
    return out


def _extract_trial_ids(text: str) -> list[str]:
    nct = re.findall(r"\bNCT\d{8}\b", text)
    isrctn = re.findall(r"\bISRCTN\d{6,10}\b", text)
    return sorted(set(nct + isrctn))


def parse_jats_to_paper_sections(
    xml_str: str, *, source_url: str = "",
) -> dict:
    """Parse JATS XML → dict matching pdf_ingest.PaperSections schema.
    Returns a dict (not a dataclass) so callers can JSON-dump directly
    without importing the pdf_ingest module (Europe PMC fetch path
    must work even without PyMuPDF installed)."""
    root = ET.fromstring(xml_str)
    front = root.find("front")
    body = root.find("body")
    if front is None:
        raise EuropePMCError("JATS XML missing <front> — malformed")

    # Title
    title_el = front.find(".//article-title")
    title = _text_of(title_el)

    # Abstract
    abstract = ""
    abstract_el = front.find(".//abstract")
    if abstract_el is not None:
        abstract = "\n\n".join(
            _text_of(p) for p in abstract_el.findall(".//p")
            if _text_of(p)
        )

    # Body sections
    sections_text: dict[str, str] = {
        n: "" for n in (
            "abstract", "introduction", "methods",
            "results", "discussion", "limitations",
            "conclusion", "references",
        )
    }
    sections_text["abstract"] = abstract
    detected: list[str] = []
    if abstract:
        detected.append("abstract")

    if body is not None:
        # Reviewer HIGH fix: walk ALL <sec> elements (incl. nested),
        # not just top-level. Many JATS papers wrap content in a
        # generic outer <sec sec-type=""> with the real
        # introduction/methods/results as nested children — pre-fix
        # these were silently dropped (PMC12954315 was the smoking
        # gun: 0 sections detected). Paragraph extraction skips nested
        # <sec> bodies so each section is appended exactly once.
        for sec in body.iter("sec"):
            canonical = _section_to_canonical(sec)
            if not canonical:
                continue
            text = _join_paragraph_text(sec)
            if text:
                sections_text[canonical] = "\n\n".join(
                    filter(None, (sections_text[canonical], text)),
                )
                if canonical not in detected:
                    detected.append(canonical)

    # References — citations live in <back><ref-list>
    back = root.find("back")
    if back is not None:
        ref_list = back.find(".//ref-list")
        if ref_list is not None:
            ref_lines = []
            for ref in ref_list.findall(".//ref"):
                ref_lines.append(_text_of(ref))
            if ref_lines:
                sections_text["references"] = "\n".join(ref_lines)
                if "references" not in detected:
                    detected.append("references")

    # Identifiers
    doi = _extract_doi(front)
    pmid = _extract_pmid(front)
    journal = _extract_journal(front)
    year = _extract_year(front)
    authors = _extract_authors(front)

    # Trial IDs from full body text (NCT/ISRCTN tokens)
    full_text_for_trial_scan = " ".join(sections_text.values())
    trial_ids = _extract_trial_ids(full_text_for_trial_scan)

    paper_id = _derive_paper_id(pmid, pmcid_from_url(source_url), title)

    return {
        "paper_id": paper_id,
        "source_pdf": source_url,  # field name kept for schema compat
        "title": title,
        "authors": authors,
        "year": year,
        "journal": journal,
        "doi": doi,
        "pmid": pmid,
        "trial_ids": trial_ids,
        "sections": sections_text,
        "tables": [],   # JATS has structured tables; left for Phase 3.1
        "figures": [],  # ditto
        "extraction_quality": {
            "section_coverage": detected,
            "table_count": 0,
            "figure_count": 0,
            "reference_count": (
                len(sections_text["references"].splitlines())
                if sections_text["references"] else 0
            ),
            "warnings": [
                "europepmc-jats: tables and figures not extracted in v0.1",
            ],
        },
    }


def pmcid_from_url(url: str) -> str:
    """Extract PMC<digits> from a Europe PMC URL (or return ""."""
    m = re.search(r"PMC\d+", url)
    return m.group(0) if m else ""


def _derive_paper_id(pmid: str, pmcid: str, title: str) -> str:
    """Build a stable paper_id similar to the PDF naming convention.
    Pattern: <FirstAuthor>_<Year>_<short_title>_<pmcid>. Without
    author info available at this point, fall back to PMCID + title
    slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title.lower()).strip("_")[:60]
    if pmcid:
        return f"{pmcid}_{slug}" if slug else pmcid
    if pmid:
        return f"PMID{pmid}_{slug}" if slug else f"PMID{pmid}"
    return slug or "unknown"


# --- Top-level orchestration ---------------------------------------------


def fetch_and_save(
    pmcids: list[str], *, out_dir: Path = DEFAULT_OUT_DIR,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    client: httpx.Client | None = None,
    fetch_delay: float = INTER_FETCH_DELAY_SECS,
) -> tuple[int, int]:
    """Fetch each PMCID, parse, write paper_sections.json. Returns
    (n_succeeded, n_failed)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    own_client = False
    if client is None:
        client = httpx.Client(timeout=60.0)
        own_client = True
    n_ok = 0
    n_fail = 0
    try:
        for i, pmcid in enumerate(pmcids):
            if i > 0:
                time.sleep(fetch_delay)
            try:
                xml = fetch_full_text_xml(
                    pmcid, cache_dir=cache_dir, client=client,
                )
                source_url = EUROPEPMC_FULLTEXT_URL_TEMPLATE.format(pmcid=pmcid)
                doc = parse_jats_to_paper_sections(xml, source_url=source_url)
                out_path = out_dir / f"{doc['paper_id']}.paper_sections.json"
                out_path.write_text(json.dumps(doc, indent=2))
                n_ok += 1
                print(
                    f"  [{i+1}/{len(pmcids)}] OK {pmcid} -> "
                    f"{doc['paper_id']}.paper_sections.json "
                    f"(sections={len(doc['extraction_quality']['section_coverage'])})",
                    file=sys.stderr,
                )
            except Exception as e:
                n_fail += 1
                print(
                    f"  [{i+1}/{len(pmcids)}] FAIL {pmcid}: {e}",
                    file=sys.stderr,
                )
    finally:
        if own_client:
            client.close()
    return n_ok, n_fail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch open-access full text from Europe PMC + emit "
            "paper_sections.json files (Phase 1.5 schema-compatible)"
        ),
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--pmcids", help="Comma-separated PMC ids (PMC1234567,PMC...)",
    )
    src.add_argument(
        "--query",
        help='Europe PMC search query, e.g. "metformin AND aging"',
    )
    parser.add_argument(
        "--limit", type=int, default=30,
        help="Max OA hits to fetch when --query is used",
    )
    parser.add_argument(
        "--out-dir", default=str(DEFAULT_OUT_DIR),
        help="Where to write paper_sections.json files",
    )
    parser.add_argument(
        "--cache-dir", default=str(DEFAULT_CACHE_DIR),
        help="Where to cache fetched JATS XML",
    )
    args = parser.parse_args(argv)

    if args.pmcids:
        pmcids = [p.strip() for p in args.pmcids.split(",") if p.strip()]
    else:
        print(f"Searching Europe PMC: {args.query}", file=sys.stderr)
        with httpx.Client(timeout=30.0) as client:
            hits = search_oa_corpus(
                args.query, limit=args.limit, client=client,
            )
        pmcids = [h.pmcid for h in hits if h.pmcid]
        print(
            f"Found {len(pmcids)} OA hits with PMCID (of {args.limit} requested)",
            file=sys.stderr,
        )

    if not pmcids:
        print("No PMCIDs to fetch", file=sys.stderr)
        return 1

    n_ok, n_fail = fetch_and_save(
        pmcids,
        out_dir=Path(args.out_dir),
        cache_dir=Path(args.cache_dir),
    )
    print(f"Done: {n_ok} OK, {n_fail} FAIL", file=sys.stderr)
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
