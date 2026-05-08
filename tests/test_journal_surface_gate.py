"""Tests for the deterministic journal-surface gate."""
from __future__ import annotations

from agent.journal_surface_gate import (
    evaluate_journal_surface,
    is_publishable_qei_row,
)
from agent.results_table import EvidenceRow


def _words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def _paper(row: str) -> str:
    return (
        f"## Abstract\n\n{_words(150)}\n\n"
        f"## Introduction\n\n{_words(400)}\n\n"
        f"## Background\n\n{_words(300)}\n\n"
        "## Quantitative Evidence Index — topic\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        f"{row}\n\n"
        f"## Methods\n\n{_words(300)}\n\n"
        f"## Results\n\n{_words(500)}\n\n"
        f"## Cross-Domain Synthesis\n\n{_words(850)}\n\n"
        f"## Discussion\n\n{_words(800)}\n\n"
        f"## Limitations\n\n{_words(250)}\n\n"
        f"## Conclusion\n\n{_words(250)}\n"
    )


def test_qei_surface_gate_flags_endpoint_unit_mismatches():
    bad_rows = [
        "| Cheung 2024 | mortality | pooled | 2.86 mg/dL | mg/dL | — |",
        "| Brogi 2024 | blood pressure | control | 12 cm | cm | — |",
        "| Brogi 2024 | fasting glucose | control | 1.99 mmHg | mmHg | — |",
        "| Bülow 2023 | body mass index | protein | 38 kg | kg | — |",
        "| Demo 2024 | body mass index | protein | 65 years | years | — |",
        "| Moel 2025 | HbA1c | placebo | 5 mg | mg | — |",
        "| Dhanabalan 2022 | body weight | control | 100 mm | mm | — |",
        "| Wang 2019 | body weight | control | 1 mL | mL | — |",
        "| Smith 2024 | inflammation | pooled | 48 mL/min | mL/min | — |",
    ]
    for row in bad_rows:
        report = evaluate_journal_surface(_paper(row))
        assert not report.passed
        assert any("endpoint/unit mismatch" in i.detail for i in report.issues)


def test_qei_surface_gate_flags_empty_and_malformed_rows():
    report = evaluate_journal_surface(
        _paper("| So 2019_wit | body weight | protein | — | — | — |"),
    )
    assert not report.passed
    details = " ".join(i.detail for i in report.issues)
    assert "empty QEI row" in details
    assert "malformed study id" in details


def test_qei_surface_gate_flags_author_year_suffix_garbage():
    report = evaluate_journal_surface(
        _paper("| Palmer 2021ucos | fasting glucose | control | 7 mmol/L | mmol/L | — |"),
    )
    assert not report.passed
    assert any("malformed study id: Palmer 2021ucos" in i.detail for i in report.issues)


def test_qei_surface_gate_flags_malformed_row_shape():
    report = evaluate_journal_surface(
        _paper("| Kell 2026 | mTOR signaling | placebo | p<0.001 |"),
    )
    assert not report.passed
    assert any("malformed QEI row cell count" in i.detail for i in report.issues)


def test_placeholder_prose_blocks_journal_surface():
    paper = (
        "## Introduction\n\n"
        "This paper evaluates the topic through accepted receipts.\n\n"
        "## Methods\n\nMethods.\n"
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_conclusion_fallback_prose_blocks_journal_surface():
    paper = (
        "## Conclusion\n\n"
        "The conclusion is limited to claims that survive receipt "
        "qualification, source-context checks, and final audit gates.\n"
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_missing_cross_domain_blocks_journal_surface():
    paper = _paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    ).replace("## Cross-Domain Synthesis", "## Cross-Domain Summary")
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(
        i.code == "structure_surface"
        and "missing required section: Cross-Domain Synthesis" in i.detail
        for i in report.issues
    )


def test_valid_rows_pass_surface_gate():
    row = EvidenceRow(
        study_label="Smith 2024", endpoint="fasting glucose",
        arm="control", value="89 mg/dL", unit_or_type="mg/dL",
        statistic="—", citation="Smith 2024",
    )
    assert is_publishable_qei_row(row)
    report = evaluate_journal_surface(_paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    ))
    assert report.passed
