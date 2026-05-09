"""Tests for the Phase 3 framework-section adapter."""
from __future__ import annotations

import pytest

from agent.framework_section import (
    SectionConfig,
    build_framework_section,
    enrich_receipts_with_registry,
    render_engagement_section,
    render_engagement_summary_line,
    render_framework_paragraph,
)
from agent.field_engagement import FrameworkEngagement, evaluate_engagement


# ---- enrich_receipts_with_registry ----------------------------------------


def test_enrich_attaches_body_citation_from_registry() -> None:
    receipts = [{"receipt_id": "PMC1_x", "outcome_class": "immune"}]
    registry = {"PMC1_x": {"body_citation": "Mannick 2018"}}
    out = enrich_receipts_with_registry(receipts, registry)
    assert out[0]["citation_token"] == "Mannick 2018"


def test_enrich_preserves_existing_citation_token() -> None:
    receipts = [{"receipt_id": "X", "citation_token": "Already 2024"}]
    registry = {"X": {"body_citation": "Different 2026"}}
    out = enrich_receipts_with_registry(receipts, registry)
    assert out[0]["citation_token"] == "Already 2024"


def test_enrich_passes_through_when_registry_missing_id() -> None:
    receipts = [{"receipt_id": "X"}]
    out = enrich_receipts_with_registry(receipts, {})
    assert "citation_token" not in out[0]
    out2 = enrich_receipts_with_registry(receipts, None)
    assert "citation_token" not in out2[0]


def test_enrich_returns_copies_not_mutations() -> None:
    receipts = [{"receipt_id": "X"}]
    registry = {"X": {"body_citation": "Ref 2024"}}
    enrich_receipts_with_registry(receipts, registry)
    assert receipts[0].get("citation_token") is None  # original untouched


# ---- render_framework_paragraph -------------------------------------------


def test_paragraph_for_support_states_support() -> None:
    e = FrameworkEngagement(
        framework_name="Mannick", status="support",
        matched_receipts=("PMC_Mannick_2018",), rationale="ok",
    )
    para = render_framework_paragraph(e)
    assert "supports the Mannick framework" in para
    assert "PMC_Mannick_2018" in para


def test_paragraph_for_insufficient_marks_provisional() -> None:
    e = FrameworkEngagement("Lamming", "insufficient", rationale="no anchor")
    para = render_framework_paragraph(e)
    assert para.startswith("[provisional]")
    assert "does not yet evaluate" in para


def test_paragraph_includes_background_refs_when_present() -> None:
    e = FrameworkEngagement(
        "Lopez-Otin", "support",
        matched_receipts=("R1",),
        matched_background_refs=("Lopez-Otin 2013",),
        rationale="ok",
    )
    para = render_framework_paragraph(e)
    assert "Lopez-Otin 2013" in para
    assert "background-literature surface" in para


# ---- render_engagement_summary_line ---------------------------------------


def test_summary_line_counts_match() -> None:
    engagements = [
        FrameworkEngagement("A", "support", rationale="x"),
        FrameworkEngagement("B", "challenge", rationale="x"),
        FrameworkEngagement("C", "extends", rationale="x"),
        FrameworkEngagement("D", "insufficient", rationale="x"),
        FrameworkEngagement("E", "insufficient", rationale="x"),
    ]
    line = render_engagement_summary_line(engagements)
    assert "5 evaluated framework(s)" in line
    assert "1 support" in line
    assert "1 challenge" in line
    assert "1 extends" in line
    assert "2 insufficient" in line


# ---- render_engagement_section --------------------------------------------


def test_section_renders_summary_line_and_subsections() -> None:
    engagements = [
        FrameworkEngagement("Mannick", "support",
            matched_receipts=("R1",), rationale="ok"),
        FrameworkEngagement("Lamming", "insufficient", rationale="no anchor"),
    ]
    md = render_engagement_section(engagements)
    assert "## Engagement with Established Frameworks" in md
    assert "2 evaluated framework(s)" in md
    assert "### Mannick" in md
    assert "### Lamming" in md


def test_section_with_empty_engagements() -> None:
    md = render_engagement_section([])
    assert "_No framework engagements computed._" in md


def test_section_suppresses_insufficient_when_configured() -> None:
    engagements = [
        FrameworkEngagement("Mannick", "support",
            matched_receipts=("R1",), rationale="ok"),
        FrameworkEngagement("Lamming", "insufficient", rationale="no anchor"),
    ]
    md = render_engagement_section(
        engagements, config=SectionConfig(include_insufficient=False)
    )
    assert "### Mannick" in md
    assert "### Lamming" not in md


def test_section_only_insufficient_with_suppress_flag_emits_stub() -> None:
    engagements = [
        FrameworkEngagement("Mannick", "insufficient", rationale="x"),
    ]
    md = render_engagement_section(
        engagements, config=SectionConfig(include_insufficient=False)
    )
    assert "section suppressed by config" in md


def test_heading_level_config() -> None:
    engagements = [
        FrameworkEngagement("Mannick", "support",
            matched_receipts=("R1",), rationale="ok"),
    ]
    md = render_engagement_section(
        engagements, config=SectionConfig(heading_level=3)
    )
    assert "### Engagement with Established Frameworks" in md
    assert "#### Mannick" in md


def test_section_config_heading_level_validation() -> None:
    with pytest.raises(ValueError, match="heading_level"):
        SectionConfig(heading_level=5)
    with pytest.raises(ValueError, match="heading_level"):
        SectionConfig(heading_level=0)


def test_section_respects_explicit_framework_order() -> None:
    engagements = [
        FrameworkEngagement("Mannick", "support",
            matched_receipts=("R1",), rationale="x"),
        FrameworkEngagement("Lopez-Otin", "support",
            matched_receipts=("R2",), rationale="x"),
    ]
    md = render_engagement_section(
        engagements,
        config=SectionConfig(framework_order=("Lopez-Otin", "Mannick")),
    )
    assert md.index("### Lopez-Otin") < md.index("### Mannick")


# ---- build_framework_section (end-to-end) ---------------------------------


def test_build_section_uses_default_5_frameworks() -> None:
    md = build_framework_section([])
    assert "Of the 5 evaluated framework(s)" in md
    for name in ("Mannick", "Lamming", "Kennedy", "Kaeberlein", "Lopez-Otin"):
        assert f"### {name}" in md


def test_build_section_aaa4_shape_returns_all_insufficient_honestly() -> None:
    """Receipt has no anchor-author hint → no fabricated framework support."""
    receipts = [
        {"receipt_id": "PMC12074816", "outcome_class": "cardiometabolic",
         "effect_direction": "null"},
    ]
    registry = {"PMC12074816": {"body_citation": "Moel 2025"}}
    md = build_framework_section(receipts, citation_registry=registry)
    # Honest finding: Moel is not a framework anchor
    assert "5 insufficient" in md
    assert "supports the Mannick" not in md
    assert "supports the Lamming" not in md


def test_build_section_with_mannick_anchor_receipt_supports_mannick() -> None:
    receipts = [
        {"receipt_id": "PMC_PIE", "citation_token": "Mannick 2018",
         "outcome_class": "immune", "effect_direction": "positive"},
    ]
    md = build_framework_section(receipts)
    assert "supports the Mannick framework" in md
    assert "PMC_PIE" in md


def test_build_section_uses_registry_when_receipt_lacks_citation_token() -> None:
    receipts = [
        {"receipt_id": "PMC_PIE",
         "outcome_class": "immune", "effect_direction": "positive"},
    ]
    registry = {"PMC_PIE": {"body_citation": "Mannick 2018"}}
    md = build_framework_section(receipts, citation_registry=registry)
    assert "supports the Mannick framework" in md


def test_build_section_extends_when_primary_plus_adjacent_match() -> None:
    """Mannick primary domain = immune; adjacent = cardiometabolic."""
    receipts = [
        {"receipt_id": "R1", "citation_token": "Mannick 2018",
         "outcome_class": "immune", "effect_direction": "positive"},
        {"receipt_id": "R2", "citation_token": "Mannick 2014",
         "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ]
    md = build_framework_section(receipts)
    assert "extends the Mannick framework" in md


def test_build_section_does_not_invoke_llm() -> None:
    """Smoke: deterministic — same input must produce same output."""
    receipts = [
        {"receipt_id": "R1", "citation_token": "Mannick 2018",
         "outcome_class": "immune", "effect_direction": "positive"},
    ]
    md1 = build_framework_section(receipts)
    md2 = build_framework_section(receipts)
    assert md1 == md2


def test_build_section_consistent_with_evaluate_engagement_path() -> None:
    """The adapter must produce the same engagements as direct evaluate_engagement."""
    receipts = [
        {"receipt_id": "R1", "citation_token": "Lamming 2012",
         "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ]
    md = build_framework_section(receipts)
    direct = evaluate_engagement(receipts=receipts)
    by_name = {e.framework_name: e for e in direct}
    assert by_name["Lamming"].status == "challenge"
    assert "challenges the Lamming framework" in md
