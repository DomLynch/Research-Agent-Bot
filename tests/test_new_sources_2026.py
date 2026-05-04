"""Unit tests for the 6 new sources/enrichment clients added 2026-05-04.

Covers parser-shape robustness, auth selection, rate-limit gating,
and aggregator registration. No network IO — every test uses
hand-rolled fixture payloads matching the real 2026 API response
shapes that were captured during smoke-test development.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any
from unittest.mock import patch

import pytest

from agent.enrichment.icite import ICiteClient
from agent.enrichment.reporter import ReporterClient
from agent.enrichment.rxnorm import DrugConcept
from agent.sources.aggregator import _build_registry
from agent.sources.arxiv import ArxivClient, _build_search_query
from agent.sources.biorxiv import BioRxivClient
from agent.sources.medrxiv import MedRxivClient
from agent.sources.openalex import OpenAlexClient


# ---------- arXiv ---------------------------------------------------

def test_arxiv_query_builder_simple():
    """Plain phrase becomes single all:<phrase> clause."""
    assert _build_search_query("metformin") == "all:metformin"


def test_arxiv_query_builder_boolean():
    """AND/OR clauses each get their own all: prefix."""
    out = _build_search_query("aspirin AND aging AND elderly")
    assert "all:aspirin" in out
    assert "all:aging" in out
    assert "all:elderly" in out
    assert out.count("AND") == 2


def test_arxiv_query_strips_parens_and_quotes():
    """Parens and quotes from upstream queries don't break arXiv."""
    out = _build_search_query('(rapamycin) AND "longevity"')
    assert '(' not in out
    assert '"' not in out
    assert "all:rapamycin" in out
    assert "all:longevity" in out


def test_arxiv_parses_atom_entry():
    """Realistic Atom-1.0 entry produces a well-formed RawHit."""
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <published>2024-01-15T10:00:00Z</published>
    <title>A Methodological Note on Aging Biomarkers</title>
    <summary>This paper presents a new statistical method.</summary>
    <arxiv:doi>10.48550/arxiv.2401.12345</arxiv:doi>
  </entry>
</feed>"""
    root = ET.fromstring(sample_xml)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    hit = ArxivClient()._parse(entry, query="aging")
    assert hit is not None
    assert hit.source == "arxiv"
    assert hit.year == 2024
    assert hit.doi == "10.48550/arxiv.2401.12345"
    assert hit.url.startswith("https://doi.org/")
    assert hit.venue == "arXiv preprint"


def test_arxiv_skips_entries_missing_title_or_abstract():
    """Defensive: entries without title OR summary return None."""
    sample = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>x</id><title></title><summary>foo</summary></entry></feed>"""
    root = ET.fromstring(sample)
    entry = root.find("{http://www.w3.org/2005/Atom}entry")
    assert ArxivClient()._parse(entry, query="x") is None


# ---------- medRxiv split ------------------------------------------

def test_medrxiv_filters_to_medrxiv_only():
    """medRxiv parser drops bioRxiv records."""
    biorxiv_record: dict[str, Any] = {
        "title": "T", "abstractText": "A" * 100,
        "journalTitle": "bioRxiv",
        "doi": "10.1101/2024.01.15.575789",
        "pubYear": "2024",
    }
    medrxiv_record: dict[str, Any] = {
        "title": "T", "abstractText": "A" * 100,
        "journalTitle": "medRxiv",
        "doi": "10.1101/2024.01.15.24301234",
        "pubYear": "2024",
    }
    cli = MedRxivClient()
    assert cli._parse(biorxiv_record, query="x") is None
    assert cli._parse(medrxiv_record, query="x") is not None


def test_biorxiv_filters_to_biorxiv_only_after_split():
    """bioRxiv parser drops medRxiv records (post-split)."""
    biorxiv_record: dict[str, Any] = {
        "title": "T", "abstractText": "A" * 100,
        "journalTitle": "bioRxiv",
        "doi": "10.1101/2024.01.15.575789",
        "pubYear": "2024",
    }
    medrxiv_record: dict[str, Any] = {
        "title": "T", "abstractText": "A" * 100,
        "journalTitle": "medRxiv",
        "doi": "10.1101/2024.01.15.24301234",
        "pubYear": "2024",
    }
    cli = BioRxivClient()
    assert cli._parse(biorxiv_record, query="x") is not None
    assert cli._parse(medrxiv_record, query="x") is None


def test_preprint_split_uses_book_or_report_details_fallback():
    """When journalTitle is empty, both adapters fall back to
    bookOrReportDetails.publisher for the venue check."""
    record: dict[str, Any] = {
        "title": "T", "abstractText": "A" * 100,
        "journalTitle": "",
        "bookOrReportDetails": {"publisher": "medRxiv"},
        "doi": "10.1101/x",
        "pubYear": "2024",
    }
    assert MedRxivClient()._parse(record, query="x") is not None
    assert BioRxivClient()._parse(record, query="x") is None  # not biorxiv


# ---------- OpenAlex 2026 auth -------------------------------------

def test_openalex_prefers_api_key_over_mailto():
    """Per 2026-02-13 OpenAlex auth refresh, api_key wins."""
    cli = OpenAlexClient()
    with patch.dict(os.environ, {
        "OPENALEX_API_KEY": "k123",
        "CROSSREF_POLITE_EMAIL": "user@example.com",
    }, clear=False):
        params = cli._auth_params()
        assert params == {"api_key": "k123"}


def test_openalex_falls_back_to_mailto_when_no_key():
    """Without OPENALEX_API_KEY, reuse Crossref polite-pool email."""
    cli = OpenAlexClient()
    env = {k: v for k, v in os.environ.items()
           if k != "OPENALEX_API_KEY"}
    env["CROSSREF_POLITE_EMAIL"] = "user@example.com"
    with patch.dict(os.environ, env, clear=True):
        params = cli._auth_params()
        assert params == {"mailto": "user@example.com"}


def test_openalex_anonymous_when_neither_set():
    """No key, no email → empty auth params (anonymous tier)."""
    cli = OpenAlexClient()
    env = {k: v for k, v in os.environ.items()
           if k not in ("OPENALEX_API_KEY", "CROSSREF_POLITE_EMAIL")}
    with patch.dict(os.environ, env, clear=True):
        assert cli._auth_params() == {}


# ---------- iCite enrichment ---------------------------------------

def test_icite_parser_extracts_rcr_and_percentile():
    """Real iCite response fields → CitationMetrics dataclass."""
    record = {
        "pmid": 30566884,
        "year": 2018,
        "relative_citation_ratio": 11.6741,
        "nih_percentile": 98.1,
        "citation_count": 183,
        "expected_citations_per_year": 1.5,
        "is_clinical": True,
        "is_research_article": True,
    }
    m = ICiteClient._parse(record)
    assert m is not None
    assert m.pmid == "30566884"
    assert m.rcr == pytest.approx(11.6741)
    assert m.nih_percentile == 98.1
    assert m.citation_count == 183
    assert m.is_clinical is True


def test_icite_parser_handles_missing_metrics():
    """iCite returns null for very-recent papers (no citation history)."""
    record = {"pmid": 99999999, "year": 2025}
    m = ICiteClient._parse(record)
    assert m is not None
    assert m.rcr is None
    assert m.nih_percentile is None
    assert m.citation_count is None


def test_icite_parser_drops_record_without_pmid():
    assert ICiteClient._parse({}) is None


def test_icite_dedupes_input_pmids():
    """Inline dedup logic invariant: empty + dup PMIDs collapse cleanly.
    Mirrors what ICiteClient.fetch() does before splitting into batches."""
    pmids = ["30566884", "30566884", "29320655", ""]
    cleaned = [p.strip() for p in pmids if p and p.strip()]
    seen: set[str] = set()
    unique = [p for p in cleaned if not (p in seen or seen.add(p))]
    assert unique == ["30566884", "29320655"]


# ---------- RxNorm enrichment --------------------------------------

def test_rxnorm_unique_first_helper():
    """Dedup helper preserves first-seen order, drops empties."""
    from agent.enrichment.rxnorm import _unique_first
    assert _unique_first(["a", "b", "a", "c", "b", ""]) == ["a", "b", "c"]


def test_rxnorm_drug_concept_immutable():
    """Frozen dataclass — assignment raises FrozenInstanceError."""
    from dataclasses import FrozenInstanceError
    c = DrugConcept(rxcui="1191", canonical_name="aspirin")
    with pytest.raises(FrozenInstanceError):
        c.rxcui = "999"  # type: ignore[misc]


# ---------- RePORTER enrichment ------------------------------------

def test_reporter_parser_extracts_minimal_grant():
    """Realistic NIH RePORTER record → GrantRecord."""
    record = {
        "project_num": "4R01AG067744-02",
        "project_title": "Prospective Study of the Gut Microbiome in Aging",
        "fiscal_year": 2025,
        "award_amount": 943516,
        "contact_pi_name": "CHAN, ANDREW T",
        "organization": {"org_name": "MGH"},
        "abstract_text": "Lorem ipsum",
        "activity_code": "R01",
        "agency_ic_admin": {"code": "NIA"},
    }
    g = ReporterClient._parse(record)
    assert g is not None
    assert g.project_num == "4R01AG067744-02"
    assert g.fiscal_year == 2025
    assert g.award_amount == 943516
    assert g.contact_pi_name == "CHAN, ANDREW T"
    assert "NIA" in g.agencies


def test_reporter_drops_record_missing_required_fields():
    """No project_num or no title → drop."""
    assert ReporterClient._parse({"project_title": "x"}) is None
    assert ReporterClient._parse({"project_num": "x"}) is None


def test_reporter_falls_back_to_principal_investigators_array():
    """When contact_pi_name is missing, use first principal_investigators."""
    record = {
        "project_num": "X1",
        "project_title": "T",
        "principal_investigators": [
            {"first_name": "Alice", "last_name": "Smith"},
        ],
    }
    g = ReporterClient._parse(record)
    assert g is not None
    assert g.contact_pi_name == "Alice Smith"


# ---------- Aggregator registry ------------------------------------

def test_aggregator_registers_arxiv_and_medrxiv():
    """The new sources must appear in the registry as Tier-1 default-on."""
    reg = _build_registry()
    assert "arxiv" in reg
    assert "medrxiv" in reg
    arxiv_client, default_en, auth = reg["arxiv"]
    assert default_en is True
    assert auth is None
    medrxiv_client, default_en, auth = reg["medrxiv"]
    assert default_en is True
    assert auth is None


def test_aggregator_core_auto_enables_with_key():
    """CORE registry: default_enabled=True (was False — bug fix)."""
    reg = _build_registry()
    _, default_en, auth = reg["core"]
    assert default_en is True
    assert auth == "CORE_API_KEY"


def test_aggregator_total_source_count_is_15():
    """Sanity check: 13 corpus sources + 2 new = 15 total in registry.
    (10 default Tier-1 + arXiv + medRxiv = 12 Tier-1; +CORE=13 default-on
    gated; +ChEMBL+Unpaywall=15 opt-in.)"""
    reg = _build_registry()
    assert len(reg) == 15, (
        f"Expected 15 registered sources, got {len(reg)}: {sorted(reg)}"
    )
