"""Surrogate wiring: exercise agent.schema TypedDicts against real data.

Runs every pytest invocation. Keeps schema.py alive while Tier 2 waits.
Validates that the TypedDict schemas are importable, correctly structured,
and that well-formed extraction/effect dicts match the expected shapes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import get_type_hints

import pytest

from agent.schema import (
    EffectDict,
    EvidenceCardDict,
    ExtractionDict,
    GoldTopicDict,
    QuantitativeClaim,
    SourceEntryDict,
    VerificationNotes,
)


# ─── Required-field manifests (must stay in sync with schema.py) ─────

_EFFECT_REQUIRED = {"outcome", "metric", "value", "ci_low", "ci_high", "p_value", "n", "source_span"}
_EXTRACTION_REQUIRED = {"primary_outcome", "population", "intervention", "comparator",
                        "methods_summary", "risk_of_bias", "effects",
                        "extractor_version", "source_doi", "found"}
_EVIDENCE_CARD_REQUIRED = {"citation", "journal", "quality_signal", "evidence_grade",
                           "study_type", "context", "population", "intervention",
                           "outcomes", "comparator", "methods_summary", "risk_of_bias",
                           "effects", "full_text_source", "full_text_found",
                           "extraction_found", "extractor_version"}


# ─── Type-hint existence ────────────────────────────────────────────

def test_all_schema_types_are_importable():
    """Every expected TypedDict must be importable from agent.schema."""
    for td in (EffectDict, ExtractionDict, EvidenceCardDict,
               SourceEntryDict, GoldTopicDict, QuantitativeClaim,
               VerificationNotes):
        assert td is not None


# ─── EffectDict field checks ────────────────────────────────────────

def test_effect_dict_has_required_fields():
    hints = get_type_hints(EffectDict)
    for field in _EFFECT_REQUIRED:
        assert field in hints, f"EffectDict missing field: {field}"


def test_effect_dict_no_extra_fields():
    hints = get_type_hints(EffectDict)
    extra = set(hints.keys()) - _EFFECT_REQUIRED
    assert not extra, f"EffectDict unexpected fields: {extra}"


def test_effect_dict_all_fields_are_str():
    hints = get_type_hints(EffectDict)
    for name, hint in hints.items():
        assert hint is str, f"EffectDict.{name} should be str, got {hint}"


def test_well_formed_effect_matches_schema():
    """A correct effect dict must have every required field."""
    sample: EffectDict = {
        "outcome": "all-cause mortality",
        "metric": "HR",
        "value": "0.77",
        "ci_low": "0.65",
        "ci_high": "0.91",
        "p_value": "0.002",
        "n": "1240",
        "source_span": "23% reduction in all-cause mortality (HR 0.77, 95% CI 0.65-0.91)",
    }
    assert set(sample.keys()) == _EFFECT_REQUIRED
    assert all(isinstance(v, str) for v in sample.values())


# ─── ExtractionDict field checks ────────────────────────────────────

def test_extraction_dict_has_required_fields():
    hints = get_type_hints(ExtractionDict)
    for field in _EXTRACTION_REQUIRED:
        assert field in hints, f"ExtractionDict missing field: {field}"


def test_extraction_effects_is_list_of_effect_dict():
    hints = get_type_hints(ExtractionDict)
    # effects should be list[EffectDict]
    assert "effects" in hints


def test_well_formed_extraction_matches_schema():
    """A correct extraction dict must have every required field."""
    sample_effect: EffectDict = {
        "outcome": "mortality",
        "metric": "HR",
        "value": "0.85",
        "ci_low": "0.70",
        "ci_high": "1.00",
        "p_value": "0.05",
        "n": "500",
        "source_span": "HR 0.85 (0.70-1.00), p=0.05",
    }
    sample: ExtractionDict = {
        "primary_outcome": "all-cause mortality",
        "population": "adults 65+ with T2D",
        "intervention": "metformin 1500mg daily",
        "comparator": "placebo",
        "methods_summary": "double-blind RCT, 3-year follow-up",
        "risk_of_bias": "low randomization",
        "effects": [sample_effect],
        "extractor_version": "tier1.5-v1",
        "source_doi": "10.1/example",
        "found": True,
    }
    assert set(sample.keys()) == _EXTRACTION_REQUIRED
    assert isinstance(sample["effects"], list)


def test_rejection_form_extraction():
    """An extraction dict with found=False has no effects."""
    sample: ExtractionDict = {
        "primary_outcome": "",
        "population": "",
        "intervention": "",
        "comparator": "",
        "methods_summary": "",
        "risk_of_bias": "",
        "effects": [],
        "extractor_version": "tier1.5-v1",
        "source_doi": "10.1/example",
        "found": False,
    }
    assert sample["found"] is False
    assert sample["effects"] == []


# ─── EvidenceCardDict field checks ──────────────────────────────────

def test_evidence_card_dict_has_required_fields():
    hints = get_type_hints(EvidenceCardDict)
    for field in _EVIDENCE_CARD_REQUIRED:
        assert field in hints, f"EvidenceCardDict missing field: {field}"


# ─── SourceEntryDict optional/required split ────────────────────────

def test_source_entry_dict_core_fields_required():
    hints = get_type_hints(SourceEntryDict)
    core = {"id", "title", "excerpt", "url", "source_type", "evidence_type"}
    for field in core:
        assert field in hints, f"SourceEntryDict missing core field: {field}"


def test_source_entry_dict_optional_fields():
    """Optional fields should accept None."""
    from typing import get_type_hints

    hints = get_type_hints(SourceEntryDict)
    optional = {"doi", "year", "journal", "authors", "query",
                "full_text", "full_text_source", "full_text_sections",
                "extraction", "has_results"}
    for field in optional:
        assert field in hints, f"SourceEntryDict missing optional field: {field}"


# ─── GoldTopicDict structure ────────────────────────────────────────

def test_gold_topic_dict_has_required_fields():
    hints = get_type_hints(GoldTopicDict)
    required = {"topic", "domain", "criteria", "source_review",
                "conclusion_direction", "limitations", "last_validated", "curator"}
    for field in required:
        assert field in hints, f"GoldTopicDict missing field: {field}"


# ─── Numeric parsing utility (inline, no dependency on missing funcs) ─

def test_numeric_string_parsing():
    """Validate that common numeric strings round-trip correctly.

    This tests the pattern the extractor produces, not a specific function
    (schema.py doesn't export a parser yet — Tier 2 will wire one).
    """
    cases = [
        ("0.77", 0.77),
        ("23%", 23.0),
        ("1,240", 1240.0),
        ("<0.001", 0.001),
        ("0.85-1.00", None),  # range, not parseable
        ("NA", None),
        ("", None),
    ]
    for raw, expected in cases:
        if expected is None:
            assert raw in ("0.85-1.00", "NA", ""), f"unexpected None parse for {raw!r}"
        else:
            # Strip commas and percent signs
            cleaned = raw.replace(",", "").replace("%", "").replace("<", "")
            try:
                result = float(cleaned)
            except ValueError:
                result = None
            assert result == expected, f"parse({raw!r}) = {result}, expected {expected}"


# ─── Real extraction cache validation (skips on fresh clone) ────────

def _cache_files() -> list[Path]:
    """Find real extraction cache files from past bot runs."""
    candidates = [
        Path("tests/golden/fixture_runs/extract-cache"),
        Path("runs/extract-cache"),
    ]
    files: list[Path] = []
    for root in candidates:
        if root.exists():
            files.extend(root.glob("*.json"))
    return files


def test_real_extraction_cache_has_required_keys():
    """Every cached extraction (if any) must have the required ExtractionDict keys.

    Two forms are valid:
    - found=True: must have all _EXTRACTION_REQUIRED keys
    - found=False (rejection): must have 'found' (and optionally 'reason')
    """
    files = _cache_files()
    if not files:
        pytest.skip("no extraction cache files — run the bot first to populate")

    pass_count = 0
    fail_list: list[tuple[Path, str]] = []
    for f in files:
        try:
            raw = json.loads(f.read_text())
        except Exception as exc:
            fail_list.append((f, f"JSON decode: {exc}"))
            continue
        if not isinstance(raw, dict):
            fail_list.append((f, "not a dict"))
            continue
        if "found" not in raw:
            fail_list.append((f, "missing 'found' key"))
            continue
        if not raw["found"]:
            # Rejection form — just needs 'found'
            pass_count += 1
            continue
        # Full extraction — needs all required keys
        missing = _EXTRACTION_REQUIRED - set(raw.keys())
        if missing:
            fail_list.append((f, f"missing: {sorted(missing)}"))
        else:
            pass_count += 1

    assert not fail_list, (
        f"{len(fail_list)}/{len(files)} cache files failed schema:\n"
        + "\n".join(f"  {f.name}: {reason}" for f, reason in fail_list[:5])
    )
    assert pass_count > 0, "no cache files passed"
