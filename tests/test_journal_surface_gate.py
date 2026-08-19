"""Tests for the deterministic journal-surface gate."""
from __future__ import annotations

from agent.journal_surface_gate import (
    evaluate_journal_surface,
    is_publishable_qei_row,
    qei_row_issue_messages,
)
from agent.methods_pack import REQUIRED_METHODS_H3_MARKERS
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


def _complete_surface(paper: str):
    methods = "\n\n".join(
        f"{marker}\n\nMethod detail {i}."
        for i, marker in enumerate(REQUIRED_METHODS_H3_MARKERS, start=1)
    )
    paper = paper.replace("## Methods\n\n", f"## Methods\n\n{methods}\n\n", 1)
    return evaluate_journal_surface(
        paper,
        animal_citations=[],
        citation_outcome_map={},
        declared_review_type="thin_corpus_brief",
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


def test_qei_surface_gate_rejects_blank_endpoint_with_numeric_value() -> None:
    issues = qei_row_issue_messages({
        "study_label": "Smith 2024", "endpoint": "", "value": "1.2",
        "unit_or_type": "mg/dL", "statistic": "p=0.01",
    })
    assert "unpublishable endpoint: blank" in issues


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
    report = _complete_surface(paper)
    assert not report.passed
    assert any(i.code == "duplicate_heading" for i in report.issues)


def test_surface_gate_flags_public_topic_slug_artifacts():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("background1", "urolithin_a", 1)
    report = _complete_surface(paper)
    assert not report.passed
    assert any(i.code == "topic_slug_artifact" for i in report.issues)


def test_surface_gate_flags_platform_wrapper_artifacts():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("abstract1", "DECISION: ACCEPT", 1)
    report = _complete_surface(paper)
    assert not report.passed
    assert any(i.code == "public_artifact" and "decision: accept" in i.detail for i in report.issues)


def test_surface_gate_flags_not_extracted_preview_text():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("abstract1", "not extracted", 1)
    report = _complete_surface(paper)
    assert not report.passed
    assert any(i.code == "public_artifact" and "not extracted" in i.detail for i in report.issues)


def test_surface_gate_allows_methods_risk_of_bias_tool_names():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "methods1",
        "Cochrane RoB-2, ROBINS-I, and risk-of-bias roll-up methods were prespecified.",
        1,
    )
    report = _complete_surface(paper)
    assert not any(i.code == "public_artifact" and "risk-of-bias" in i.detail for i in report.issues)


def test_malformed_qei_row_in_appendix_does_not_block_public_body():
    paper = (
        _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
        + "\n\n## Publication Appendix\n\n"
        "## Quantitative Evidence Index\n\n"
        "| Kell 2026 | mTOR signaling | placebo | p<0.001 |\n"
    )
    report = _complete_surface(paper)
    assert report.passed


def test_placeholder_prose_blocks_journal_surface():
    paper = (
        "## Introduction\n\n"
        "This paper evaluates the topic through accepted receipts.\n\n"
        "## Methods\n\nMethods.\n"
    )
    report = _complete_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_unresolved_stat_placeholder_variants_block_journal_surface() -> None:
    phrases = (
        "Exact statistic unavailable in retained source excerpt.",
        "Exact p-value not available in retained source excerpt.",
        "The retained source excerpt does not report the exact confidence interval.",
        "The effect estimate was not extractable from the retained source excerpt.",
    )
    for phrase in phrases:
        paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
        report = _complete_surface(paper.replace("abstract1", phrase, 1))
        assert any(i.code == "public_text_integrity" and "unresolved statistic" in i.detail for i in report.issues)


def test_agent_certified_blocks_human_verification_even_with_signoff_flag() -> None:
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "methods1",
        "Accountability is established through reproducible artifacts and deterministic gates. Final decisions are author-verified.",
        1,
    )
    report = evaluate_journal_surface(
        paper, animal_citations=[], citation_outcome_map={},
        declared_review_type="thin_corpus_brief",
        accountability_model="researka_agent_certified",
        human_signoff_validated=True,
    )
    assert any("unsupported human-verification" in i.detail for i in report.issues)


def test_legacy_human_verification_requires_validated_signoff() -> None:
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("methods1", "Final decisions are author-verified.", 1)
    invalid = evaluate_journal_surface(
        paper, accountability_model="legacy_journal_submission",
        human_signoff_validated=False,
    )
    valid = evaluate_journal_surface(
        paper, accountability_model="legacy_journal_submission",
        human_signoff_validated=True,
    )
    assert any("unsupported human-verification" in i.detail for i in invalid.issues)
    assert not any("unsupported human-verification" in i.detail for i in valid.issues)


def test_agent_certified_requires_automated_gate_accountability_text() -> None:
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    missing = evaluate_journal_surface(paper, accountability_model="researka_agent_certified")
    present = evaluate_journal_surface(
        paper.replace("methods1", "Accountability is established through reproducible artifacts and deterministic gates.", 1),
        accountability_model="researka_agent_certified",
    )
    assert any("missing automated-gate accountability" in i.detail for i in missing.issues)
    assert not any("missing automated-gate accountability" in i.detail for i in present.issues)


def test_conclusion_fallback_prose_blocks_journal_surface():
    paper = (
        "## Conclusion\n\n"
        "The conclusion is limited to claims that survive receipt "
        "qualification, source-context checks, and final audit gates.\n"
    )
    report = _complete_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_bounded_conclusion_backfill_blocks_journal_surface():
    paper = (
        "## Conclusion\n\n"
        "The synthesis supports a bounded conclusion: the topic has enough "
        "receipt-traced evidence to justify structured interpretation, but "
        "the evidence should be read through its tiered profile.\n"
    )
    report = _complete_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_validation_contract_meta_prose_blocks_journal_surface():
    paper = (
        "## Discussion\n\n"
        "The interpretation remains cautious when section generation "
        "cannot satisfy the validation contract.\n"
    )
    report = _complete_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_llm_meta_slogans_block_journal_surface():
    paper = (
        "## Methods\n\n"
        "The load-bearing principle is LLM proposes, code disposes, "
        "with no LLM authorship.\n"
    )
    report = _complete_surface(paper)
    assert not report.passed
    assert report.issues[0].code == "placeholder_prose"


def test_appendix_meta_language_does_not_block_body_surface():
    paper = (
        _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
        + "\n\n## Data and Code Availability\n\n"
        "The audit appendix can describe that LLM proposes, code disposes.\n"
    )
    report = _complete_surface(paper)
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


def test_plain_english_receipt_does_not_block_journal_surface():
    report = evaluate_journal_surface(
        "## Results\n\n"
        "The receipt of treatment was recorded in routine clinical records.\n",
    )
    details = {(i.code, i.detail) for i in report.issues}
    assert ("public_artifact", "receipt") not in details


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


def test_abstract_language_gate_allows_category_list_conjunction_repeat():
    paper = _paper("| Smith 2024 | safety | older adults | unclear | n/a | B1 |")
    paper = paper.replace(
        "## Abstract\n\n" + _words(150, "abstract"),
        "## Abstract\n\n"
        "Mixed signals are summarized in cardiometabolic, mortality and survival, "
        "safety, and safety and comorbidity outcome classes. "
        + _words(130, "abstract"),
    )
    report = evaluate_journal_surface(paper)
    details = " ".join(i.detail for i in report.issues)
    assert "duplicate adjacent phrase: safety and" not in details


def test_abstract_language_gate_allows_repeated_statistical_notation():
    paper = _paper("| Smith 2024 | safety | older adults | unclear | n/a | B1 |")
    paper = paper.replace(
        "## Abstract\n\n" + _words(150, "abstract"),
        "## Abstract\n\n"
        "One endpoint reached P < 0.001; another reached P = 0.001. "
        + _words(140, "abstract"),
    )

    details = " ".join(i.detail for i in evaluate_journal_surface(paper).issues)

    assert "duplicate adjacent phrase: p 0 001" not in details


def test_abstract_language_gate_still_blocks_repeated_numbered_prose():
    paper = _paper("| Smith 2024 | safety | older adults | unclear | n/a | B1 |")
    paper = paper.replace(
        "## Abstract\n\n" + _words(150, "abstract"),
        "## Abstract\n\nThe Phase 2 Phase 2 trial was retained. " + _words(140, "abstract"),
    )

    details = " ".join(i.detail for i in evaluate_journal_surface(paper).issues)

    assert "duplicate adjacent phrase: phase 2" in details


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


def test_truncated_sentence_blocks_surface():
    # EGCG revise reason: a sentence cut off mid-thought ("...null versus
    # positive findings...") must be caught before submit, not by Researka.
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "## Results\n\n",
        "## Results\n\nAcross the included randomized trials the pooled estimate "
        "suggests a clear divergence between the null and positive findings...\n\n",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("truncated sentence" in i.detail for i in report.issues)


def test_unbalanced_parenthetical_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "## Results\n\n",
        "## Results\n\nThe retained trials reported several outcomes (e.\n\n",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("unbalanced parenthetical" in i.detail for i in report.issues)


def test_short_dangling_parenthetical_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("## Results\n\n", "## Results\n\nEffects remained unclear (e.\n\n", 1)
    report = evaluate_journal_surface(paper)
    assert any("unbalanced parenthetical" in i.detail for i in report.issues)


def test_short_general_unbalanced_parenthetical_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("## Results\n\n", "## Results\n\nResults were null (n=3.\n\n", 1)
    report = evaluate_journal_surface(paper)
    assert any("unbalanced parenthetical" in i.detail for i in report.issues)


def test_half_open_numeric_interval_is_not_an_unbalanced_parenthetical():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "## Results\n\n",
        "## Results\n\nThe prespecified normalized interval was (0, 1].\n\n",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not any("unbalanced parenthetical" in i.detail for i in report.issues)


def test_citation_only_reported_stub_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("## Cross-Domain Synthesis\n\n", "## Cross-Domain Synthesis\n\nWu 2025 reported.\n\n", 1)
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("citation-only stub" in i.detail for i in report.issues)


def test_known_grammar_artifact_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "abstract1",
        "The evidence is insufficient to is consistent with therapeutic efficacy.",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "grammar_artifact" for i in report.issues)


def test_double_copula_splice_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "abstract1",
        "The boundary conditions for any clinical benefit remain to be rigorously is consistent with.",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "grammar_artifact" and "to be rigorously is" in i.detail for i in report.issues)


def test_domain_transfer_grammar_artifact_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "abstract1",
        "A signal in one domain does not automatically is consistent with the same signal in another.",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any(i.code == "grammar_artifact" and "automatically is" in i.detail for i in report.issues)


def test_legitimate_to_be_consistent_sentence_does_not_trigger_grammar_artifact():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "abstract1",
        "The evidence appears to be consistent with a bounded hypothesis.",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not any(i.code == "grammar_artifact" for i in report.issues)


def test_sentence_initial_infinitive_does_not_trigger_grammar_artifact():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("abstract0 abstract1", "abstract0. To be rigorous is important for this evidence synthesis.", 1)
    report = evaluate_journal_surface(paper)
    assert not any(i.code == "grammar_artifact" for i in report.issues)


def test_classification_metadata_row_blocks_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "## Results\n\n",
        "## Results\n\n"
        "| **Outcome class** is assigned from endpoint text | not extracted | not extracted |\n\n",
        1,
    )
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("classification metadata leaked as study row" in i.detail for i in report.issues)


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


def test_lowercase_reference_label_matches_inline_author_year():
    paper = _paper("| Velayati 2025 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("- Smith 2024.", "- **velayati 2025.** DOI: 10.1/example.")
    report = _complete_surface(paper)
    assert report.passed


def test_orphan_table_reference_blocks_journal_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("results1", "Table 2 presents endpoint evidence", 1)
    report = evaluate_journal_surface(paper)
    assert not report.passed
    assert any("orphan table reference: Table 2" in i.detail for i in report.issues)


def test_source_internal_table_reference_is_not_a_manuscript_cross_reference():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace(
        "results1",
        "\n\nSmith 2024 [bundle:1] reports: values in Table 2 "
        "[exact source: https://doi.org/10.1/example].\n\n",
        1,
    )
    assert _complete_surface(paper).passed


def test_exact_source_marker_does_not_bypass_orphan_table_check():
    source = "Smith 2024 [bundle:1] reports: values [exact source: https://doi.org/10.1/example]."
    for claim in (f"As shown in Table 99. {source}", f"{source} As shown in Table 99."):
        paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
        paper = paper.replace("results1", claim, 1)
        assert any(
            "orphan table reference: Table 99" in issue.detail
            for issue in evaluate_journal_surface(paper).issues
        )


def test_labeled_table_reference_passes_journal_surface():
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    paper = paper.replace("## Results\n\n", "## Results\n\nTable 2. Endpoint summary.\n\n")
    paper = paper.replace("results1", "Table 2 presents endpoint evidence", 1)
    report = _complete_surface(paper)
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
    report = _complete_surface(paper)
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
    report = _complete_surface(paper)
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
    assert "unexpected Results outcome section: immune inflammatory" in details


def test_results_summary_heading_is_not_an_outcome_section() -> None:
    paper = _paper("| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |")
    results = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Immune | n=3 | mixed |\n\n"
        "### Results Summary\n\n"
        "This paragraph summarizes the Results section before outcome-specific subsections.\n\n"
        "### Immune Outcomes\n\n"
        f"{_words(500, 'results')}\n\n"
    )
    report = evaluate_journal_surface(paper.replace(f"## Results\n\n{_words(500, 'results')}\n\n", results))
    assert not any("unexpected Results outcome section: results summary" in i.detail for i in report.issues)


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


def test_refined_outcome_display_heading_satisfies_results_contract():
    paper = _paper(
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
    )
    results = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Safety and Comorbidity | n=1 | mixed |\n\n"
        "### Safety and Comorbidity Outcomes\n\n"
        f"{_words(500, 'results')}\n\n"
    )
    paper = paper.replace(f"## Results\n\n{_words(500, 'results')}\n\n", results)
    report = evaluate_journal_surface(paper)
    assert not any("Safety and Comorbidity" in i.detail for i in report.issues)


def test_valid_rows_pass_surface_gate():
    row = EvidenceRow(
        study_label="Smith 2024", endpoint="fasting glucose",
        arm="control", value="89 mg/dL", unit_or_type="mg/dL",
        statistic="—", citation="Smith 2024",
    )
    assert is_publishable_qei_row(row)
    report = _complete_surface(_paper(
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


def test_unreferenced_citation_ignores_possessive_year_phrase() -> None:
    from agent.journal_surface_gate import unreferenced_citation_tokens
    paper = (
        "## Introduction\n\n"
        "The Food and Drug Administration's 2023 decision is regulatory context.\n\n"
        "## References\n\n- Smith 2020.\n"
    )
    assert unreferenced_citation_tokens(paper) == ()


def test_unreferenced_citation_ignores_date_ranges() -> None:
    from agent.journal_surface_gate import unreferenced_citation_tokens
    paper = (
        "## Results\n\n"
        "Participants were enrolled between June 2023 and September 2024.\n\n"
        "## References\n\n- Chai 2026.\n"
    )
    assert unreferenced_citation_tokens(paper) == ()


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


def test_missing_semantic_inputs_fail_closed() -> None:
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    report = evaluate_journal_surface(paper)
    missing = [i for i in report.issues if i.code == "missing_semantic_context"]
    assert not report.passed
    assert {i.detail for i in missing} == {
        "animal_citations not supplied",
        "citation_outcome_map not supplied",
        "declared_review_type not supplied",
    }


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
    """Universal: 'we propose', 'novel framework', 'we introduce',
    'first to propose' must trigger the check. Note: 'we operationalize'
    is intentionally NOT in the trigger set — per the Slice 16 finalizer
    doctrine, it is the SAFE rewrite of an ungrounded 'we propose',
    implying build-on-prior-work rather than first invention."""
    from agent.journal_surface_gate import _unsupported_novelty_claim_issue_messages
    for phrase in (
        "We propose a new approach.",
        "Our novel framework explains the gap.",
        "We introduce a new framework.",
        "We are the first to propose this synthesis.",
    ):
        body = f"## Framework\n\n{phrase}\n"
        msgs = _unsupported_novelty_claim_issue_messages(body)
        assert msgs, f"expected flag for: {phrase}"
    # Defensive: confirm "we operationalize" is intentionally NOT flagged
    body_safe = "## Framework\n\nWe operationalize the gradient lens here.\n"
    assert _unsupported_novelty_claim_issue_messages(body_safe) == ()


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


def test_outcome_cross_reference_in_anchored_sentence_passes() -> None:
    """Sentence-dominant routing (2026-06-13): a sentence anchored to its own
    outcome class may reference another class for cross-domain synthesis ("the
    exposure in Sahay 2026 maps onto the cardiometabolic effects in Hong 2026")
    without being flagged — the minority cross-reference is legitimate."""
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    new_results = (
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "The exposure in Sahay 2026 maps onto the cardiometabolic effects in "
        "Hong 2026 and Lim 2026.\n\n"
        "### Frailty Outcomes\n\nFrailty stub.\n\n"
    )
    paper = paper.replace(f"## Results\n\n{_words(500, 'results')}\n\n", new_results)
    report = evaluate_journal_surface(paper, citation_outcome_map={
        "Sahay 2026": "dosing_pharmacokinetics",
        "Hong 2026": "cardiometabolic",
        "Lim 2026": "cardiometabolic",
    })
    assert not any(i.code == "outcome_routing" for i in report.issues)


def test_outcome_routing_missing_map_is_explicit_failure() -> None:
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    report = evaluate_journal_surface(
        paper, animal_citations=[], declared_review_type="evidence_map",
    )
    assert any(
        i.code == "missing_semantic_context"
        and i.detail == "citation_outcome_map not supplied"
        for i in report.issues
    )


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
        "the evidence base for caloric restriction shows mixed signals.",
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
        "limits generalization beyond the enrolled cohort. The evidence base "
        "for pediatric populations is limited.\n\n## Conclusion\n"
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


# Slice 10 — review-type self-claim gate. Manifest declares one of the
# 7 canonical review types; Abstract/Methods must not self-claim a
# stronger methodology. Universal — no per-topic knowledge.


def test_review_type_self_claim_flagged() -> None:
    """`We conducted a systematic review` in Methods when manifest
    declares scoping synthesis → flag."""
    from agent.journal_surface_gate import _review_type_overclaim_issue_messages
    paper = (
        "## Abstract\n\nA short abstract.\n\n"
        "## Methods\n\nWe conducted a systematic review following PRISMA 2020.\n"
    )
    issues = _review_type_overclaim_issue_messages(paper, "prisma_scr_scoping_synthesis")
    assert any("systematic review" in i for i in issues)


def test_review_type_cited_evidence_not_flagged() -> None:
    """Listing 'systematic reviews and meta-analyses' as included
    evidence types is NOT a self-methodological claim — must not flag."""
    from agent.journal_surface_gate import _review_type_overclaim_issue_messages
    paper = (
        "## Abstract\n\nThis synthesis integrated randomized controlled trials, "
        "systematic reviews and meta-analyses, and observational cohorts.\n\n"
        "## Methods\n\nSources were screened for relevance.\n"
    )
    assert _review_type_overclaim_issue_messages(paper, "prisma_scr_scoping_synthesis") == ()


def test_review_type_check_skipped_for_strongest_tier() -> None:
    """When manifest declares the strongest tier (systematic_review or
    meta_analysis), there are no over-claims to flag — empty forbidden set."""
    from agent.journal_surface_gate import _review_type_overclaim_issue_messages
    paper = (
        "## Abstract\n\nThis paper is a systematic review and meta-analysis.\n\n"
        "## Methods\n\nWe registered with PROSPERO and followed PRISMA 2020.\n"
    )
    assert _review_type_overclaim_issue_messages(paper, "meta_analysis") == ()


def test_undeclared_review_type_is_explicit_failure() -> None:
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    paper = paper.replace(
        "## Methods\n\n",
        "## Methods\n\nWe conducted a systematic review and meta-analysis.\n\n",
    )
    report_no_type = evaluate_journal_surface(paper)
    assert any(
        i.code == "missing_semantic_context"
        and i.detail == "declared_review_type not supplied"
        for i in report_no_type.issues
    )
    assert not any(i.code == "review_type_overclaim" for i in report_no_type.issues)
    report_with_type = evaluate_journal_surface(
        paper, declared_review_type="prisma_scr_scoping_synthesis",
    )
    assert any(i.code == "review_type_overclaim" for i in report_with_type.issues)


def test_review_type_parse_validates() -> None:
    """parse_review_type accepts known tokens, defaults None/empty,
    raises on unknown tokens. Universal — no per-topic knowledge."""
    from agent.review_type import parse_review_type, ReviewTypeError, DEFAULT_REVIEW_TYPE
    assert parse_review_type(None) == DEFAULT_REVIEW_TYPE
    assert parse_review_type("") == DEFAULT_REVIEW_TYPE
    assert parse_review_type("narrative_review") == "narrative_review"
    # case + hyphen tolerance
    assert parse_review_type("Narrative-Review") == "narrative_review"
    try:
        parse_review_type("ivy_league_review")
    except ReviewTypeError as e:
        assert "unknown" in str(e).lower()
    else:
        raise AssertionError("expected ReviewTypeError for unknown token")


# Slice 11 — PRISMA-ScR Methods pack. The Methods section must
# contain 11 H3 subsection markers when manifest declares a review
# type. Universal — markers are topic-agnostic.


def test_methods_pack_completeness_flags_missing_markers() -> None:
    """Existing-style Methods (single prose block) → 11 missing markers."""
    from agent.journal_surface_gate import _methods_pack_completeness_issue_messages
    paper = (
        "## Methods\n\nWe conducted a structured synthesis. Source set frozen.\n\n"
        "## Results\n"
    )
    issues = _methods_pack_completeness_issue_messages(paper, "prisma_scr_scoping_synthesis")
    assert len(issues) == 11
    assert any("### Search strategy" in i for i in issues)
    assert any("### AI-use disclosure" in i for i in issues)


def test_methods_pack_complete_passes() -> None:
    """Methods with all 11 markers → no flag."""
    from agent.methods_pack import build_methods_pack, render_methods_md
    pack = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis",
        topic="x_topic", corpus_search_queries=("q1",),
        n_retrieved=10, n_screened=5, n_included=2, n_rejected=3,
        outcome_classes=("a", "b"),
    )
    paper = render_methods_md(pack, submission_id="run-1") + "\n\n## Results\n"
    from agent.journal_surface_gate import _methods_pack_completeness_issue_messages
    issues = _methods_pack_completeness_issue_messages(paper, "prisma_scr_scoping_synthesis")
    assert issues == ()


def test_methods_pack_skipped_when_no_review_type() -> None:
    """Backward-compat: no declared review_type → check skipped."""
    from agent.journal_surface_gate import _methods_pack_completeness_issue_messages
    paper = "## Methods\n\nStub.\n\n## Results\n"
    assert _methods_pack_completeness_issue_messages(paper, None) == ()
    assert _methods_pack_completeness_issue_messages(paper, "") == ()


def test_methods_pack_required_fields_missing_detects_stub() -> None:
    """MethodsPack.required_fields_missing() flags empty fields."""
    from agent.methods_pack import MethodsPack
    stub = MethodsPack(
        review_type="", databases_searched=(), search_strings=(),
        search_dates="", eligibility_criteria=(),
        screening_flow={"n_retrieved": 0},
        data_extraction_fields=(), exclusion_reason_summary=(),
        risk_of_bias_approach="", synthesis_approach="",
        ai_use_disclosure="", human_accountability="",
    )
    missing = set(stub.required_fields_missing())
    # Every field should flag as missing (string empty / tuple empty /
    # dict all-zero).
    assert "review_type" in missing
    assert "search_strings" in missing
    assert "screening_flow" in missing
    assert "ai_use_disclosure" in missing


def test_backtick_code_refs_exempt_from_slug_check() -> None:
    """Universal regression: code refs like `methods_pack.json` inside
    backticks must NOT trip the public-slug artifact check, which is
    designed to catch raw pipeline identifiers in prose."""
    paper = _paper("| Smith 2024 | endpoint | arm | 1 | mg | — |")
    paper = paper.replace(
        "## Methods\n\n",
        "## Methods\n\nAudit trail in `methods_pack.json` and `risk_of_bias.json`.\n\n",
    )
    report = evaluate_journal_surface(paper)
    assert not any(i.code == "topic_slug_artifact" for i in report.issues)


# Slice 12 — universal evidence-lane engine. Six canonical lanes
# derived from (evidence_tier, directness, source-text) triple. No
# per-topic table; works for biomedical, climate, materials, etc.


def test_derive_lane_human_rct() -> None:
    from agent.evidence_lanes import derive_lane
    assert derive_lane(
        evidence_tier="A1", directness="direct",
        title="Randomised trial of CR in adults", venue="NEJM",
    ) == "human_rct"


def test_derive_lane_animal_overrides_tier() -> None:
    """Animal keywords win over tier — Bamford 2019 is A1-direct but
    in equids → animal_preclinical, not human_rct."""
    from agent.evidence_lanes import derive_lane
    assert derive_lane(
        evidence_tier="A1", directness="direct",
        title="Caloric restriction in obese equids",
        venue="Journal of Veterinary Internal Medicine",
    ) == "animal_preclinical"


def test_derive_lane_human_rct_ignores_preclinical_background_excerpt() -> None:
    """A human protocol does not become animal evidence because its background cites mice."""
    from agent.evidence_lanes import derive_lane

    assert derive_lane(
        evidence_tier="A1",
        directness="direct",
        title="Randomized placebo-controlled trial in older adults",
        population="older adults",
        source_excerpt="Mouse studies motivated this human trial.",
    ) == "human_rct"


def test_derive_lane_human_rct_ignores_uppercase_arm_acronym() -> None:
    from agent.evidence_lanes import derive_lane

    assert derive_lane(
        evidence_tier="A1",
        directness="direct",
        title="Randomized controlled clinical trial study",
        population="adults",
        source_excerpt="The CAT intervention arm included 43 participants.",
    ) == "human_rct"


def test_derive_lane_uppercase_animal_identity_stays_preclinical() -> None:
    from agent.evidence_lanes import derive_lane

    assert derive_lane(
        evidence_tier="A1",
        directness="direct",
        title="Randomized RAT intervention study",
        source_excerpt="The intervention reduced the measured outcome.",
    ) == "animal_preclinical"


def test_derive_lane_animal_clinical_trial_excerpt_stays_preclinical() -> None:
    from agent.evidence_lanes import derive_lane

    assert derive_lane(
        evidence_tier="A1",
        directness="direct",
        title="Randomized intervention study",
        source_excerpt="A randomized controlled clinical trial in rats.",
    ) == "animal_preclinical"


def test_derive_lane_ambiguous_subject_population_does_not_override_animal() -> None:
    from agent.evidence_lanes import derive_lane

    assert derive_lane(
        evidence_tier="A1",
        directness="direct",
        title="Randomized intervention study",
        population="n=100 subjects",
        source_excerpt="Rats were randomized between interventions.",
    ) == "animal_preclinical"


def test_derive_lane_generic_a1_with_animal_only_excerpt_is_preclinical() -> None:
    from agent.evidence_lanes import derive_lane

    assert derive_lane(
        evidence_tier="A1",
        directness="direct",
        title="Randomized intervention study",
        source_excerpt="Male arctic foxes were randomized between diets.",
    ) == "animal_preclinical"


def test_derive_lane_source_excerpt_flips_generic_title() -> None:
    """Species named only in the body text (not the title) still flips the
    lane — a generic-titled study whose claim excerpt says 'arctic foxes'
    is animal_preclinical, not human_observational."""
    from agent.evidence_lanes import derive_lane
    assert derive_lane(
        evidence_tier="B2", directness="indirect",
        title="Steroidogenesis under seasonal photoperiod",
        source_excerpt="testicular steroidogenesis in male arctic foxes",
    ) == "animal_preclinical"


def test_derive_lane_review_meta() -> None:
    from agent.evidence_lanes import derive_lane
    assert derive_lane(
        evidence_tier="B1", directness="review",
        title="Systematic review of caloric restriction",
    ) == "review_meta_analysis"


def test_derive_lane_observational() -> None:
    from agent.evidence_lanes import derive_lane
    assert derive_lane(
        evidence_tier="B2", directness="indirect",
        title="Cohort of weight loss outcomes",
    ) == "human_observational"


def test_derive_lane_mechanistic() -> None:
    from agent.evidence_lanes import derive_lane
    assert derive_lane(
        evidence_tier="A2", directness="mechanistic",
        title="Gene-expression study in human muscle",
    ) == "human_mechanistic"


def test_derive_lane_fallback_background() -> None:
    """Empty/unknown inputs → background_only (don't crash)."""
    from agent.evidence_lanes import derive_lane
    assert derive_lane(
        evidence_tier=None, directness=None, title=None,
    ) == "background_only"


def test_build_lane_map_handles_dict_receipts() -> None:
    """Universal: works for both ReceiptSummary objects and
    dict-shaped manifest receipts."""
    from agent.evidence_lanes import build_lane_map
    receipts = [
        {"citation_token": "Smith 2024", "evidence_tier": "A1",
         "directness": "direct", "source_title": "RCT"},
        {"body_citation": "Jones 2022", "evidence_tier": "B1",
         "directness": "review", "source_title": "Systematic review"},
    ]
    lanes = build_lane_map(receipts)
    assert lanes == {
        "Smith 2024": "human_rct",
        "Jones 2022": "review_meta_analysis",
    }


# Slice 13 — universal reference-style renderer. Produces Vancouver
# / Harvard / APA / Cell / Nature output from one minimal record
# shape. Universal — no per-topic logic.


def test_reference_style_canonical_set() -> None:
    """5 canonical styles registered."""
    from agent.reference_styles import CANONICAL_STYLES
    assert set(CANONICAL_STYLES) == {
        "Vancouver", "Harvard", "APA", "Cell", "Nature",
    }


def test_reference_render_vancouver() -> None:
    """Vancouver: Authors. Title. Venue. Year. DOI/PMID."""
    from agent.reference_styles import ReferenceRecord, render_reference
    r = ReferenceRecord(
        citation_token="Smith 2024", title="A trial of X",
        year=2024, venue="NEJM", doi="10.1/x", pmid="12345",
        authors=("Smith",),
    )
    out = render_reference(r, "Vancouver")
    assert "Smith." in out and "A trial of X." in out and "NEJM." in out
    assert "2024." in out and "doi:10.1/x." in out and "PMID: 12345." in out


def test_reference_render_styles_differ() -> None:
    """Each canonical style produces a distinguishable string."""
    from agent.reference_styles import ReferenceRecord, render_reference, CANONICAL_STYLES
    r = ReferenceRecord(
        citation_token="Smith 2024", title="A trial of X",
        year=2024, venue="NEJM", doi="10.1/x", pmid="12345",
        authors=("Smith", "Jones"),
    )
    outs = {s: render_reference(r, s) for s in CANONICAL_STYLES}
    # Vancouver has the year as separate '.' token, Harvard/APA use (year)
    assert "(2024)" in outs["Harvard"]
    assert "(2024)." in outs["APA"]
    assert "(2024)." in outs["Cell"]
    # All distinct
    assert len({outs[s] for s in CANONICAL_STYLES}) >= 4


def test_reference_unknown_style_falls_back_to_vancouver() -> None:
    """Unknown / None style defaults to Vancouver (biomedical default)."""
    from agent.reference_styles import ReferenceRecord, render_reference
    r = ReferenceRecord(
        citation_token="Smith 2024", title="T", year=2024,
        venue="J", doi=None, pmid=None,
    )
    assert render_reference(r, None) == render_reference(r, "Vancouver")
    assert render_reference(r, "made-up") == render_reference(r, "Vancouver")


def test_reference_style_consistency_flags_stub_form() -> None:
    """When a journal style is declared, plain `**Smith 2024.**` bold-
    marker entries are flagged as pre-render stubs."""
    from agent.reference_styles import reference_style_consistency_issue_messages
    refs_body = (
        "- **Smith 2024.** 2024. DOI: 10.1/x. PMID: 12345.\n"
        "- **Jones 2023.** 2023. DOI: 10.2/y. PMID: 67890.\n"
    )
    issues = reference_style_consistency_issue_messages(refs_body, "Vancouver")
    assert issues and "pre-render stub" in issues[0]


def test_reference_style_consistency_skipped_when_no_style() -> None:
    """No declared style → no check fires."""
    from agent.reference_styles import reference_style_consistency_issue_messages
    refs_body = "- **Smith 2024.** 2024. DOI: 10.1/x.\n"
    assert reference_style_consistency_issue_messages(refs_body, None) == ()
    assert reference_style_consistency_issue_messages(refs_body, "") == ()


# Slice 14 — universal artifact consistency verifier. Kills the
# stale-PDF / desync-supplement reviewer trap. Pure-structural,
# no per-topic knowledge.


def test_artifact_consistency_fails_when_required_artifacts_are_missing(tmp_path) -> None:
    from agent.artifact_consistency import verify_run_artifacts
    (tmp_path / "full_paper.md").write_text("## Abstract\n\nText.\n")
    report = verify_run_artifacts(tmp_path)
    assert not report.passed
    assert any(c.name == "paper_present" and c.passed for c in report.checks)
    assert not any(c.name == "submission_package_match" for c in report.checks)
    assert any(c.name == "citation_registry_coverage" and not c.passed for c in report.checks)
    assert any(c.name == "citation_registry_coverage" and not c.passed for c in report.checks)


def test_artifact_consistency_passes_complete_trust_artifacts(tmp_path) -> None:
    import json as _json
    from agent.artifact_consistency import verify_run_artifacts
    paper = "## Abstract\n\nSmith 2024 reported.\n\n## References\n\n- Smith 2024.\n"
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "submission_package").mkdir()
    (tmp_path / "submission_package" / "final_manuscript.md").write_text(paper)
    (tmp_path / "citation_registry.json").write_text(_json.dumps({
        "R1": {"body_citation": "Smith 2024"},
    }))
    assert verify_run_artifacts(tmp_path).passed


def test_artifact_consistency_flags_missing_paper(tmp_path) -> None:
    """Run dir without full_paper.md → immediate fail."""
    from agent.artifact_consistency import verify_run_artifacts
    report = verify_run_artifacts(tmp_path)
    assert not report.passed
    assert report.checks[0].name == "paper_present"


def test_artifact_consistency_detects_submission_drift(tmp_path) -> None:
    """When submission_package/final_manuscript.md drifts from
    full_paper.md → flag."""
    from agent.artifact_consistency import verify_run_artifacts
    (tmp_path / "full_paper.md").write_text("## Abstract\n\nOriginal.\n")
    (tmp_path / "submission_package").mkdir()
    (tmp_path / "submission_package" / "final_manuscript.md").write_text(
        "## Abstract\n\nStale supplement copy.\n",
    )
    report = verify_run_artifacts(tmp_path)
    assert not report.passed
    assert any(
        c.name == "submission_package_match" and not c.passed
        for c in report.checks
    )


def test_artifact_consistency_canonicalises_whitespace(tmp_path) -> None:
    """Cosmetic whitespace/bullet-marker differences between the
    submission mirror and the source must NOT trip the gate —
    canonicalisation strips them."""
    from agent.artifact_consistency import verify_run_artifacts
    body = "## Abstract\n\nA result is reported.\n"
    spaced = "## Abstract\n\nA   result   is reported.\n"  # whitespace runs
    (tmp_path / "full_paper.md").write_text(body)
    (tmp_path / "submission_package").mkdir()
    (tmp_path / "submission_package" / "final_manuscript.md").write_text(spaced)
    report = verify_run_artifacts(tmp_path)
    assert any(
        c.name == "submission_package_match" and c.passed
        for c in report.checks
    )


def test_artifact_consistency_flags_orphan_registry_entries(tmp_path) -> None:
    """citation_registry entry whose body_citation never appears in
    the body's References section → flag (the renovar 2023 / Hernndez
    2024 failure mode)."""
    import json as _json
    from agent.artifact_consistency import verify_run_artifacts
    (tmp_path / "full_paper.md").write_text(
        "## Abstract\n\nSmith 2024 reported.\n\n"
        "## References\n\n- **Smith 2024.** 2024.\n",
    )
    (tmp_path / "citation_registry.json").write_text(_json.dumps({
        "rid-1": {"body_citation": "Smith 2024"},
        "rid-2": {"body_citation": "Ghost 2099"},  # not in refs
    }))
    report = verify_run_artifacts(tmp_path)
    assert any(
        c.name == "citation_registry_coverage" and not c.passed
        for c in report.checks
    )


def test_artifact_consistency_sidecar_round_trip(tmp_path) -> None:
    """write_consistency_sidecar persists the report; the JSON shape
    is final-status-readable (top-level `passed` + `checks` list)."""
    import json as _json
    from agent.artifact_consistency import (
        verify_run_artifacts, write_consistency_sidecar,
    )
    (tmp_path / "full_paper.md").write_text("## Abstract\n\nOK.\n")
    report = verify_run_artifacts(tmp_path)
    path = write_consistency_sidecar(tmp_path, report)
    payload = _json.loads(path.read_text())
    assert "passed" in payload and "checks" in payload
    assert payload["passed"] == report.passed
    assert len(payload["checks"]) == len(report.checks)


def test_artifact_consistency_fails_when_docx_extractor_is_unavailable(tmp_path, monkeypatch) -> None:
    from agent import artifact_consistency as ac
    (tmp_path / "full_paper.md").write_text("## Abstract\n\nOK.\n")
    (tmp_path / "full_paper.docx").write_bytes(b"not parsed without optional dependency")
    monkeypatch.setattr(ac, "_extract_docx_text", lambda _p: (_ for _ in ()).throw(ImportError("No module named 'docx'")))
    report = ac.verify_run_artifacts(tmp_path)
    assert report.passed is False
    assert any(c.name == "docx_extracted" and not c.passed for c in report.checks)


# Slice 15 — writer-compliance scrubber. The deterministic post-render
# helper that turns the writer's leaked pipeline jargon into the
# academic-language equivalents. Universal — no per-topic logic.


def test_apply_pipeline_jargon_replacements_swaps_all() -> None:
    """Every entry in _PIPELINE_JARGON_PUBLIC gets substituted in
    the body — single source of truth for the writer-compliance pass."""
    from agent.journal_surface_gate import (
        apply_pipeline_jargon_replacements, _PIPELINE_JARGON_PUBLIC,
    )
    body = "\n".join(
        f"## Section {i}\n\n{jargon} appears in prose."
        for i, (jargon, _) in enumerate(_PIPELINE_JARGON_PUBLIC)
    )
    out = apply_pipeline_jargon_replacements(body)
    for jargon, replacement in _PIPELINE_JARGON_PUBLIC:
        assert jargon not in out.lower(), f"left {jargon!r} in body"
        # The replacement text appears in the output (may include
        # other tokens as substrings).
        if replacement.lower() not in (j for j, _ in _PIPELINE_JARGON_PUBLIC):
            assert replacement.lower() in out.lower(), f"missing replacement for {jargon!r}"


def test_apply_pipeline_jargon_replacements_longest_wins() -> None:
    """Longest pattern replaces first so 'source-bound observation'
    becomes 'extracted quantitative finding', not 'extracted
    observation' (which would happen if 'source-bound' alone matched
    first)."""
    from agent.journal_surface_gate import apply_pipeline_jargon_replacements
    text = "The source-bound observation set was retained."
    out = apply_pipeline_jargon_replacements(text)
    assert "extracted quantitative finding" in out
    assert "source-bound" not in out.lower()


def test_apply_pipeline_jargon_replacements_idempotent() -> None:
    """Running twice → same result. Post-render scrubber must be safe
    to re-apply (e.g. consistency-audit loop runs may re-scrub)."""
    from agent.journal_surface_gate import apply_pipeline_jargon_replacements
    text = "The source-bound observation set was retained. Endpoint proximity matters."
    once = apply_pipeline_jargon_replacements(text)
    twice = apply_pipeline_jargon_replacements(once)
    assert once == twice


def test_apply_pipeline_jargon_replacements_scrubs_receipt_artifacts() -> None:
    from agent.journal_surface_gate import apply_pipeline_jargon_replacements
    text = (
        "The accepted receipt graph retained 171 receipts for this synthesis. "
        "Classified receipt candidates were reviewed in the Receipt admission funnel "
        "before final receipt admission. The accepted corpus was then rendered."
    )
    out = apply_pipeline_jargon_replacements(text)
    assert "receipt" not in out.lower()
    assert "accepted corpus" not in out.lower()
    assert "included source set" in out.lower()
    assert "171 sources" in out.lower()
    assert "source candidates" in out.lower()
    assert "source admission funnel" in out.lower()
    assert "final source admission" in out.lower()


def test_apply_pipeline_jargon_replacements_preserves_plain_english_receipt() -> None:
    from agent.journal_surface_gate import apply_pipeline_jargon_replacements
    text = "The receipt of treatment was recorded in routine clinical records."
    assert apply_pipeline_jargon_replacements(text) == text


def test_apply_pipeline_jargon_replacements_respects_token_boundaries() -> None:
    from agent.journal_surface_gate import apply_pipeline_jargon_replacements
    text = "The source-bounded conclusion stays within the evidence."
    assert apply_pipeline_jargon_replacements(text) == text


# Slice 16 — agent/journal_finalizer.py. Single deterministic
# compiler-owned post-render pass. Five phases (Methods replace /
# lane qualifier / terminology / reference closure / structural
# fallback). Universal — runs on every fresh pipeline finish.


def test_finalizer_no_paper_no_change(tmp_path) -> None:
    """Run dir without full_paper.md → empty report, no crash."""
    from agent.journal_finalizer import finalize_run
    report = finalize_run(tmp_path)
    assert not report.paper_changed
    assert report.entries == ()


def test_finalizer_phase_d_reference_closure(tmp_path) -> None:
    """Orphan refs in bibliography → finalizer appends a supporting-
    corpus cluster citing them. Universal — no topic-specific logic."""
    from agent.journal_finalizer import finalize_run
    from agent.journal_surface_gate import orphan_reference_tokens
    paper = (
        "## Abstract\n\nSmith 2024 reported.\n\n"
        "## References\n\n"
        "- **Smith 2024.** 2024.\n"
        "- **GhostA 2099.** 2099.\n"
        "- **GhostB 2100.** 2100.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    # Stub the other sidecars finalizer reads (all fail-soft when absent)
    report = finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()
    assert report.paper_changed
    assert orphan_reference_tokens(new_text) == ()
    # Cluster mentions both ghosts
    assert "GhostA 2099" in new_text
    assert "GhostB 2100" in new_text


def test_finalizer_phase_e_inserts_thesis_marker(tmp_path) -> None:
    """Discussion without **Thesis:** + manifest thesis → marker
    inserted at start of Discussion."""
    import json as _json
    from agent.journal_finalizer import finalize_run
    paper = (
        "## Abstract\n\nA.\n\n"
        "## Methods\n\nM.\n\n"
        "## Results\n\nR.\n\n"
        "## Discussion\n\nFreeform discussion prose only.\n\n"
        "## Limitations\n\nL.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "manifest.json").write_text(_json.dumps({
        "topic": "demo",
        "review_type": "thin_corpus_brief",
        "thesis": "X improves Y but not Z in human RCTs.",
    }))
    (tmp_path / "full_paper.audit.json").write_text(_json.dumps({
        "checks": [{"name": "Q8_thesis_present", "passed": False}],
    }))
    report = finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()
    assert report.paper_changed
    assert "**Thesis:**" in new_text
    assert "X improves Y but not Z in human RCTs." in new_text
    refreshed = _json.loads((tmp_path / "full_paper.audit.json").read_text())
    q8 = next(c for c in refreshed["checks"] if c["name"] == "Q8_thesis_present")
    assert q8["passed"] is True


def test_finalizer_preserves_inserted_thesis_after_noise_dedupe(tmp_path) -> None:
    """A thesis marker may repeat Abstract wording; noise-control dedupe
    must not delete the required Discussion marker."""
    import json as _json
    from agent.journal_finalizer import finalize_run

    thesis = "The evidence remains bounded and should not support broad clinical claims."
    paper = (
        f"## Abstract\n\n{thesis}\n\n"
        "## Methods\n\nM.\n\n"
        "## Results\n\nR.\n\n"
        "## Discussion\n\nFreeform discussion prose only.\n\n"
        "## Limitations\n\nL.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "manifest.json").write_text(_json.dumps({"topic": "demo", "thesis": thesis}))

    finalize_run(tmp_path)

    new_text = (tmp_path / "full_paper.md").read_text()
    assert "**Thesis:**" in new_text
    assert thesis in new_text


def test_finalizer_phase_e_softens_we_propose(tmp_path) -> None:
    """Ungrounded 'we propose' (no inline citation in same paragraph)
    → softened to 'we operationalize' (a non-novelty-claim phrasing)."""
    from agent.journal_finalizer import finalize_run
    paper = (
        "## Abstract\n\nA.\n\n"
        "## Discussion\n\n**Thesis:** X.\n\n"
        "We propose a comprehensive integrative framework here.\n\n"
        "## Limitations\n\nL.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    report = finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()
    assert "we propose" not in new_text.lower() or "we operationalize" in new_text.lower()
    assert any(
        e.rule == "soften_we_propose" for e in report.entries
    )


def test_finalizer_phase_e_softens_unsupported_novelty_variants(tmp_path) -> None:
    """Ungrounded novelty variants like 'novel approach' are compiler-fixable."""
    from agent.journal_finalizer import finalize_run
    paper = (
        "## Abstract\n\nA.\n\n"
        "## Discussion\n\n**Thesis:** X.\n\n"
        "This novel approach organizes the evidence without claiming treatment guidance.\n\n"
        "## Limitations\n\nL.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    report = finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()
    assert "novel approach" not in new_text.lower()
    assert "structured approach" in new_text.lower()
    assert any(e.rule == "soften_unsupported_novelty" for e in report.entries)
    assert not any(
        i.code == "unsupported_novelty"
        for i in evaluate_journal_surface(new_text).issues
    )


def test_finalizer_iterates_until_deterministic_surface_repairs_converge(tmp_path, monkeypatch) -> None:
    """If a later deterministic phase introduces a surface issue, finalize_run
    should fix it in the same call instead of waiting for a full re-synthesis."""
    import json as _json
    import agent.journal_finalizer as finalizer
    from agent.methods_pack import build_methods_pack, write_methods_pack

    row = "| Smith 2024 | fasting glucose | treatment | 89 mg/dL | mg/dL | mean |"
    (tmp_path / "full_paper.md").write_text(_paper(row))
    (tmp_path / "manifest.json").write_text(_json.dumps({"review_type": "thin_corpus_brief"}))
    write_methods_pack(
        tmp_path,
        build_methods_pack(
            review_type="thin_corpus_brief",
            topic="glucose variability",
            corpus_search_queries=("glucose variability aging",),
            n_retrieved=20,
            n_screened=12,
            n_included=10,
            n_rejected=2,
            outcome_classes=("cardiometabolic",),
            search_dates_iso="2026-05-28",
        ),
    )
    calls = 0

    def late_novelty_phase(text, _out_dir):
        nonlocal calls
        calls += 1
        if calls > 1:
            return text, []
        patched = text.replace(
            "## Limitations",
            "This novel approach remains a synthesis-only framing.\n\n## Limitations",
        )
        return patched, [
            finalizer.FinalizerLogEntry(
                "F_reconcile_results_table",
                "test_late_surface_issue",
                1,
                "introduced a late deterministic surface issue",
            )
        ]

    monkeypatch.setattr(finalizer, "_phase_f_reconcile_results_table", late_novelty_phase)
    monkeypatch.setattr(finalizer, "_phase_l_strengthen_analytical_sections", lambda text, _out_dir: (text, []))

    report = finalizer.finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()

    assert calls == 3
    assert report.paper_changed
    assert "novel approach" not in new_text.lower()
    assert "structured approach" in new_text.lower()
    assert any(e.rule == "soften_unsupported_novelty" for e in report.entries)
    assert evaluate_journal_surface(
        new_text,
        animal_citations=[],
        citation_outcome_map={},
        declared_review_type="thin_corpus_brief",
    ).passed


def test_finalizer_idempotent(tmp_path) -> None:
    """Re-running the finalizer must not double-patch. Required so a
    re-run of run_v06_synthesis on the same out_dir is safe."""
    from agent.journal_finalizer import finalize_run
    paper = (
        "## Abstract\n\nSmith 2024 reported.\n\n"
        "## References\n\n- **Smith 2024.** 2024.\n- **Ghost 2099.** 2099.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    finalize_run(tmp_path)
    first_text = (tmp_path / "full_paper.md").read_text()
    first_report = (tmp_path / "journal_finalizer.json").read_text()
    second_report = finalize_run(tmp_path)
    second_text = (tmp_path / "full_paper.md").read_text()
    assert first_text == second_text
    assert second_report.entries == ()
    assert (tmp_path / "journal_finalizer.json").read_text() == first_report


def test_finalizer_reaches_text_fixed_point_before_return(tmp_path, monkeypatch) -> None:
    from agent import journal_finalizer as finalizer

    calls = 0

    def staged(text: str, _out_dir):
        nonlocal calls
        calls += 1
        return {"A": "B", "B": "C"}.get(text, text), []

    (tmp_path / "full_paper.md").write_text("A")
    monkeypatch.setattr(finalizer, "_run_text_phases", staged)
    report = finalizer.finalize_run(tmp_path)

    assert calls == 3
    assert report.paper_changed
    assert (tmp_path / "full_paper.md").read_text() == "C"


def test_finalizer_reprocesses_phase_g_paper_mutation(tmp_path, monkeypatch) -> None:
    from agent import journal_finalizer as finalizer

    (tmp_path / "full_paper.md").write_text("A")
    phase_g_calls = 0

    def text_phases(text: str, _out_dir):
        return text.replace("G", "FINAL"), []

    def phase_g(out_dir):
        nonlocal phase_g_calls
        phase_g_calls += 1
        if phase_g_calls == 1:
            (out_dir / "full_paper.md").write_text("G")
        return []

    monkeypatch.setattr(finalizer, "_run_text_phases", text_phases)
    monkeypatch.setattr(finalizer, "_phase_g_refresh_sidecars", phase_g)
    report = finalizer.finalize_run(tmp_path)

    assert report.paper_changed
    assert report.final_word_count == 1
    assert phase_g_calls == 3
    assert (tmp_path / "full_paper.md").read_text() == "FINAL"


def test_finalizer_writes_repair_log_sidecar(tmp_path) -> None:
    """Finalizer always writes journal_finalizer.json sidecar — used
    by downstream audit and reviewer to see what was patched."""
    import json as _json
    from agent.journal_finalizer import finalize_run
    (tmp_path / "full_paper.md").write_text("## Abstract\n\nA.\n")
    finalize_run(tmp_path)
    path = tmp_path / "journal_finalizer.json"
    assert path.is_file()
    payload = _json.loads(path.read_text())
    assert "paper_changed" in payload and "entries" in payload


# Slice 16-F — Results-table reconciliation. When a `### X Outcomes`
# subsection exists but the Results table doesn't declare X, derive
# a row from manifest receipts and append. Universal — no per-topic
# knowledge; row content comes from the receipt data the run already
# has.


def test_finalizer_phase_f_appends_missing_outcome_row(tmp_path) -> None:
    """Subsection 'Mechanism' exists, table lacks the row → finalizer
    appends a row derived from manifest receipts."""
    import json as _json
    from agent.journal_finalizer import finalize_run
    paper = (
        "## Abstract\n\nA.\n\n"
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Longevity | n=2; claims=10 | mixed | 1 direct | x |\n"
        "\n"
        "### Longevity Outcomes\n\nText.\n\n"
        "### Mechanism Outcomes\n\nDai 2014 reports proteome turnover.\n\n"
        "## Discussion\n\nD.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "manifest.json").write_text(_json.dumps({
        "receipts": [
            {"outcome_class": "longevity", "directness": "direct",
             "effect_direction": "positive", "n_claims": 5},
            {"outcome_class": "longevity", "directness": "indirect",
             "effect_direction": "mixed", "n_claims": 5},
            {"outcome_class": "mechanism", "directness": "review",
             "effect_direction": "positive", "n_claims": 2},
        ],
    }))
    report = finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()
    assert report.paper_changed
    # Row added with derived counts
    assert "| Mechanism | n=1; claims=2" in new_text
    assert any(
        e.phase == "F_reconcile_results_table"
        and e.rule == "rebuild_results_summary_table"
        for e in report.entries
    )


def test_finalizer_phase_f_skips_when_table_already_complete(tmp_path) -> None:
    """All H3 subsections declared in Results table → Phase F adds
    nothing. Universal."""
    import json as _json
    from agent.journal_finalizer import finalize_run
    paper = (
        "## Abstract\n\nA.\n\n"
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Longevity | n=2 | mixed | 1 direct | x |\n"
        "\n"
        "### Longevity Outcomes\n\nText.\n\n"
        "## Discussion\n\nD.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "manifest.json").write_text(_json.dumps({"receipts": []}))
    report = finalize_run(tmp_path)
    assert not any(
        e.phase == "F_reconcile_results_table" for e in report.entries
    )


def test_finalizer_phase_f_adds_missing_outcome_subsections(tmp_path) -> None:
    import json as _json
    from agent.journal_finalizer import finalize_run
    paper = (
        "## Abstract\n\nA.\n\n"
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Longevity | n=1 | mixed | 1 direct | x |\n\n"
        "### Longevity Outcomes\n\nL.\n\n"
        "## Discussion\n\nD.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "manifest.json").write_text(_json.dumps({
        "receipts": [
            {"outcome_class": "longevity", "directness": "direct",
             "effect_direction": "positive", "n_claims": 1},
            {"outcome_class": "frailty", "directness": "direct",
             "effect_direction": "mixed", "n_claims": 2},
        ],
    }))
    finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()
    assert "| Frailty | n=1; claims=2" in new_text
    assert "### Frailty Outcomes" in new_text


def test_finalizer_closes_orphan_references_terminally(tmp_path) -> None:
    """Orphan-reference closure must survive every later section rebuild.

    Regression for the 2026-06-11 publish stall: the in-loop closure inserted
    an inline supporting-corpus cluster, but surface-floor/structural rebuilds
    that ran afterwards dropped it, so the gate still saw bibliography entries
    as uncited. The terminal closure pass guarantees the cluster persists.
    """
    import json as _json
    from agent.journal_finalizer import finalize_run
    from agent.journal_surface_gate import orphan_reference_tokens
    (tmp_path / "audit").mkdir()
    # A body that cites nobody + a References section listing two papers ->
    # both are orphans until the closure cluster is appended inline.
    (tmp_path / "full_paper.md").write_text(
        "## Abstract\n\n" + ("alpha " * 60) + "\n\n"
        "## Discussion\n\n" + ("discussion " * 60) + "\n\n"
        "## References\n\n"
        "- **Zarate 2019.** A mitochondrial peptide study. DOI: 10.1/x.\n"
        "- **Okada 2017.** Another corpus source. DOI: 10.2/y.\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(_json.dumps({"receipts": []}), encoding="utf-8")
    assert len(orphan_reference_tokens((tmp_path / "full_paper.md").read_text())) == 2
    finalize_run(tmp_path)
    final = (tmp_path / "full_paper.md").read_text()
    assert orphan_reference_tokens(final) == ()
    assert "catalogued for completeness" in final


def test_finalizer_load_bearing_tensions_are_public_safe(tmp_path) -> None:
    import json as _json
    from agent.journal_finalizer import finalize_run
    (tmp_path / "audit").mkdir()
    (tmp_path / "full_paper.md").write_text(
        "## Abstract\n\nA.\n\n"
        "## Cross-Domain Synthesis\n\nA 2026 and B 2026 disagree on dosing.\n\n"
        + ("context --- " * 500)
        + "\n\n"
        "## Discussion\n\nD.\n"
    )
    (tmp_path / "manifest.json").write_text(_json.dumps({"receipts": []}))
    (tmp_path / "audit" / "tension_elaboration_plans.json").write_text(_json.dumps({
        "plans": [
            {
                "paper_a": "A 2026",
                "paper_b": "B 2026",
                "outcome_class": "dosing_pharmacokinetics",
                "conflict_type": "disagreement",
                "severity": 4,
                "numeric_anchors": {"p = 0.002": 1},
                "hypotheses": ["dose-regime difference"],
            },
            {
                # Papers the document never cites: the row must be dropped,
                # or it would trip the unreferenced-citation gate.
                "paper_a": "Uncited 2025",
                "paper_b": "Ghost 2024",
                "outcome_class": "other",
                "conflict_type": "null_vs_positive",
                "severity": 3,
                "hypotheses": ["x"],
            },
        ],
    }))
    finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()
    assert "Dosing and Pharmacokinetics" in new_text
    assert "dosing_pharmacokinetics" not in new_text
    assert "0.002" not in new_text
    assert "severity 4" not in new_text
    assert "null_vs_positive" not in new_text
    assert "Uncited 2025" not in new_text and "Ghost 2024" not in new_text


def test_finalizer_phase_m_applies_general_review_noise_controls(tmp_path) -> None:
    import json as _json
    from agent.journal_finalizer import finalize_run

    repeated_table = (
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Contextual Other | n=26; claims=1346 | adjacent context |\n"
    )
    duplicate_qei = (
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Smith 2024 | glucose | treatment | 89 mg/dL | mg/dL | mean |\n"
        "| Smith 2024 | glucose | treatment | 91 mg/dL | mg/dL | mean |\n"
    )
    repeated_methods = (
        "The search protocol used identical eligibility checks, extraction rules, "
        "and reviewer weighting before synthesis.\n"
    )
    repeated_finding = (
        "Key findings repeated verbatim across sections with enough words to "
        "trigger the duplicate-block guard before submission to review using "
        "overlapping language about source weighting and table interpretation.\n"
    )
    near_finding = repeated_finding.replace("submission to review", "submission to peer review")
    front_matter_recap = (
        "This front matter deliberately recaps the same evidence profile using "
        "enough shared tokens that body-dedupe must not delete it from the "
        "abstract or introduction sections before journal surface evaluation.\n"
    )
    paper = (
        f"## Abstract\n\n{front_matter_recap}\n"
        f"## Introduction\n\n{front_matter_recap}\n"
        "## Methods\n\n"
        f"### Search\n\n{repeated_methods}\n"
        f"### Screening\n\n{repeated_methods}\n"
        "## Results\n\n"
        f"{duplicate_qei}\n"
        f"{repeated_table}\n{repeated_table}\n"
        f"{repeated_finding}\n{near_finding}\n"
        "## Cross-Domain Synthesis\n\n"
        "| Pair | Kind | Severity | Interpretation |\n"
        "|---|---|---|---|\n"
        "| A-B | agreement | 1 | minor same-direction context |\n"
        "| C-D | null_vs_positive | 3 | notable tension |\n"
        "| E-F | disagreement | 5 | load-bearing disagreement |\n\n"
        "## Limitations\n\nL.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "citation_registry.json").write_text(_json.dumps({
        "r1": {"body_citation": "Smith 2024", "title": None, "source_journal": None},
    }))

    report = finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()
    rules = {entry.rule for entry in report.entries}

    assert "Contextual Other" not in new_text
    assert "Contextual Adjacent Evidence" in new_text
    assert new_text.count("This front matter deliberately recaps") == 2
    assert "not pooled with direct outcome evidence" not in new_text
    assert "these sources bound scope, safety, methods, and translation" not in new_text
    assert new_text.count("| Smith 2024 | glucose | treatment |") == 1
    assert new_text.count("Key findings repeated verbatim") == 1
    assert new_text.count("The search protocol used identical eligibility checks") == 1
    assert "minor same-direction context" not in new_text
    assert "notable tension" in new_text
    assert "load-bearing disagreement" in new_text
    assert "verification-limited context" in new_text
    assert {
        "rename_contextual_other",
        "dedupe_repeated_blocks",
        "dedupe_duplicate_table_rows",
        "dedupe_repeated_h3_blocks",
        "trim_low_value_cross_domain_rows",
        "flag_verification_limited_sources",
    } <= rules


def test_finalizer_phase_m_adds_requested_clinical_policy_caveat(tmp_path) -> None:
    import json as _json
    from agent.journal_finalizer import finalize_run

    paper = (
        "## Abstract\n\nEvidence is mixed.\n\n"
        "## Results\n\nR.\n\n"
        "## Conclusion\n\nThe synthesis remains provisional.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "researka_revision_request.json").write_text(_json.dumps({
        "feedback": "Add a clear caveat that clinical or policy use is not supported.",
    }))

    report = finalize_run(tmp_path)
    new_text = (tmp_path / "full_paper.md").read_text()

    assert new_text.count("does not support clinical or policy use") == 2
    assert any(entry.rule == "add_clinical_policy_caveat" for entry in report.entries)


def test_finalizer_phase_f_idempotent(tmp_path) -> None:
    """Second finalizer run must not re-add the same row. The new
    row from the first run now satisfies the gate, so Phase F is a
    no-op the second time."""
    import json as _json
    from agent.journal_finalizer import finalize_run
    paper = (
        "## Abstract\n\nA.\n\n"
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Longevity | n=1 | mixed | 1 direct | x |\n"
        "\n"
        "### Longevity Outcomes\n\nL.\n\n"
        "### Mechanism Outcomes\n\nM.\n\n"
        "## Discussion\n\nD.\n"
    )
    (tmp_path / "full_paper.md").write_text(paper)
    (tmp_path / "manifest.json").write_text(_json.dumps({
        "receipts": [
            {"outcome_class": "longevity", "directness": "direct",
             "effect_direction": "positive", "n_claims": 1},
            {"outcome_class": "mechanism", "directness": "review",
             "effect_direction": "positive", "n_claims": 1},
        ],
    }))
    finalize_run(tmp_path)
    first = (tmp_path / "full_paper.md").read_text()
    finalize_run(tmp_path)
    second = (tmp_path / "full_paper.md").read_text()
    # The Phase F Mechanism row appears exactly once in the Results overview table after re-runs.
    first_results_table = first.split("## Results", 1)[1].split("### Longevity Outcomes", 1)[0]
    second_results_table = second.split("## Results", 1)[1].split("### Longevity Outcomes", 1)[0]
    assert first_results_table.count("| Mechanism |") == 1
    assert second_results_table.count("| Mechanism |") == 1


def test_slice35_thin_corpus_brief_does_not_flag_missing_long_form_sections() -> None:
    """Slice 35: when manifest declares review_type=thin_corpus_brief
    (Slice 31 downshift), the gate must not flag Introduction / Background
    / Cross-Domain Synthesis / Discussion as missing — Phase J intentionally
    trims those. Universal — applies to any thin-corpus run regardless of
    domain (biomedical, climate, materials)."""
    from agent.journal_surface_gate import _section_issue_messages
    brief = (
        "## Abstract\n\n" + ("alpha " * 110) + "\n\n"
        "## Methods\n\n" + ("beta " * 210) + "\n\n"
        "## Results\n\n" + ("gamma " * 210) + "\n\n"
        "## Limitations\n\n" + ("delta " * 90) + "\n\n"
        "## Conclusion\n\n" + ("epsilon " * 90) + "\n"
    )
    issues = _section_issue_messages(brief, declared_review_type="thin_corpus_brief")
    missing = [i for i in issues if i.startswith("missing required section:")]
    # No long-form sections flagged as missing
    for token in ("Introduction", "Background", "Cross-Domain Synthesis", "Discussion"):
        assert not any(token in m for m in missing), (
            f"thin_corpus_brief should not require {token!r}; got: {missing}"
        )
    # Sanity: same paper under full review_type WOULD flag those as missing
    full_issues = _section_issue_messages(brief, declared_review_type="prisma_scr_scoping_synthesis")
    full_missing = [i for i in full_issues if i.startswith("missing required section:")]
    assert any("Introduction" in m for m in full_missing)
    assert any("Discussion" in m for m in full_missing)


def test_slice35_thin_corpus_brief_still_enforces_minimum_sections() -> None:
    """Slice 35: thin_corpus_brief still requires the structural-evidence
    minimum: Abstract, Methods, Results, Limitations, Conclusion."""
    from agent.journal_surface_gate import _section_issue_messages
    # Paper missing Methods + Results
    paper = (
        "## Abstract\n\n" + ("alpha " * 110) + "\n\n"
        "## Limitations\n\n" + ("delta " * 90) + "\n\n"
        "## Conclusion\n\n" + ("epsilon " * 90) + "\n"
    )
    issues = _section_issue_messages(paper, declared_review_type="thin_corpus_brief")
    missing = [i for i in issues if i.startswith("missing required section:")]
    assert any("Methods" in m for m in missing)
    assert any("Results" in m for m in missing)


def test_outcome_sections_key_on_outcome_not_topic_anchor() -> None:
    """The results table anchors its Outcome class cell; headings do not.

    The table renders "<topic anchor> / <outcome>" while the matching H3 carries
    the bare outcome. Comparing them verbatim reported the SAME section as both
    missing and unexpected, turning one real fault into eleven and preventing
    the finalizer repair loop from ever reaching a fixed point.
    """
    from agent.journal_surface_gate import _outcome_key

    assert _outcome_key("Liraglutide Adverse Effects / Cardiometabolic") == _outcome_key(
        "Cardiometabolic Outcomes",
    )
    # A bare outcome with no anchor must still key to itself.
    assert _outcome_key("Safety") == _outcome_key("Safety Outcomes")
    # Distinct outcomes must NOT collide just because they share an anchor.
    assert _outcome_key("Topic X / Safety") != _outcome_key("Topic X / Longevity")


def test_animal_citation_in_data_table_is_not_flagged_unlabelled() -> None:
    """A stats table is not prose and carries no lane column by design.

    The quantitative-evidence table is Study/Endpoint/Arm/Value/Type/Statistic,
    so every animal citation inside it was reported as an unlabelled paragraph.
    That blocked a 28/30 paper on a formatting artefact while the prose was
    correctly labelled.
    """
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages
    paper = (
        "## Results\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Simon 2024 | cognition | nad | P = 0.03 | p-value | - |\n"
    )
    assert not _unlabeled_animal_citation_issue_messages(paper, ["Simon 2024"])


def test_animal_citation_in_unlabelled_prose_is_still_flagged() -> None:
    """The guard must still catch prose presenting animal data as human."""
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages
    paper = (
        "## Results\n\n"
        "Cognitive function improved substantially (Simon 2024), supporting "
        "the primary endpoint across the cohort.\n"
    )
    assert _unlabeled_animal_citation_issue_messages(paper, ["Simon 2024"])
