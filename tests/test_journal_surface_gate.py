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
    # Discussion includes the **Thesis:** and **Resolution criteria:**
    # markers required by the Slice-9 thesis-taking gate so this default
    # fixture stays passing for tests that target other gates. Each
    # paragraph uses a distinct word-prefix so the duplicate-paragraph
    # gate doesn't false-positive on the synthetic filler text.
    discussion_body = (
        f"**Thesis:** This synthesis takes a defensible position. "
        f"{_words(420, 'discussion')}\n\n"
        f"**Resolution criteria:** Settled by future trials. "
        f"{_words(420, 'resolutionprose')}"
    )
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
        f"## Discussion\n\n{discussion_body}\n\n"
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


def test_public_thesis_marker_no_longer_blocks_but_pipeline_tokens_do():
    # Slice 9 (2026-05-14): `**Thesis:**` is now a REQUIRED Discussion
    # marker — no longer banned as a pipeline artifact. The other
    # pipeline-internal tokens ("accepted receipt", "receipt set") are
    # still forbidden in public prose.
    report = evaluate_journal_surface(
        "## Abstract\n\n**Thesis:** This synthesis argues from an "
        "accepted receipt set.\n",
    )
    assert not report.passed
    details = " ".join(i.detail for i in report.issues)
    # `**Thesis:**` itself must NOT be flagged anymore
    assert "**thesis:**" not in details.lower() or "missing `**thesis:**`" in details.lower()
    # The other pipeline leaks still are
    assert "accepted receipt" in details


def test_abstract_language_gate_blocks_duplicate_phrases_and_templates():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "## Abstract\n\n" + _words(150, "abstract"),
        "## Abstract\n\n"
        "The evidence profile contains 4 direct clinical direct clinical source(s). "
        + _words(140, "abstract"),
    )
    report = evaluate_journal_surface(paper)
    details = " ".join(i.detail for i in report.issues)
    assert not report.passed
    assert "duplicate adjacent phrase: direct clinical" in details
    assert "unresolved public template: source(s)" in details


def test_abstract_zero_count_profile_cannot_contradict_body():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "## Abstract\n\n" + _words(150, "abstract"),
        "## Abstract\n\nThe evidence profile contains 0 mechanistic sources. "
        + _words(140, "abstract"),
    )
    paper = paper.replace(
        "background1",
        "mechanistic studies appear in the body",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("abstract evidence-profile contradiction" in i.detail for i in report.issues)


def test_results_table_count_must_match_section_count_claim():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    results = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Cardiometabolic | n=14; claims=132 | mixed |\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "The cardiometabolic evidence packet spans 15 curated references. "
        f"{_words(492, 'results')}\n\n"
    )
    paper = paper.replace(f"## Results\n\n{_words(500, 'results')}\n\n", results)
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("Results count mismatch: Cardiometabolic Outcomes table n=14 body says 15" in i.detail for i in report.issues)


def test_thin_analytical_paragraph_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "## Results\n\n",
        "## Results\n\nMeta-analytic evidence corroborates the glycemic signal.\n\n",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("thin analytical paragraph" in i.detail for i in report.issues)


def test_conclusion_cannot_carry_what_this_adds_prose():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "conclusion1",
        "It separates endpoint-specific evidence from broad geroprotection claims. conclusion1",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("What This Synthesis Adds language appears inside Conclusion" in i.detail for i in report.issues)


def test_conclusion_scope_gate_does_not_require_broad_claim_wording():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "conclusion1",
        "It separates endpoint-specific evidence from inferential claims. conclusion1",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("What This Synthesis Adds language appears inside Conclusion" in i.detail for i in report.issues)


def test_missing_references_blocks_journal_surface():
    report = evaluate_journal_surface(_paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |").replace("\n\n## References\n\n- Smith 2024.\n", ""))
    assert not report.passed
    assert any("missing required section: References" in i.detail for i in report.issues)


def test_unreferenced_author_year_citation_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("discussion1", "ADA 2024 contextualizes the endpoint. discussion1", 1)
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("unreferenced citation: ADA 2024" in i.detail for i in report.issues)


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


# Bug-fix: gate must tolerate diacritic mismatch between inline
# citations and Reference-list entries (Hernández inline / Hernandez
# in refs). Universal — works for any Latin-script accent.


def test_unreferenced_citation_tolerates_diacritic_match() -> None:
    """Inline 'Hernández 2024' + ref 'Hernandez 2024' (NFKD-equivalent)
    must NOT flag as unreferenced."""
    from agent.journal_surface_gate import unreferenced_citation_tokens
    paper = (
        "## Introduction\n\nHernández 2024 reported a finding.\n\n"
        "## References\n\n- **Hernandez 2024.** 2024.\n"
    )
    assert unreferenced_citation_tokens(paper) == ()


def test_unreferenced_citation_still_flags_real_missing() -> None:
    """Defensive: the fold helper must not silently accept genuinely
    missing references (e.g. Jones cited inline but not in refs)."""
    from agent.journal_surface_gate import unreferenced_citation_tokens
    paper = (
        "## Introduction\n\nSmith 2020 said. Jones 2021 said another.\n\n"
        "## References\n\n- Smith 2020.\n"
    )
    assert "Jones 2021" in unreferenced_citation_tokens(paper)


def test_unreferenced_citation_is_case_insensitive() -> None:
    """Casefolding is part of the universal fold so inline 'SMITH 2020'
    matches reference 'Smith 2020' (case shouldn't matter for ID)."""
    from agent.journal_surface_gate import unreferenced_citation_tokens
    paper = (
        "## Introduction\n\nSMITH 2020 said.\n\n"
        "## References\n\n- Smith 2020.\n"
    )
    assert unreferenced_citation_tokens(paper) == ()


# Bug-fix: pipeline-internal vocabulary (source-bound observation,
# claim atom, endpoint proximity, structured corpus synthesis) must
# not appear in the public manuscript body. Audit sidecars + supplement
# may still use the raw terms.


def test_pipeline_jargon_flagged_in_public_prose() -> None:
    """Each jargon token surfaces an issue naming the academic
    replacement so the writer / auto-fixer can swap it in."""
    paper = _paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    )
    paper = paper.replace(
        "## Methods\n\n", "## Methods\n\nThis is a structured corpus synthesis.\n\n",
    )
    paper = paper.replace(
        "## Results\n\n",
        "## Results\n\nThe source-bound observation set spans 30 receipts; endpoint proximity differs.\n\n",
    )
    report = evaluate_journal_surface(paper)
    codes = [i.code for i in report.issues]
    assert "pipeline_jargon" in codes
    details = " | ".join(i.detail for i in report.issues if i.code == "pipeline_jargon")
    assert "structured corpus synthesis" in details
    assert "source-bound observation" in details
    assert "endpoint proximity" in details


def test_academic_prose_passes_jargon_gate() -> None:
    """Defensive: the gate must not false-positive on standard
    academic phrasing without the forbidden tokens."""
    paper = _paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    )
    report = evaluate_journal_surface(paper)
    assert not any(i.code == "pipeline_jargon" for i in report.issues)


# Bug-fix: every entry in the References bibliography must be cited
# inline at least once. Catches the failure mode where the writer
# emits a stub reference but never names the source in prose (the
# real-world example was "renovar 2023" appearing only in refs).


def test_orphan_reference_flagged() -> None:
    """Reference listed in bibliography but never cited inline → flag."""
    from agent.journal_surface_gate import orphan_reference_tokens
    paper = (
        "## Introduction\n\nSmith 2020 reported.\n\n"
        "## References\n\n- Smith 2020.\n- Cresnovar 2023.\n"
    )
    tokens = orphan_reference_tokens(paper)
    assert "Cresnovar 2023" in tokens
    assert "Smith 2020" not in tokens


def test_orphan_reference_tolerates_diacritic_match() -> None:
    """A reference 'Hernandez 2024' (ASCII) cited inline as
    'Hernández 2024' (diacritic) must NOT flag as orphan."""
    from agent.journal_surface_gate import orphan_reference_tokens
    paper = (
        "## Introduction\n\nHernández 2024 found a thing.\n\n"
        "## References\n\n- Hernandez 2024.\n"
    )
    assert orphan_reference_tokens(paper) == ()


def test_orphan_reference_no_refs_section_returns_empty() -> None:
    """No References section → nothing to flag (other gates catch
    the missing section separately)."""
    from agent.journal_surface_gate import orphan_reference_tokens
    paper = "## Introduction\n\nSmith 2020 reported.\n"
    assert orphan_reference_tokens(paper) == ()


# Bug-fix: evidence-lane labels — animal / preclinical citations must
# appear in a paragraph that explicitly frames the evidence as
# non-human. Universal — works for any topic that mixes human and
# animal evidence.


def test_is_animal_paper_keyword_set_universal() -> None:
    """Detector hits common non-human organisms + veterinary markers."""
    from agent.journal_surface_gate import is_animal_paper
    assert is_animal_paper("...in obese equids and ponies")
    assert is_animal_paper("Long-Tailed Macaque Breeding Groups")
    assert is_animal_paper("Murine model of caloric restriction")
    assert is_animal_paper("Journal of Veterinary Internal Medicine")
    assert is_animal_paper("C. elegans lifespan extension")
    # Negative: pure human-clinical text
    assert not is_animal_paper("adults with type 2 diabetes")
    assert not is_animal_paper("")
    assert not is_animal_paper(None)


def test_unlabeled_animal_citation_flagged() -> None:
    """Animal citation in a paragraph without an animal-lane qualifier
    fails the gate; same citation in a paragraph with 'equine' or
    'preclinical' or any qualifier passes."""
    bad = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    bad = bad.replace(
        "## Results\n\n",
        "## Results\n\nThe trial reported Zijlmans 2022 showed reductions in adipose mass over 24 weeks.\n\n",
    )
    report = evaluate_journal_surface(bad, animal_citations=["Zijlmans 2022"])
    assert any(i.code == "evidence_lane" for i in report.issues)


def test_animal_citation_with_lane_qualifier_passes() -> None:
    """Defensive: same animal citation framed as preclinical → no flag."""
    good = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    good = good.replace(
        "## Results\n\n",
        "## Results\n\nIn non-human primate evidence, Zijlmans 2022 showed reductions in adipose mass.\n\n",
    )
    report = evaluate_journal_surface(good, animal_citations=["Zijlmans 2022"])
    assert not any(i.code == "evidence_lane" for i in report.issues)


def test_evidence_lane_check_skipped_when_no_sidecar() -> None:
    """Backward-compat: existing callers that do not pass
    animal_citations must see identical behaviour to pre-Slice-4."""
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    report_old = evaluate_journal_surface(paper)
    report_new = evaluate_journal_surface(paper, animal_citations=None)
    assert [i.code for i in report_old.issues] == [i.code for i in report_new.issues]


# Bug-fix: novelty / framework claims must be grounded in prior
# literature within the same paragraph (≥1 Author-Year citation).
# Universal — works for any topic that introduces a framework.


def test_unsupported_novelty_claim_flagged() -> None:
    """A 'we propose' paragraph with zero inline citations → flag."""
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    paper = paper.replace(
        "## Discussion\n\n",
        "## Discussion\n\nWe propose a novel framework that resolves all tensions in the corpus.\n\n",
    )
    report = evaluate_journal_surface(paper)
    assert any(i.code == "unsupported_novelty" for i in report.issues)


def test_grounded_novelty_claim_passes() -> None:
    """Defensive: 'we propose' paragraph WITH a prior-lit citation → no flag."""
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    paper = paper.replace(
        "## Discussion\n\n",
        "## Discussion\n\nBuilding on prior synthesis (Smith 2024), we propose an extension that operationalizes the gradient claim-by-claim.\n\n",
    )
    report = evaluate_journal_surface(paper)
    assert not any(i.code == "unsupported_novelty" for i in report.issues)


def test_novelty_gate_catches_multiple_phrasings() -> None:
    """Universal: 'novel framework', 'we operationalize', 'first to
    propose' must all trigger the check."""
    from agent.journal_surface_gate import _unsupported_novelty_claim_issue_messages
    for phrase in (
        "We propose a new approach.",
        "Our novel framework explains the gap.",
        "We operationalize a new construct.",
        "We are the first to propose this synthesis.",
    ):
        body = f"## Framework\n\n{phrase}\n"
        msgs = _unsupported_novelty_claim_issue_messages(body)
        assert msgs, f"expected flag for: {phrase}"


# Bug-fix: per-outcome cited-author cross-check (Slice 6 of the
# editorial-conformance work). Every Author-Year token in a
# `### X Outcomes` Results subsection must come from a receipt whose
# outcome_class normalises to X. Universal — caller supplies the map.


def test_outcome_class_mismatch_flagged() -> None:
    """Beavers 2022 (frailty receipt) cited in Cardiometabolic
    subsection → flag with both citation and section names."""
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    new_results = (
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "Beavers 2022 reported gait speed changes (P < 0.05).\n\n"
        "### Frailty Outcomes\n\nFrailty stub.\n\n"
    )
    paper = paper.replace(f"## Results\n\n{_words(500, 'results')}\n\n", new_results)
    report = evaluate_journal_surface(
        paper,
        citation_outcome_map={"Beavers 2022": "frailty"},
    )
    detail = " | ".join(i.detail for i in report.issues if i.code == "outcome_routing")
    assert "Beavers 2022" in detail
    assert "Cardiometabolic" in detail


def test_outcome_class_match_passes() -> None:
    """Same citation cited in its OWN outcome subsection → no flag."""
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    new_results = (
        "## Results\n\n"
        "### Frailty Outcomes\n\n"
        "Beavers 2022 reported gait speed changes (P < 0.05).\n\n"
    )
    paper = paper.replace(f"## Results\n\n{_words(500, 'results')}\n\n", new_results)
    report = evaluate_journal_surface(
        paper,
        citation_outcome_map={"Beavers 2022": "frailty"},
    )
    assert not any(i.code == "outcome_routing" for i in report.issues)


def test_outcome_routing_check_skipped_without_map() -> None:
    """Backward-compat: no map → no check (previous callers untouched)."""
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    report_old = evaluate_journal_surface(paper)
    report_new = evaluate_journal_surface(paper, citation_outcome_map=None)
    assert [i.code for i in report_old.issues] == [i.code for i in report_new.issues]


# Bug-fix: Limitations summary-prose leak detector (Slice 7).
# Limitations must name limitations; summary-of-findings prose or
# synthesis-contribution prose belongs elsewhere. Universal patterns,
# topic-agnostic.


def test_limitations_summary_prose_flagged() -> None:
    """Each of the canonical leak patterns is detected."""
    from agent.journal_surface_gate import _limitations_summary_leak_issue_messages
    for leak in (
        "Positive signals appear in cardiometabolic.",
        "Negative signals appear in immune.",
        "Null findings dominate the corpus.",
        "the evidence base for caloric restriction is incomplete.",
        "The strongest unresolved contrast is X vs Y.",
        "Across 47 curated reference papers, ...",
        "It separates endpoint-specific evidence from broad claims.",
    ):
        body = f"## Limitations\n\nReal limitation here. {leak}\n\n## Conclusion\n"
        msgs = _limitations_summary_leak_issue_messages(body)
        assert msgs, f"expected flag for: {leak}"


def test_limitations_legit_prose_passes() -> None:
    """Defensive: real limitation sentences (no summary tokens) → no flag."""
    from agent.journal_surface_gate import _limitations_summary_leak_issue_messages
    body = (
        "## Limitations\n\nThe corpus omits long-term mortality RCTs. "
        "Single-trial outcomes cannot be replicated. Population specificity "
        "limits generalization beyond the enrolled cohort.\n\n## Conclusion\n"
    )
    assert _limitations_summary_leak_issue_messages(body) == ()


# Slice 9 — Discussion thesis-taking discipline. The Discussion must
# open with a literal **Thesis:** marker and end with a
# **Resolution criteria:** paragraph. Universal — markers are
# topic-agnostic.


def test_undeclared_thesis_flagged() -> None:
    """Discussion without a `**Thesis:**` marker → flag."""
    from agent.journal_surface_gate import _undeclared_thesis_in_discussion_issue_messages
    body = (
        "## Discussion\n\nThe evidence is context-dependent and warrants "
        "further study.\n\n## Limitations\n"
    )
    msgs = _undeclared_thesis_in_discussion_issue_messages(body)
    assert any("Thesis:" in m for m in msgs)


def test_missing_resolution_criteria_flagged() -> None:
    """Discussion with Thesis but no Resolution criteria → flag."""
    from agent.journal_surface_gate import _undeclared_thesis_in_discussion_issue_messages
    body = (
        "## Discussion\n\n**Thesis:** The intervention reduces risk in adults. "
        "The convergent signals from Smith 2020 and Jones 2021 support this.\n\n"
        "## Limitations\n"
    )
    msgs = _undeclared_thesis_in_discussion_issue_messages(body)
    assert any("Resolution criteria:" in m for m in msgs)


def test_discussion_with_both_markers_passes() -> None:
    """Defensive: Discussion containing both markers → no flag."""
    from agent.journal_surface_gate import _undeclared_thesis_in_discussion_issue_messages
    body = (
        "## Discussion\n\n**Thesis:** Position sentence here. Supporting prose.\n\n"
        "**Resolution criteria:** Settled by an RCT.\n\n## Limitations\n"
    )
    assert _undeclared_thesis_in_discussion_issue_messages(body) == ()


def test_thesis_marker_case_insensitive() -> None:
    """Universal: `**THESIS:**` or `**Thesis:**` both satisfy the gate."""
    from agent.journal_surface_gate import _undeclared_thesis_in_discussion_issue_messages
    body = (
        "## Discussion\n\n**THESIS:** Strong claim.\n\n"
        "**Resolution Criteria:** Trial design.\n\n## Limitations\n"
    )
    assert _undeclared_thesis_in_discussion_issue_messages(body) == ()
