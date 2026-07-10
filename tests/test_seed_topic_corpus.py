"""Tests for generic topic corpus seeding helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import seed_topic_corpus as seed  # type: ignore[import-not-found]  # noqa: E402


def test_abstract_fallback_writes_paper_sections_schema(tmp_path):
    hit = SimpleNamespace(
        title="mTOR inhibition improves immune function in the elderly",
        abstract=(
            "In older adults, mTOR inhibition improved immune response "
            "after vaccination in a randomized trial."
        ),
        url="",
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


def test_hit_specific_to_topic_uses_source_gate_aliases() -> None:
    pack = cast(Any, SimpleNamespace(
        aliases=(
            "plasma proteomic age clocks",
            "plasma proteomics",
            "proteomic aging clock",
        ),
    ))
    drift_hit = SimpleNamespace(
        title="Plasma Proteomics Identifies Potential Pancreatic Cancer Risk Indicators in Type 2 Diabetes",
        abstract="",
        venue="",
    )
    direct_hit = SimpleNamespace(
        title="A plasma proteomic age clock for multimorbidity risk in older adults",
        abstract="",
        venue="",
    )

    assert not seed._hit_specific_to_topic("plasma_proteomic_age_clocks", pack, drift_hit)
    assert seed._hit_specific_to_topic("plasma_proteomic_age_clocks", pack, direct_hit)


def test_extraction_rank_prioritizes_core_clinical_evidence() -> None:
    def entry(pool: str, score: int, sources: int, year: int, title: str) -> Any:
        return SimpleNamespace(
            pool=pool,
            classification=SimpleNamespace(score=score),
            hit=SimpleNamespace(n_sources=sources, year=year, title=title),
        )

    rows = [
        entry("background", 90, 8, 2026, "Background"),
        entry("adjacent", 95, 7, 2026, "Adjacent"),
        entry("core", 70, 1, 2020, "Core"),
    ]

    assert [row.pool for row in sorted(rows, key=seed._extraction_entry_rank)] == [
        "core", "adjacent", "background",
    ]


def test_docling_fallback_can_replace_abstract_fallback(tmp_path, monkeypatch):
    hit = SimpleNamespace(
        title="Closed paper with source PDF",
        abstract="",
        url="https://example.test/paper.pdf",
        year=2024,
        venue="Example",
        doi="10.1/example",
        pmid="123",
    )

    def fake_docling(**kwargs):
        assert kwargs["source_uri"] == hit.url
        return {"status": "passed", "paper_id": kwargs["paper_id"]}

    monkeypatch.setattr(seed._optional_adapters, "write_docling_paper_sections", fake_docling)
    assert seed._write_abstract_fallback(hit, tmp_path, reason="fulltext_unavailable") == "PMID123_closed_paper_with_source_pdf"
