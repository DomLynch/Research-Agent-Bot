"""Tests for the Phase 6 template-language gate adapter."""
from __future__ import annotations

import json

import pytest

from agent.template_gate_adapter import (
    TemplateGateReport,
    evaluate_template_gate,
)


# ---- Pass cases (clean papers) -------------------------------------------


def test_clean_paper_does_not_block() -> None:
    text = "Rapamycin extends mouse lifespan by 14% (Harrison 2009)."
    r = evaluate_template_gate(text)
    assert r.template_language_blocking is False
    assert r.total_hits == 0
    assert r.p1_count == 0
    assert r.p2_count == 0


def test_clean_paper_returns_template_gate_report() -> None:
    r = evaluate_template_gate("Body sentence.")
    assert isinstance(r, TemplateGateReport)


def test_clean_paper_markdown_report_says_no_hits() -> None:
    r = evaluate_template_gate("Body sentence.")
    assert "_No template-language hits detected._" in r.markdown_report


# ---- Block cases (dirty papers) ------------------------------------------


def test_p1_unsupported_authority_blocks() -> None:
    r = evaluate_template_gate("It is clear that rapamycin works.")
    assert r.template_language_blocking is True
    assert r.p1_count >= 1


def test_p2_generic_cliche_blocks() -> None:
    r = evaluate_template_gate("Further research is needed.")
    assert r.template_language_blocking is True
    assert r.p2_count >= 1


def test_p2_ai_summary_tell_blocks() -> None:
    r = evaluate_template_gate("In conclusion, rapamycin shows promise.")
    assert r.template_language_blocking is True


def test_vague_limitation_without_specifics_blocks() -> None:
    r = evaluate_template_gate("The evidence base is limited.")
    assert r.template_language_blocking is True


def test_vague_limitation_with_specifics_does_not_block() -> None:
    r = evaluate_template_gate(
        "The evidence base is limited to 3 RCTs with n<100 over 12 months."
    )
    assert r.template_language_blocking is False


def test_multiple_hits_aggregated_correctly() -> None:
    text = (
        "It is clear that the drug works.\n"
        "Further research is needed.\n"
        "More studies are needed.\n"
    )
    r = evaluate_template_gate(text)
    assert r.p1_count == 1
    assert r.p2_count == 2
    assert r.total_hits == 3


# ---- Section-skip behaviour preserved ------------------------------------


def test_references_section_excluded() -> None:
    text = (
        "Body sentence with no hits.\n\n"
        "## References\n\n"
        "It is clear that this is in references.\n"
    )
    r = evaluate_template_gate(text)
    assert r.total_hits == 0


def test_code_fence_excluded() -> None:
    text = (
        "Body sentence.\n"
        "```\n"
        "further research is needed in this code\n"
        "It is clear that\n"
        "```\n"
    )
    r = evaluate_template_gate(text)
    assert r.total_hits == 0


def test_table_rows_excluded() -> None:
    text = (
        "Body sentence.\n"
        "| further research is needed | x |\n"
        "| more studies are needed | y |\n"
    )
    r = evaluate_template_gate(text)
    assert r.total_hits == 0


# ---- Markdown report -----------------------------------------------------


def test_markdown_report_includes_source_label() -> None:
    r = evaluate_template_gate("It is clear that.", source="full_paper.md")
    assert "# Template-Language Gate — full_paper.md" in r.markdown_report


def test_markdown_report_includes_severity_breakdown() -> None:
    r = evaluate_template_gate(
        "It is clear that.\nFurther research is needed."
    )
    assert "| P1 | 1 |" in r.markdown_report
    assert "| P2 | 1 |" in r.markdown_report


def test_markdown_report_includes_per_hit_table() -> None:
    r = evaluate_template_gate("It is clear that the drug works.")
    assert "| Line | Severity | Category | Phrase | Sentence |" in r.markdown_report
    assert "P1" in r.markdown_report
    assert "unsupported_authority" in r.markdown_report


# ---- JSON report ---------------------------------------------------------


def test_json_report_parses() -> None:
    r = evaluate_template_gate("It is clear that.")
    data = json.loads(r.json_report)
    assert isinstance(data, dict)
    assert "source" in data and "summary" in data and "hits" in data


def test_json_report_summary_shape() -> None:
    r = evaluate_template_gate(
        "It is clear that.\nFurther research is needed.",
        source="paper.md",
    )
    data = json.loads(r.json_report)
    assert data["source"] == "paper.md"
    assert data["summary"]["total_hits"] == 2
    assert data["summary"]["blocking"] is True
    assert data["summary"]["by_severity"]["P1"] == 1
    assert data["summary"]["by_severity"]["P2"] == 1


def test_json_report_includes_hit_details() -> None:
    r = evaluate_template_gate("It is clear that.")
    data = json.loads(r.json_report)
    assert len(data["hits"]) == 1
    assert data["hits"][0]["category"] == "unsupported_authority"
    assert data["hits"][0]["severity"] == "P1"
    assert "line_number" in data["hits"][0]


# ---- Validation + determinism --------------------------------------------


def test_non_string_input_rejected() -> None:
    with pytest.raises(TypeError, match="paper_text"):
        evaluate_template_gate(123)  # type: ignore[arg-type]


def test_empty_string_handled_cleanly() -> None:
    r = evaluate_template_gate("")
    assert r.total_hits == 0
    assert r.template_language_blocking is False


def test_determinism_same_input_same_output() -> None:
    text = "It is clear that.\nFurther research is needed."
    r1 = evaluate_template_gate(text, source="x")
    r2 = evaluate_template_gate(text, source="x")
    assert r1.markdown_report == r2.markdown_report
    assert r1.json_report == r2.json_report
    assert r1.hits == r2.hits


def test_hits_are_frozen_tuple() -> None:
    r = evaluate_template_gate("It is clear that.")
    assert isinstance(r.hits, tuple)


# ---- Wiring contract: connects to final_gate -----------------------------


def test_blocking_flag_wires_into_gate_inputs_signature() -> None:
    """The bool exposes exactly the field name GateInputs.template_language_blocking expects."""
    r = evaluate_template_gate("It is clear that.")
    # Exposed attribute name matches the GateInputs field name verbatim
    assert hasattr(r, "template_language_blocking")
    assert isinstance(r.template_language_blocking, bool)
