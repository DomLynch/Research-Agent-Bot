"""Tests for the deterministic journal-surface gate."""
from __future__ import annotations

from agent.journal_surface_gate import (
    evaluate_journal_surface,
    is_publishable_qei_row,
)
from agent.results_table import EvidenceRow


def _words(n: int, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def _paper(row: str) -> str:
    return (
        f"## Abstract\n\n{_words(150, 'abstract')}\n\n"
        f"## Introduction\n\n{_words(400, 'intro')}\n\n"
        f"## Background\n\n{_words(300, 'background')}\n\n"
        "## Quantitative Evidence Index — topic\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        f"{row}\n\n"
        f"## Methods\n\n{_words(300, 'methods')}\n\n"
        f"## Results\n\n{_words(500, 'results')}\n\n"
        f"## Cross-Domain Synthesis\n\n{_words(850, 'cross')}\n\n"
        f"## Discussion\n\n{_words(800, 'discussion')}\n\n"
        f"## Limitations\n\n{_words(250, 'limits')}\n\n"
        f"## Conclusion\n\n{_words(250, 'conclusion')}\n\n"
        "## References\n\n- Smith 2024.\n"
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


def test_qei_surface_gate_flags_malformed_zero_numeric_artifacts():
    report = evaluate_journal_surface(
        _paper("| Singh 2022 | dose | treatment | 000 mg/day | mg/day | — |"),
    )
    assert not report.passed
    assert any("malformed numeric artifact" in i.detail for i in report.issues)


def test_surface_gate_allows_thousands_separated_doses():
    report = evaluate_journal_surface(
        _paper("| Singh 2022 | dose | treatment | 1,000 mg/day | mg/day | — |"),
    )
    assert not any("malformed numeric artifact" in i.detail for i in report.issues)


def test_surface_gate_flags_consecutive_duplicate_qei_headings():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "## Quantitative Evidence Index — topic\n\n",
        (
            "## Quantitative Evidence Index — Urolithin A\n\n"
            "## Quantitative Evidence Index — urolithin_a\n\n"
        ),
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "duplicate_heading" for i in report.issues)


def test_surface_gate_flags_public_topic_slug_artifacts():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("background1", "urolithin_a", 1)
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "topic_slug_artifact" for i in report.issues)


def test_malformed_qei_row_in_appendix_does_not_block_public_body():
    paper = (
        _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
        + "\n\n## Publication Appendix\n\n"
        "## Quantitative Evidence Index\n\n"
        "| Kell 2026 | mTOR signaling | placebo | p<0.001 |\n"
    )
    report = evaluate_journal_surface(paper)
    assert report.passed


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


def test_bounded_conclusion_backfill_blocks_journal_surface():
    paper = (
        "## Conclusion\n\n"
        "The synthesis supports a bounded conclusion: the topic has enough "
        "receipt-traced evidence to justify structured interpretation, but "
        "the evidence should be read through its tiered profile.\n"
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_validation_contract_meta_prose_blocks_journal_surface():
    paper = (
        "## Discussion\n\n"
        "The interpretation remains cautious when section generation "
        "cannot satisfy the validation contract.\n"
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_llm_meta_slogans_block_journal_surface():
    paper = (
        "## Methods\n\n"
        "The load-bearing principle is LLM proposes, code disposes, "
        "with no LLM authorship.\n"
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_appendix_meta_language_does_not_block_body_surface():
    paper = (
        _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
        + "\n\n## Data and Code Availability\n\n"
        "The audit appendix can describe that LLM proposes, code disposes.\n"
    )
    report = evaluate_journal_surface(paper)
    assert report.passed


def test_public_template_meta_blocks_journal_surface():
    paper = (
        "## Methods\n\n"
        "This synthesis was produced by the v0.6 pipeline "
        "(submission `synthesis-demo`). Patches are auto-applied.\n"
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "template_meta" for i in report.issues)


def test_public_artifact_language_blocks_journal_surface():
    paper = (
        "## Discussion\n\n"
        "[D1_inferential_bridge | confidence=medium]\n\n"
        "The accepted receipt graph is described by the manifest, tension "
        "matrix, and citation registry. The background should be read as "
        "Evidence-context framing.\n"
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    details = " ".join(i.detail for i in report.issues)
    assert "[d1_inferential_bridge" in details
    assert "accepted receipt graph" in details
    assert "manifest, tension matrix, and citation registry" in details


def test_h3_residue_heading_blocks_journal_surface():
    report = evaluate_journal_surface("## Results\n\n### H3: Cardiometabolic Outcomes\n")
    assert not report.passed
    assert any("### h3:" in i.detail for i in report.issues)


def test_broken_possessive_fragment_blocks_journal_surface():
    report = evaluate_journal_surface(
        "## Results\n\nThis contrasts with 's evidence of a blunted response.\n",
    )
    assert not report.passed
    assert any("with 's evidence" in i.detail for i in report.issues)


def test_public_thesis_marker_blocks_journal_surface():
    report = evaluate_journal_surface(
        "## Abstract\n\n**Thesis:** This synthesis argues from an "
        "accepted receipt set.\n",
    )
    assert not report.passed
    details = " ".join(i.detail for i in report.issues)
    assert "**thesis:**" in details
    assert "accepted receipt" in details


def test_missing_references_blocks_journal_surface():
    report = evaluate_journal_surface(_paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |").replace("\n\n## References\n\n- Smith 2024.\n", ""))
    assert not report.passed
    assert any("missing required section: References" in i.detail for i in report.issues)


def test_orphan_table_reference_blocks_journal_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("results1", "Table 2 presents endpoint evidence", 1)
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("orphan table reference: Table 2" in i.detail for i in report.issues)


def test_labeled_table_reference_passes_journal_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("## Results\n\n", "## Results\n\nTable 2. Endpoint summary.\n\n")
    paper = paper.replace("results1", "Table 2 presents endpoint evidence", 1)
    report = evaluate_journal_surface(paper)
    assert report.passed


def test_reference_dump_and_internal_final_heading_block_journal_surface():
    report = evaluate_journal_surface(
        "## What This Synthesis Adds\n\n"
        "PMID: 12345. DOI: 10.1000/example.\n\n"
        "### Final interpretation\n\nInternal guidance.\n"
    )
    assert not report.passed
    details = " ".join(i.detail for i in report.issues)
    assert "public reference dump" in details
    assert "### final interpretation" in details


def test_duplicate_public_paragraph_blocks_journal_surface():
    para = " ".join(f"alpha{i}" for i in range(35))
    paper = f"## Results\n\n{para}\n\n{para} extra\n\n"
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "duplicate_paragraph" for i in report.issues)


def test_repeated_low_diversity_normal_methods_do_not_false_positive():
    paper = (
        "## Methods\n\n"
        "The review used structured source screening and source checks. "
        * 12
        + "\n\n## Results\n\n"
        "The review used structured source screening and source checks. "
        * 12
    )
    report = evaluate_journal_surface(paper)
    assert not any(i.code == "duplicate_paragraph" for i in report.issues)


def test_duplicate_appendix_paragraph_does_not_block_body_surface():
    good = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    para = " ".join(f"alpha{i}" for i in range(35))
    paper = good + f"\n\n## Publication Appendix\n\n{para}\n\n{para}\n"
    report = evaluate_journal_surface(paper)
    assert report.passed


def test_glp1_deterministic_evidence_summary_pattern_blocks_surface():
    paper = (
        "## Structured Evidence Tables\n\n"
        "*The following tables present the deterministic evidence summary "
        "referenced throughout this paper.*\n"
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "placeholder_prose" for i in report.issues)


def test_metformin_public_methods_meta_pattern_blocks_surface():
    paper = (
        "## Methods\n\n"
        "This synthesis was produced by the v0.6 quant-claim adapter "
        "pipeline on the metformin corpus (submission `synthesis-x`). "
        "Rejected-evidence quarantine did NOT run.\n"
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "template_meta" for i in report.issues)


def test_citation_artifacts_and_hedge_fragments_block_public_body():
    paper = "## Results\n\n[citation needed]\n\nMay.\n"
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "citation_artifact" for i in report.issues)
    assert any(i.code == "hedge_fragment" for i in report.issues)


def test_citation_artifacts_and_hedge_fragments_allowed_in_appendix():
    paper = (
        _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
        + "\n\n## Publication Appendix\n\n[citation needed]\n\nMay.\n"
    )
    report = evaluate_journal_surface(paper)
    assert report.passed


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


def test_abstract_over_journal_cap_blocks_surface():
    paper = _paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    ).replace(
        "## Abstract\n\n" + _words(150, "abstract"),
        "## Abstract\n\n" + _words(301, "abstract"),
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("section too long: Abstract 301/300 words" in i.detail for i in report.issues)


def test_empty_public_heading_blocks_surface():
    paper = _paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    ).replace("\n\n## References", "\n\n### Next-Study Design Recommendation\n\n## References")
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("empty heading: Next-Study Design Recommendation" in i.detail for i in report.issues)


def test_results_table_requires_matching_outcome_sections():
    paper = _paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    )
    results = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Immune | n=3 | mixed |\n"
        "| Cardiometabolic | n=2 | positive |\n\n"
        "### Cardiometabolic Outcomes\n\n"
        f"{_words(500, 'results')}\n\n"
    )
    paper = paper.replace(f"## Results\n\n{_words(500, 'results')}\n\n", results)
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("missing Results outcome section: Immune" in i.detail for i in report.issues)


def test_results_outcome_sections_must_use_declared_heading_once():
    paper = _paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    )
    results = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Immune | n=3 | mixed |\n\n"
        "### Immune and Inflammatory Outcomes\n\n"
        f"{_words(500, 'results')}\n\n"
    )
    paper = paper.replace(f"## Results\n\n{_words(500, 'results')}\n\n", results)
    report = evaluate_journal_surface(paper)
    assert not report.passed
    details = " ".join(i.detail for i in report.issues)
    assert "missing Results outcome section: Immune" in details
    assert "unexpected Results outcome section: immune and inflammatory" in details


def test_duplicate_declared_results_outcome_section_blocks_surface():
    paper = _paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    )
    results = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Immune | n=3 | mixed |\n\n"
        "### Immune Outcomes\n\n"
        f"{_words(260, 'immunea')}\n\n"
        "### Immune Outcomes\n\n"
        f"{_words(260, 'immuneb')}\n\n"
    )
    paper = paper.replace(f"## Results\n\n{_words(500, 'results')}\n\n", results)
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("duplicate Results outcome section: Immune" in i.detail for i in report.issues)


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
