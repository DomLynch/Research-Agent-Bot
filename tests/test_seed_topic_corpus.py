"""Tests for generic topic corpus seeding helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import seed_topic_corpus as seed  # noqa: E402


def test_abstract_fallback_writes_paper_sections_schema(tmp_path):
    hit = SimpleNamespace(
        title="mTOR inhibition improves immune function in the elderly",
        abstract=(
            "In older adults, mTOR inhibition improved immune response "
            "after vaccination in a randomized trial."
        ),
        url="https://example.test/paper",
        year=2014,
        venue="Science Translational Medicine",
        doi="10.1126/scitranslmed.3009892",
        pmid="25540326",
    )
    paper_id = seed._write_abstract_fallback(
        hit, tmp_path, reason="no_pmcid",
    )

    assert paper_id == (
        "PMID25540326_mtor_inhibition_improves_immune_function_in_the_elderly"
    )
    doc = json.loads((tmp_path / f"{paper_id}.paper_sections.json").read_text())
    assert doc["paper_id"] == paper_id
    assert doc["doi"] == "10.1126/scitranslmed.3009892"
    assert doc["sections"]["abstract"].startswith("In older adults")
    assert doc["extraction_quality"]["section_coverage"] == ["abstract"]
    assert "abstract-fallback:no_pmcid" in doc["extraction_quality"]["warnings"]


def test_abstract_fallback_preserves_resolved_authors_for_citations(tmp_path):
    hit = SimpleNamespace(
        title="mTOR inhibition improves immune function in the elderly",
        abstract="RAD001 enhanced vaccine response by about 20%.",
        url="",
        year=2014,
        venue="",
        doi="10.1126/scitranslmed.3009892",
        pmid="25540326",
    )
    paper_id = seed._write_abstract_fallback(
        hit, tmp_path, reason="no_pmcid",
        resolved_meta={
            "authors": ["JB Mannick", "G Del Giudice"],
            "journal": "Science Translational Medicine",
            "year": 2014,
        },
    )
    doc = json.loads((tmp_path / f"{paper_id}.paper_sections.json").read_text())
    assert doc["authors"][0] == "JB Mannick"
    assert doc["journal"] == "Science Translational Medicine"


def test_abstract_fallback_uses_resolved_abstract_when_hit_is_title_only(
    tmp_path,
):
    hit = SimpleNamespace(
        title="Closed-access landmark cardiovascular outcomes trial",
        abstract="",
        url="",
        year=2016,
        venue="",
        doi="10.1056/example",
        pmid="12345678",
    )
    paper_id = seed._write_abstract_fallback(
        hit, tmp_path, reason="no_pmcid",
        resolved_meta={
            "abstract": "Statin therapy reduced cardiovascular events in older adults.",
            "authors": ["A Trialist"],
            "journal": "Example Journal",
            "year": 2016,
        },
    )
    assert paper_id is not None
    doc = json.loads((tmp_path / f"{paper_id}.paper_sections.json").read_text())
    assert doc["sections"]["abstract"].startswith("Statin therapy reduced")
    assert "abstract-fallback:no_pmcid" in doc["extraction_quality"]["warnings"]


def test_europepmc_author_string_normalizes_surname_last_shape():
    authors = seed._authors_from_europepmc_result({
        "authorString": "Mannick JB, Del Giudice G, Lattanzi M",
    })
    assert authors[:2] == ["JB Mannick", "G Del Giudice"]


def test_abstract_fallback_skips_hits_without_abstract(tmp_path):
    hit = SimpleNamespace(
        title="Closed paper",
        abstract="",
        url="",
        year=None,
        venue="",
        doi="",
        pmid="",
    )
    assert seed._write_abstract_fallback(hit, tmp_path, reason="x") is None
    assert list(tmp_path.iterdir()) == []
