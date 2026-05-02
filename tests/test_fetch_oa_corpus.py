"""Tests for scripts/fetch_oa_corpus.py — Day 10.17 Phase 3.

JATS XML fixtures are embedded inline (no network needed). The
discriminating tests pin: section mapping, identifier extraction,
title slug discipline, and schema compatibility with Phase 1.5
paper_sections.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_oa_corpus  # noqa: E402


# ============================================================
# Embedded JATS fixtures
# ============================================================


# Minimal but realistic JATS XML — covers metadata, abstract,
# 4 typed sections, and a back/ref-list. Values chosen so the
# section-mapping + identifier extraction tests can pin specific
# discriminating output.
JATS_MINIMAL = """<?xml version="1.0"?>
<article>
  <front>
    <journal-meta>
      <journal-title>Test Journal of Aging</journal-title>
    </journal-meta>
    <article-meta>
      <article-id pub-id-type="doi">10.1234/test.2026.001</article-id>
      <article-id pub-id-type="pmid">99999999</article-id>
      <title-group>
        <article-title>A Test of Metformin in Aging Adults</article-title>
      </title-group>
      <contrib-group>
        <contrib contrib-type="author">
          <name>
            <surname>Smith</surname>
            <given-names>Jane A.</given-names>
          </name>
        </contrib>
        <contrib contrib-type="author">
          <name>
            <surname>Doe</surname>
            <given-names>John B.</given-names>
          </name>
        </contrib>
      </contrib-group>
      <pub-date pub-type="ppub"><year>2026</year></pub-date>
      <abstract>
        <p>This trial tested whether metformin (n = 30) improves
        outcomes in older adults compared to placebo (n = 30).
        The primary endpoint was significant (p = 0.04).</p>
      </abstract>
    </article-meta>
  </front>
  <body>
    <sec sec-type="intro">
      <title>Introduction</title>
      <p>Metformin is a glucose-lowering agent.</p>
    </sec>
    <sec sec-type="methods">
      <title>Methods</title>
      <p>Trial registration NCT12345678. Randomized double-blind.</p>
    </sec>
    <sec sec-type="results">
      <title>Results</title>
      <p>Primary endpoint reached (p = 0.04, 95% CI 0.01 to 0.07).</p>
    </sec>
    <sec sec-type="discussion">
      <title>Discussion</title>
      <p>Findings consistent with prior MASTERS trial.</p>
    </sec>
  </body>
  <back>
    <ref-list>
      <ref id="r1"><citation>Walton 2019, Aging Cell.</citation></ref>
      <ref id="r2"><citation>Konopka 2019, Aging Cell.</citation></ref>
    </ref-list>
  </back>
</article>"""


# Section without sec-type attribute — must fall back to title-keyword
# heuristic (e.g. <sec><title>Materials and Methods</title>...).
JATS_NO_SEC_TYPE = """<?xml version="1.0"?>
<article>
  <front>
    <journal-meta><journal-title>X</journal-title></journal-meta>
    <article-meta>
      <article-id pub-id-type="doi">10.1234/x</article-id>
      <title-group><article-title>X</article-title></title-group>
      <pub-date pub-type="ppub"><year>2020</year></pub-date>
      <abstract><p>Abstract content.</p></abstract>
    </article-meta>
  </front>
  <body>
    <sec>
      <title>Materials and Methods</title>
      <p>Methods text.</p>
    </sec>
    <sec>
      <title>Results and Discussion</title>
      <p>Results text.</p>
    </sec>
  </body>
</article>"""


# ============================================================
# JATS parsing — section mapping
# ============================================================


def test_parses_typed_sections_into_canonical_names() -> None:
    """sec-type='intro' → introduction, sec-type='methods' → methods,
    etc. Must populate the standard section dict."""
    doc = fetch_oa_corpus.parse_jats_to_paper_sections(JATS_MINIMAL)
    assert doc["sections"]["introduction"].startswith("Metformin is")
    assert doc["sections"]["methods"].startswith("Trial registration")
    assert doc["sections"]["results"].startswith("Primary endpoint")
    assert doc["sections"]["discussion"].startswith("Findings")
    assert doc["sections"]["abstract"].startswith("This trial")


def test_falls_back_to_title_keyword_when_sec_type_missing() -> None:
    """A <sec> without sec-type but with title 'Materials and Methods'
    must map to methods. 'Results and Discussion' → results (the
    longer-name-first ordering rule)."""
    doc = fetch_oa_corpus.parse_jats_to_paper_sections(JATS_NO_SEC_TYPE)
    assert doc["sections"]["methods"] == "Methods text."
    assert doc["sections"]["results"] == "Results text."


# ============================================================
# JATS parsing — metadata
# ============================================================


def test_extracts_doi_pmid_journal_year_authors() -> None:
    doc = fetch_oa_corpus.parse_jats_to_paper_sections(JATS_MINIMAL)
    assert doc["doi"] == "10.1234/test.2026.001"
    assert doc["pmid"] == "99999999"
    assert doc["journal"] == "Test Journal of Aging"
    assert doc["year"] == 2026
    assert "Jane A. Smith" in doc["authors"]
    assert "John B. Doe" in doc["authors"]


def test_extracts_trial_ids_from_body_text() -> None:
    """NCT regex scans the joined section text. Must find NCT12345678
    even though it appears only in methods, not in dedicated metadata."""
    doc = fetch_oa_corpus.parse_jats_to_paper_sections(JATS_MINIMAL)
    assert "NCT12345678" in doc["trial_ids"]


def test_references_collected_from_back_ref_list() -> None:
    doc = fetch_oa_corpus.parse_jats_to_paper_sections(JATS_MINIMAL)
    refs = doc["sections"]["references"]
    assert "Walton 2019" in refs
    assert "Konopka 2019" in refs
    assert doc["extraction_quality"]["reference_count"] >= 2


# ============================================================
# Schema compatibility with Phase 1.5 paper_sections.json
# ============================================================


def test_output_schema_matches_pdf_ingest_paper_sections_shape() -> None:
    """The OA fetch path must emit the SAME field set as pdf_ingest's
    PaperSections so quant_claim_extract.py and Phase 4 see them as
    just-more-papers. Top-level field set is the discriminator."""
    doc = fetch_oa_corpus.parse_jats_to_paper_sections(JATS_MINIMAL)
    expected_keys = {
        "paper_id", "source_pdf", "title", "authors", "year",
        "journal", "doi", "pmid", "trial_ids", "sections",
        "tables", "figures", "extraction_quality",
    }
    assert set(doc.keys()) == expected_keys
    # And the inner sections dict has all 8 canonical names too.
    expected_section_keys = {
        "abstract", "introduction", "methods", "results",
        "discussion", "limitations", "conclusion", "references",
    }
    assert set(doc["sections"].keys()) == expected_section_keys


def test_output_round_trips_through_quant_claim_extractor() -> None:
    """Run the OA-produced doc through quant_claim_extract.py to verify
    it's a valid input to Phase 2. This is the load-bearing integration
    test — if it fails, downstream Phase 4 breaks."""
    doc = fetch_oa_corpus.parse_jats_to_paper_sections(JATS_MINIMAL)
    # Re-import here so the test doesn't depend on top-level import order
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import quant_claim_extract
    # The abstract has p=0.04, n=30 (twice). Results has p=0.04 + a 95% CI.
    claims_abstract = quant_claim_extract.extract_from_text(
        doc["sections"]["abstract"], "abstract", paper_id=doc["paper_id"],
    )
    p_claims = [c for c in claims_abstract if c.claim_type == "p_value"]
    assert len(p_claims) == 1
    n_claims = [c for c in claims_abstract if c.claim_type == "sample_size"]
    assert len(n_claims) == 2
    claims_results = quant_claim_extract.extract_from_text(
        doc["sections"]["results"], "results", paper_id=doc["paper_id"],
    )
    ci_claims = [c for c in claims_results if c.claim_type == "confidence_interval"]
    assert len(ci_claims) == 1


# ============================================================
# Paper-id discipline
# ============================================================


def test_derive_paper_id_uses_pmcid_and_title_slug() -> None:
    pid = fetch_oa_corpus._derive_paper_id(
        pmid="123", pmcid="PMC9999", title="A Test of Metformin in Aging",
    )
    assert pid == "PMC9999_a_test_of_metformin_in_aging"


def test_derive_paper_id_handles_pmcid_only() -> None:
    pid = fetch_oa_corpus._derive_paper_id(pmid="", pmcid="PMC9999", title="")
    assert pid == "PMC9999"


def test_pmcid_from_url_extracts_pmc_id() -> None:
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12345/fullTextXML"
    assert fetch_oa_corpus.pmcid_from_url(url) == "PMC12345"
    assert fetch_oa_corpus.pmcid_from_url("https://example.com/no-pmc-here") == ""


# ============================================================
# Validation guards
# ============================================================


def test_parse_jats_raises_on_missing_front() -> None:
    """An XML missing <front> is malformed JATS — the parser must
    raise EuropePMCError so the caller can record the failure
    rather than silently produce a metadata-less artifact."""
    bad_xml = "<?xml version='1.0'?><article><body><sec/></body></article>"
    import pytest
    with pytest.raises(fetch_oa_corpus.EuropePMCError):
        fetch_oa_corpus.parse_jats_to_paper_sections(bad_xml)
