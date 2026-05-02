"""Tests for scripts/pdf_ingest.py — Day 10.17 Path B-prime Phase 1.

The 7 reference PDFs are the ingestion test corpus. We know what
each paper contains (gold passages from
docs/quality-reference/metformin/README.md) so we can grade the
parser deterministically.

Walton/MASTERS is the canonical test target — cleanest published
RCT shape, used to develop the parser. The other 6 are run as a
batch in test_all_seven_reference_papers_extract_minimum_fields
to surface any parser failures honestly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# scripts/ is not a package — import via path manipulation
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pdf_ingest  # noqa: E402

PDFS_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs" / "quality-reference" / "metformin" / "pdfs"
)
MASTERS_PDF = PDFS_DIR / "Walton_2019_MASTERS_metformin_blunts_resistance_hypertrophy.pdf"


def _all_pdfs() -> list[Path]:
    return sorted(PDFS_DIR.glob("*.pdf"))


# ============================================================
# MASTERS — canonical development target
# ============================================================


@pytest.mark.skipif(
    not MASTERS_PDF.exists(),
    reason="MASTERS PDF not present (gitignored, see Phase 1 README)",
)
class TestMastersExtraction:
    """Discriminating tests against the Walton 2019 MASTERS PDF.
    The gold values are taken from
    docs/quality-reference/metformin/README.md (which lists DOI,
    PMID, NCT, journal, year, gold passages)."""

    @pytest.fixture(scope="class")
    def paper(self) -> pdf_ingest.PaperSections:
        return pdf_ingest.ingest_pdf(MASTERS_PDF)

    def test_paper_id_matches_pdf_stem(
        self, paper: pdf_ingest.PaperSections,
    ) -> None:
        assert paper.paper_id == MASTERS_PDF.stem

    def test_extracts_doi(self, paper: pdf_ingest.PaperSections) -> None:
        # Per README: 10.1111/acel.13039
        assert paper.doi == "10.1111/acel.13039", (
            f"DOI not extracted; got {paper.doi!r}"
        )

    def test_extracts_nct_trial_id(
        self, paper: pdf_ingest.PaperSections,
    ) -> None:
        # Per README: NCT02308228
        assert "NCT02308228" in paper.trial_ids, (
            f"trial id not detected; got {paper.trial_ids}"
        )

    def test_extracts_year_2019(
        self, paper: pdf_ingest.PaperSections,
    ) -> None:
        assert paper.year == 2019, f"year not 2019; got {paper.year}"

    def test_extracts_journal_aging_cell(
        self, paper: pdf_ingest.PaperSections,
    ) -> None:
        assert "Aging Cell" in paper.journal, (
            f"journal not Aging Cell; got {paper.journal!r}"
        )

    def test_extracts_title_mentions_metformin(
        self, paper: pdf_ingest.PaperSections,
    ) -> None:
        # Per README, the title mentions "metformin" + "MASTERS" /
        # "resistance" — title detection is best-effort, just verify
        # plausible content.
        assert paper.title, "title is empty"
        title_lower = paper.title.lower()
        assert "metformin" in title_lower or "masters" in title_lower, (
            f"title missing metformin/masters: {paper.title!r}"
        )

    def test_separates_methods_from_results(
        self, paper: pdf_ingest.PaperSections,
    ) -> None:
        """Methods and Results must be distinct non-empty sections."""
        assert paper.sections.methods, "methods section empty"
        assert paper.sections.results, "results section empty"
        # They mustn't be identical (would mean the splitter failed).
        assert paper.sections.methods != paper.sections.results

    def test_separates_discussion_from_results(
        self, paper: pdf_ingest.PaperSections,
    ) -> None:
        assert paper.sections.discussion, "discussion section empty"
        assert paper.sections.discussion != paper.sections.results

    def test_results_section_contains_metformin_finding(
        self, paper: pdf_ingest.PaperSections,
    ) -> None:
        """The results section should contain a key Walton 2019
        finding about metformin and hypertrophy/training (per gold
        passage in README)."""
        results_lower = paper.sections.results.lower()
        # Must mention metformin AND a training-related term
        assert "metformin" in results_lower
        # Check for any of: hypertrophy, training, resistance, AMPK,
        # mTORC1 — gold passages mention these
        relevant_terms = ("hypertrophy", "training", "resistance",
                          "ampk", "mtorc1")
        assert any(t in results_lower for t in relevant_terms), (
            "results section missing expected MASTERS terminology"
        )

    def test_extraction_quality_reports_section_coverage(
        self, paper: pdf_ingest.PaperSections,
    ) -> None:
        """At minimum, abstract/methods/results/discussion should
        be detected for a clean RCT paper."""
        coverage = set(paper.extraction_quality.section_coverage)
        required = {"abstract", "methods", "results", "discussion"}
        missing = required - coverage
        assert not missing, (
            f"section coverage missing: {missing}"
        )


# ============================================================
# Batch run — all 7 reference PDFs
# ============================================================


@pytest.mark.skipif(
    not _all_pdfs(),
    reason="No PDFs in docs/quality-reference/metformin/pdfs/",
)
def test_all_seven_reference_papers_extract_minimum_fields() -> None:
    """Run the parser against all 7 reference PDFs and assert the
    minimum-success contract for each: paper_id matches stem,
    title detected, no parse exception, ≥1 substantive section
    captured. Some papers (e.g. Aging Cell "Short Takes" like
    MILES / Kulkarni 2018) merge methods/results/discussion into
    the body without explicit headings — those legitimately
    register as 2-section papers (introduction + references) and
    are NOT parser failures. Phase 2 claim extraction reads
    section bodies; even a 2-section short-take is usable
    because the content lives in `sections.introduction`.

    Failures reported per-paper so parser-tuning priorities are
    visible at-a-glance."""
    pdfs = _all_pdfs()
    assert len(pdfs) >= 1, "no reference PDFs found"
    failures: list[str] = []
    for pdf_path in pdfs:
        try:
            paper = pdf_ingest.ingest_pdf(pdf_path)
        except Exception as e:
            failures.append(f"{pdf_path.name}: parse failed — {e}")
            continue
        if not paper.title:
            failures.append(f"{pdf_path.name}: no title")
        # Identifier contract: at least ONE of DOI / PMID / trial_id
        # must be extractable. Some clinical-trial papers (Lancet
        # Healthy Longevity / Elsevier) place DOI in margins where
        # PyMuPDF can't reach but include the trial registry id in
        # body text — those still qualify as identifiable.
        if not (paper.doi or paper.pmid or paper.trial_ids):
            failures.append(
                f"{pdf_path.name}: no DOI / PMID / trial_id extracted"
            )
        coverage = set(paper.extraction_quality.section_coverage)
        # ≥2 sections: introduction OR abstract on one side, refs
        # / methods / results / discussion on the other. Strictest
        # threshold that doesn't false-fail short-take papers.
        if len(coverage) < 2:
            failures.append(
                f"{pdf_path.name}: only {len(coverage)} sections "
                f"detected ({sorted(coverage)})"
            )
        # And the first detected section must have actual content
        non_empty_sections = [
            n for n in coverage
            if getattr(paper.sections, n, "").strip()
        ]
        if not non_empty_sections:
            failures.append(
                f"{pdf_path.name}: detected sections all empty"
            )
    assert not failures, (
        "Parser failures across the 7 reference PDFs:\n  - "
        + "\n  - ".join(failures)
    )


# ============================================================
# JSON round-trip
# ============================================================


@pytest.mark.skipif(
    not MASTERS_PDF.exists(),
    reason="MASTERS PDF not present",
)
def test_paper_sections_json_round_trip(tmp_path: Path) -> None:
    """The artifact must serialize to JSON and round-trip without
    losing fields. Downstream consumers (Phase 2 claim extractor,
    Phase 5 ablation scorer) need a stable JSON shape."""
    paper = pdf_ingest.ingest_pdf(MASTERS_PDF)
    json_dict = pdf_ingest._to_json_dict(paper)
    out_path = tmp_path / "out.json"
    out_path.write_text(json.dumps(json_dict, indent=2))
    loaded = json.loads(out_path.read_text())
    assert loaded["paper_id"] == paper.paper_id
    assert loaded["doi"] == paper.doi
    assert loaded["title"] == paper.title
    assert "sections" in loaded
    assert "extraction_quality" in loaded
    assert isinstance(loaded["trial_ids"], list)


# ============================================================
# Metadata extractor unit tests (no PDF needed)
# ============================================================


def test_doi_regex_extracts_aging_cell_doi() -> None:
    text = "Published online 2019. doi: 10.1111/acel.13039 page 7"
    assert pdf_ingest._extract_doi(text) == "10.1111/acel.13039"


def test_pmid_regex_extracts_8_digit_pmid() -> None:
    text = "PMID: 31557380 (Aging Cell)"
    assert pdf_ingest._extract_pmid(text) == "31557380"


def test_trial_id_regex_extracts_nct_and_isrctn() -> None:
    text = "Trial registry: NCT02308228 and ISRCTN29932357"
    ids = pdf_ingest._extract_trial_ids(text)
    assert "NCT02308228" in ids
    assert "ISRCTN29932357" in ids


def test_year_regex_extracts_4_digit_year_in_head() -> None:
    text = "Walton et al. 2019. Aging Cell volume 18..."
    assert pdf_ingest._extract_year(text) == 2019


def test_year_regex_returns_none_when_absent() -> None:
    text = "No date in this header"
    assert pdf_ingest._extract_year(text) is None
