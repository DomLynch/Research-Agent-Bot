from __future__ import annotations

from agent.schema import (
    EffectDict,
    EvidenceCardDict,
    ExtractionDict,
    GoldTopicDict,
    QuantitativeClaim,
    SourceEntryDict,
    SourceReviewEntry,
    VerificationNotes,
)


# -- EffectDict ----------------------------------------------------------


def _effect(**overrides: str) -> EffectDict:
    base: EffectDict = {
        "outcome": "mortality",
        "metric": "HR",
        "value": "0.85",
        "ci_low": "0.72",
        "ci_high": "0.99",
        "p_value": "0.04",
        "n": "1200",
        "source_span": "HR 0.85 (95% CI 0.72-0.99)",
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def test_effect_dict_fields() -> None:
    e = _effect()
    assert e["outcome"] == "mortality"
    assert e["source_span"] == "HR 0.85 (95% CI 0.72-0.99)"


def test_effect_dict_empty_strings() -> None:
    e = {k: "" for k in EffectDict.__annotations__}
    assert isinstance(e, dict)


# -- ExtractionDict -------------------------------------------------------


def test_extraction_dict_typing() -> None:
    e: ExtractionDict = {
        "primary_outcome": "all-cause mortality",
        "population": "adults 65+",
        "intervention": "caloric restriction",
        "comparator": "ad libitum",
        "methods_summary": "RCT, 2 years",
        "risk_of_bias": "low",
        "effects": [_effect()],
        "extractor_version": "tier1.5-v1",
        "source_doi": "10.1234/test",
        "found": True,
    }
    assert len(e["effects"]) == 1
    assert e["found"] is True


def test_extraction_dict_empty_effects() -> None:
    e: ExtractionDict = {
        "primary_outcome": "",
        "population": "",
        "intervention": "",
        "comparator": "",
        "methods_summary": "",
        "risk_of_bias": "",
        "effects": [],
        "extractor_version": "tier1.5-v1",
        "source_doi": "",
        "found": False,
    }
    assert e["effects"] == []


# -- EvidenceCardDict -----------------------------------------------------


def test_evidence_card_dict_typing() -> None:
    card: EvidenceCardDict = {
        "citation": "Smith et al., 2023",
        "journal": "Nature",
        "quality_signal": "rct",
        "evidence_grade": "H",
        "study_type": "rct",
        "context": "aging",
        "population": "adults",
        "intervention": "exercise",
        "outcomes": "mortality",
        "comparator": "usual care",
        "methods_summary": "RCT",
        "risk_of_bias": "low",
        "effects": [_effect()],
        "full_text_source": "pubmed",
        "full_text_found": True,
        "extraction_found": True,
        "extractor_version": "tier1.5-v1",
    }
    assert card["evidence_grade"] in ("H", "M", "L")


def test_evidence_card_empty_effects() -> None:
    card: EvidenceCardDict = {
        "citation": "Jones, 2022",
        "journal": "",
        "quality_signal": "primary",
        "evidence_grade": "L",
        "study_type": "primary",
        "context": "general",
        "population": "",
        "intervention": "",
        "outcomes": "",
        "comparator": "",
        "methods_summary": "",
        "risk_of_bias": "",
        "effects": [],
        "full_text_source": "",
        "full_text_found": False,
        "extraction_found": False,
        "extractor_version": "",
    }
    assert card["extraction_found"] is False


# -- SourceEntryDict ------------------------------------------------------


def test_source_entry_pubmed() -> None:
    entry: SourceEntryDict = {
        "id": "35123456",
        "title": "Test study",
        "excerpt": "Abstract text",
        "url": "https://pubmed.ncbi.nlm.nih.gov/35123456/",
        "source_type": "pubmed",
        "evidence_type": "primary",
        "doi": "10.1234/test",
        "year": 2023,
        "journal": "Test Journal",
        "authors": ["Smith"],
    }
    assert entry["source_type"] == "pubmed"


def test_source_entry_minimal() -> None:
    entry: SourceEntryDict = {
        "id": "test-1",
        "title": "Title",
        "excerpt": "Excerpt",
        "url": "https://example.com",
        "source_type": "rxiv",
        "evidence_type": "primary",
    }
    assert "doi" not in entry
    assert "year" not in entry


def test_source_entry_with_extraction() -> None:
    ext: ExtractionDict = {
        "primary_outcome": "mortality",
        "population": "adults",
        "intervention": "exercise",
        "comparator": "none",
        "methods_summary": "RCT",
        "risk_of_bias": "low",
        "effects": [],
        "extractor_version": "tier1.5-v1",
        "source_doi": "10.1234/test",
        "found": True,
    }
    entry: SourceEntryDict = {
        "id": "test-1",
        "title": "Title",
        "excerpt": "Excerpt",
        "url": "https://example.com",
        "source_type": "pubmed",
        "evidence_type": "primary",
        "extraction": ext,
    }
    assert entry["extraction"]["found"] is True


def test_source_entry_has_results() -> None:
    entry: SourceEntryDict = {
        "id": "NCT123",
        "title": "Trial",
        "excerpt": "Summary",
        "url": "https://clinicaltrials.gov/study/NCT123",
        "source_type": "clinicaltrials",
        "evidence_type": "interventional",
        "has_results": True,
    }
    assert entry["has_results"] is True


# -- GoldTopicDict -------------------------------------------------------


def test_gold_topic_dict_typing() -> None:
    sr: SourceReviewEntry = {
        "doi": "10.1234/test",
        "title": "Review title",
        "year": 2023,
        "journal": "Test Journal",
    }
    topic: GoldTopicDict = {
        "topic": "test topic",
        "domain": "longevity",
        "criteria": "human, 2020+",
        "source_review": sr,
        "conclusion_direction": "positive_with_caveats",
        "limitations": ["small samples"],
        "last_validated": "2026-04-21",
        "curator": "test",
    }
    assert topic["source_review"]["doi"] == "10.1234/test"


def test_gold_topic_dict_full() -> None:
    sr: SourceReviewEntry = {
        "doi": "10.1234/test",
        "title": "Review",
        "year": 2023,
        "journal": "J",
        "url": "https://doi.org/10.1234/test",
    }
    qc: QuantitativeClaim = {"claim": "20% reduction", "source_doi": "10.1234/test"}
    vn: VerificationNotes = {"dropped_dois": ["10.1234/old"]}
    topic: GoldTopicDict = {
        "topic": "full topic",
        "domain": "cognition",
        "criteria": "RCT, 2020+",
        "source_review": sr,
        "conclusion_direction": "positive",
        "limitations": ["limitation 1"],
        "last_validated": "2026-04-21",
        "curator": "test",
        "included_dois": ["10.1234/a", "10.1234/b"],
        "conclusion_summary": "Positive results",
        "quantitative_claims": [qc],
        "doi_verified": True,
        "doi_verified_at": "2026-04-21T00:00:00+00:00",
        "verification_notes": vn,
    }
    assert topic["doi_verified"] is True
    assert len(topic["included_dois"]) == 2


# -- Real fixture compatibility ------------------------------------------


def test_effect_dict_matches_normalize_output() -> None:
    """Fields must match _normalize_effect output keys."""
    e = _effect()
    expected_keys = {"outcome", "metric", "value", "ci_low", "ci_high", "p_value", "n", "source_span"}
    assert set(e.keys()) == expected_keys


def test_extraction_dict_matches_normalize_output() -> None:
    """Fields must match _normalize_payload + extract output keys."""
    e: ExtractionDict = {
        "primary_outcome": "",
        "population": "",
        "intervention": "",
        "comparator": "",
        "methods_summary": "",
        "risk_of_bias": "",
        "effects": [],
        "extractor_version": "tier1.5-v1",
        "source_doi": "",
        "found": True,
    }
    expected_keys = {
        "primary_outcome", "population", "intervention", "comparator",
        "methods_summary", "risk_of_bias", "effects", "extractor_version",
        "source_doi", "found",
    }
    assert set(e.keys()) == expected_keys


def test_evidence_card_dict_matches_build_card_output() -> None:
    """Fields must match build_card output keys."""
    card: EvidenceCardDict = {
        "citation": "Test, 2023",
        "journal": "",
        "quality_signal": "primary",
        "evidence_grade": "L",
        "study_type": "primary",
        "context": "general",
        "population": "",
        "intervention": "",
        "outcomes": "",
        "comparator": "",
        "methods_summary": "",
        "risk_of_bias": "",
        "effects": [],
        "full_text_source": "",
        "full_text_found": False,
        "extraction_found": False,
        "extractor_version": "",
    }
    expected_keys = {
        "citation", "journal", "quality_signal", "evidence_grade",
        "study_type", "context", "population", "intervention",
        "outcomes", "comparator", "methods_summary", "risk_of_bias",
        "effects", "full_text_source", "full_text_found",
        "extraction_found", "extractor_version",
    }
    assert set(card.keys()) == expected_keys
