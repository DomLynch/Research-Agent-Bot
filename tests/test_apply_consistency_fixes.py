from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
fixes: Any = importlib.import_module("apply_consistency_fixes")
noise: Any = importlib.import_module("review_noise_control")


def test_public_snake_case_labels_normalize_in_body_only() -> None:
    paper = (
        "## Discussion\n\n"
        "The intervention remains a nutritional_supplement with a p_value label.\n\n"
        "## Publication Appendix\n\n"
        "`nutritional_supplement` may remain in machine metadata.\n"
    )
    new_md, n = fixes._normalize_public_snake_case_labels(paper)
    assert n == 2
    assert "nutritional supplement" in new_md
    assert "p-value label" in new_md
    assert "`nutritional_supplement` may remain" in new_md


def test_valid_d1_block_accepts_public_mechanism_anchor_tag() -> None:
    block = (
        "1. [D1_inferential_bridge | confidence=low] Conserved pathway logic. "
        "[mechanism anchor: A 2020] [conservation: B 2021]\n"
        "Testability: Run validation. [testability: explicit]"
    )
    assert fixes._valid_d1_block(block)


def test_lightweight_polish_journalizes_public_counter_terms() -> None:
    paper = (
        "## Cross-Domain Synthesis\n\n"
        "Across the 47 accepted sources, the effect-direction distribution "
        "from SPAR-adjudicated sources was mixed. The corpus's tension matrix "
        "contains 1081 pairwise tensions across the source set, of which 237 "
        "were classified as severe (severity >=3). These non-orthogonal "
        "tensions define the framework.\n\n"
        "## References\n\nDOI: 10.1/example.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(
        paper, manifest={"n_non_orthogonal_tensions": 366},
    )
    assert "accepted sources" not in out
    assert "SPAR-adjudicated sources" not in out
    assert "tension matrix" not in out
    assert "1081 pairwise comparisons" in out
    assert "237 severe comparisons" in out
    assert "366 public cross-study disagreements" in out
    assert "DOI: 10.1/example." in out
    assert any(i["fix_type"] == "public_evidence_term_normalization" for i in log)


def test_lightweight_polish_repairs_connector_punctuation() -> None:
    paper = (
        "## Discussion\n\n"
        "These findings, suggest caution.\n\n"
        "## References\n\n"
        "- Smith 2024.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "These findings suggest caution." in out
    assert "These findings, suggest caution." not in out
    assert any(i["fix_type"] == "connector_punctuation_repair" for i in log)


def test_review_noise_dedupes_rows_across_two_duplicate_heading_tables(tmp_path: Path) -> None:
    table = (
        "## Table 1: Included Studies\n\n"
        "| Study | Endpoint | Arm | Value |\n"
        "|---|---|---|---|\n"
        "| Smith 2024 | glucose | treatment | 10 |\n"
        "| Smith 2024 | glucose | treatment | 10 |\n\n"
    )
    paper = table + "## Results\n\nInterpretation.\n\n" + table
    out, changes = noise.apply_review_noise_control(paper, tmp_path)
    assert out.count("| Smith 2024 | glucose | treatment | 10 |") == 2
    assert any(c[0] == "dedupe_duplicate_table_rows" and c[1] == 2 for c in changes)


def test_lightweight_polish_removes_orphan_table_and_overclaim_language() -> None:
    paper = (
        "## Abstract\n\n"
        "The topic is the most robust non-pharmacological intervention for "
        "extending lifespan across species. Eligible studies were identified "
        "through systematic search.\n\n"
        "## Results\n\n"
        "Table 2 presents per-study endpoint evidence. Endpoints are "
        "summarized in Table 2.\n\n"
        "## References\n\n"
        "- Smith 2024.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "most robust non-pharmacological intervention" not in out
    assert "extending lifespan across species" not in out
    assert "one of the most extensively studied non-pharmacological intervention" in out
    assert "systematic search" not in out
    assert "structured corpus search" in out
    assert "Table 2" not in out
    assert "The synthesis presents per-study endpoint evidence" in out
    assert "summarized in the evidence synthesis" in out
    assert any(i["fix_type"] == "orphan_table_reference_normalization" for i in log)


def test_lightweight_polish_splits_dense_conclusion_transitions() -> None:
    paper = (
        "## Conclusion\n\n"
        "The final claim remains bounded. The recommended next step is a "
        "prospective study. Until such evidence accrues, clinical use should "
        "remain cautious.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "\n\nThe recommended next step is" in out
    assert "\n\nUntil such evidence accrues," in out
    assert any(i["fix_type"] == "conclusion_paragraph_split" for i in log)


def test_lightweight_polish_repairs_surface_contract_defects() -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Cardiometabolic | n=14; claims=20 | mixed |\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "The cardiometabolic evidence base spans 15 curated references.\n\n"
        "Meta-analytic evidence corroborates the glycemic signal.\n\n"
        "## Conclusion\n\n"
        "It separates endpoint-specific evidence from broad treatment claims. "
        "The final interpretation remains bounded.\n\n"
        "## References\n\n"
        "- Smith 2024.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "spans 14 curated references" in out
    assert "Meta-analytic evidence corroborates" not in out
    assert "It separates endpoint-specific evidence" not in out
    fix_types = {i["fix_type"] for i in log}
    assert "results_count_claim_alignment" in fix_types
    assert "thin_analytic_paragraph_strip" in fix_types
    assert "conclusion_scope_leak_strip" in fix_types


def test_lightweight_polish_inserts_missing_declared_outcome_sections() -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Cardiometabolic | n=14; claims=20 | mixed |\n"
        "| Immune | n=1; claims=6 | mixed |\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "The cardiometabolic evidence base spans 14 curated references.\n\n"
        "## Cross-Domain Synthesis\n\n"
        "The outcome map remains bounded.\n\n"
        "## References\n\n"
        "- Smith 2024.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "### Immune Outcomes" in out
    assert "n=1" in out
    assert any(i["fix_type"] == "missing_results_outcome_section_insert" for i in log)


def test_missing_outcome_insert_uses_canonical_surface_keys() -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Dosing Pharmacokinetics | n=4; claims=20 | mixed signal | 4 review | indirect |\n"
        "| Immune | n=2; claims=6 | null signal | 2 indirect | sparse |\n\n"
        "### Dosing and Pharmacokinetics Outcomes\n\n"
        "The dosing packet already has the canonical public heading.\n\n"
        "## Cross-Domain Synthesis\n\n"
        "The outcome map remains bounded.\n"
    )
    out, n = fixes._insert_missing_declared_outcome_sections(paper)
    assert n == 1
    assert out.count("### Dosing and Pharmacokinetics Outcomes") == 1
    assert "### Immune Outcomes" in out


def test_inserted_outcome_stubs_do_not_trip_duplicate_surface_gate() -> None:
    from agent.journal_surface_gate import _duplicate_paragraph_issue_messages

    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |\n"
        "|---|---|---|---|---|\n"
        "| Cardiometabolic | n=3; claims=20 | null signal | 1 direct; 2 indirect | bounded |\n"
        "| Safety and Comorbidity | n=3; claims=18 | null signal | 1 direct; 2 indirect | bounded |\n"
    )
    out, n = fixes._insert_missing_declared_outcome_sections(paper)
    assert n == 2
    assert _duplicate_paragraph_issue_messages(out) == ()


def test_duplicate_subsection_strip_preserves_distinct_outcome_sections() -> None:
    paper = (
        "## Results\n\n"
        "### Longevity Outcomes\n\n"
        "The evidence packet is kept separate from adjacent outcomes and interpreted as hypothesis-generating rather than standalone proof.\n\n"
        "### Immune Outcomes\n\n"
        "The evidence packet is kept separate from adjacent outcomes and interpreted as hypothesis-generating rather than standalone proof.\n"
    )
    out, n = fixes._strip_duplicate_subsections(paper)
    assert n == 0
    assert "### Longevity Outcomes" in out and "### Immune Outcomes" in out


def test_results_depth_backfill_is_not_an_outcome_h3() -> None:
    assert not fixes._RESULTS_BACKFILL.startswith("###")


def test_unexpected_results_h3_is_demoted() -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Immune | n=2; claims=6 | null |\n\n"
        "### Result-interpretation guardrail\n\n"
        "This explains how to read the result pattern.\n\n"
        "### Immune Outcomes\n\n"
        "The immune packet is preserved.\n"
    )
    out, n = fixes._demote_unexpected_results_h3s(paper)
    assert n == 1
    assert "### Result-interpretation guardrail" not in out
    assert "**Result-interpretation guardrail.**" in out
    assert "### Immune Outcomes" in out


def test_legacy_missing_outcome_stubs_are_shortened() -> None:
    from agent.journal_surface_gate import _duplicate_paragraph_issue_messages

    paper = (
        "## Results\n\n"
        "### Immune Outcomes\n\n"
        "The Results table identifies immune evidence as a separate outcome slice (n=12). "
        "Because this slice is small, it is kept separate from adjacent outcomes and "
        "interpreted as hypothesis-generating rather than as a standalone endpoint conclusion.\n\n"
        "### Immune and Inflammation Outcomes\n\n"
        "The Results table identifies immune and inflammation evidence as a separate outcome slice (n=5). "
        "Because this slice is small, it is kept separate from adjacent outcomes and "
        "interpreted as hypothesis-generating rather than as a standalone endpoint conclusion.\n"
    )
    out, n = fixes._shorten_legacy_results_outcome_stubs(paper)
    assert n == 2
    assert "The Results table identifies" not in out
    assert _duplicate_paragraph_issue_messages(out) == ()


def test_sentence_like_h3_headings_are_demoted() -> None:
    paper = (
        "## Methods\n\n"
        "### Information sources were retrieved across PubMed, Europe PMC, OpenAlex, Semantic Scholar, Crossref, DOAJ, OpenAIRE, PMC OAI, bioRxiv, medRxiv, arXiv, and ClinicalTrials.gov. Retrieval window: 2026-05-27.\n\n"
        "### Search strategy\n\n"
        "Queries were executed.\n"
    )
    out, n = fixes._demote_sentence_like_headings(paper)
    assert n == 1
    assert "### Information sources were retrieved" not in out
    assert "**Information sources were retrieved" in out
    assert "### Search strategy" in out


def test_fuzzy_duplicate_strip_handles_bold_thesis_prefix() -> None:
    paper = (
        "## Abstract\n\n"
        "**Thesis:** Across 57 curated reference papers, the evidence base shows a context-dependent profile. "
        "Positive signals appear in contextual outcomes. Negative signals appear in immune outcomes. "
        "Null findings dominate adjacent domains. The synthesis surfaces cross-study disagreements across outcome classes.\n\n"
        "## Discussion\n\n"
        "Across 57 curated reference papers, the evidence base shows a context-dependent profile. "
        "Positive signals appear in contextual outcomes. Negative signals appear in immune outcomes. "
        "Null findings dominate adjacent domains. The synthesis surfaces cross-study disagreements across outcome classes.\n"
    )
    out, n = fixes._strip_fuzzy_duplicate_paragraphs(paper)
    assert n == 1
    assert out.count("Across 57 curated reference papers") == 1


def test_thesis_marker_not_injected_when_abstract_already_thesis_framed() -> None:
    # Abstract already opens with a "This paper synthesizes ..." framing
    # sentence; injecting another "This synthesis tests the thesis ..." line
    # stacks two near-identical openers (the redundancy Researka flagged).
    paper = (
        "## Abstract\n\n"
        "This paper synthesizes cold exposure as an aging-related intervention "
        "across 37 source papers and 1333 claims.\n\n"
        "The conclusion is that it remains a bounded geroscience case.\n\n"
        "## Discussion\n\nBody.\n"
    )
    out, n = fixes._ensure_public_thesis_marker(paper, {"topic": "cold_exposure"})
    assert n == 0
    assert "This synthesis tests the thesis" not in out


def test_thesis_marker_injected_when_abstract_lacks_thesis_framing() -> None:
    # No thesis-framing opener anywhere -> the marker must still be injected.
    paper = (
        "## Abstract\n\n"
        "Cold exposure was reviewed across many studies with mixed endpoints "
        "and no single pooled estimate.\n\n"
        "## Discussion\n\nBody.\n"
    )
    out, n = fixes._ensure_public_thesis_marker(paper, {"topic": "cold_exposure"})
    assert n == 1
    assert "tests the thesis" in out


def test_apply_fixes_skips_full_depth_backfill_for_thin_brief() -> None:
    paper = "## Results\n\nShort thin result.\n\n## Conclusion\n\nShort.\n"
    out, log = fixes.apply_fixes(paper, [], manifest={"review_type": "thin_corpus_brief"})
    assert "Result-interpretation guardrail" not in out
    assert "analytical_depth_backfill" not in {i["fix_type"] for i in log}


def test_lightweight_polish_rebuilds_thin_results_from_manifest() -> None:
    paper = (
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "Broken duplicate paragraph.\n\n"
        "### Longevity Outcomes\n\n"
        "\n\n## References\n\n- Smith 2024.\n"
    )
    manifest = {"review_type": "thin_corpus_brief", "topic": "everolimus", "receipts": [
        {"outcome_class": "cardiometabolic", "effect_direction": "null", "directness": "indirect", "n_claims": 3},
        {"outcome_class": "longevity", "effect_direction": "positive", "directness": "review", "n_claims": 2},
    ]}
    out, log = fixes.apply_lightweight_public_polish(paper, manifest=manifest)
    assert "| TORC1 inhibitor / Cardiometabolic | n=1; claims=3 | null signal" in out
    assert "Broken duplicate paragraph" not in out
    assert any(i["fix_type"] == "thin_results_rebuild" for i in log)


def test_lightweight_polish_strips_empty_headings() -> None:
    paper = "## What This Adds\n\n### Next-Study Design Recommendation\n\n## Methods\n\nText.\n"
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "Next-Study Design Recommendation" not in out
    assert any(i["fix_type"] == "empty_heading_strip" for i in log)


def test_lightweight_polish_strips_reference_only_next_study_section() -> None:
    paper = (
        "## What This Adds\n\n### Next-Study Design Recommendation\n\n"
        "- **Smith 2024.** _Title._ Journal.\n\n"
        "Additional corpus sources informed the synthesis without anchoring a foregrounded quantitative claim.\n"
        "## References\n\n- **Smith 2024.** 2024.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "Next-Study Design Recommendation" not in out
    assert "Additional corpus sources" not in out
    assert "## References" in out
    assert any(i["fix_type"] == "reference_only_next_study_strip" for i in log)


def test_lightweight_polish_completes_known_background_references() -> None:
    paper = (
        "## Discussion\n\n"
        "ADA 2024 contextualizes the glycemic endpoint. "
        "Ioannidis 2005 contextualizes surrogate endpoint caution.\n\n"
        "## References\n\n"
        "- Smith 2024.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "ADA 2024 contextualizes" in out
    assert "### Background References" in out
    assert "- **ADA 2024.**" in out
    assert "- **Ioannidis 2005.**" in out
    assert any(i["fix_type"] == "background_reference_completion" for i in log)


def test_lightweight_polish_completes_near_floor_conclusion_only() -> None:
    near_floor = " ".join(f"conclusion{i}" for i in range(240))
    paper = f"## Conclusion\n\n{near_floor}\n\n## References\n\n- Smith 2024.\n"
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "broad clinical extrapolation" in out
    assert "gaps.\n\n## References" in out
    assert any(i["fix_type"] == "near_floor_conclusion_completion" for i in log)


def test_lightweight_polish_repairs_heading_glue() -> None:
    out, log = fixes.apply_lightweight_public_polish(
        "## Results\n\n### Cardiometabolic Outcomes\n\nDone.## References\n\n- Smith 2024.\n",
    )
    assert "### Cardiometabolic Outcomes" in out
    assert "Done.\n\n## References" in out
    assert any(i["fix_type"] == "heading_boundary_normalization" for i in log)


def test_lightweight_polish_repairs_missing_sentence_spaces() -> None:
    out, log = fixes.apply_lightweight_public_polish(
        "## Discussion\n\n"
        "Evidence remains mixed. Harrison 2021 informs dosing. "
        "Practice change.Harrison 2021 requires replication.Likewise, "
        "safety data remain sparse.\n\n"
        "## References\n\n- Harrison 2021.\n",
    )
    assert "Practice change. Harrison" in out
    assert "replication. Likewise" in out
    assert any(i["fix_type"] == "sentence_spacing_normalization" for i in log)


def test_apply_fixes_repairs_abstract_direction_summary_from_manifest() -> None:
    paper = (
        "## Abstract\n\n"
        "Positive study-level signals are summarized in the cardiometabolic "
        "and muscle function outcome classes, null signals in the skeletal "
        "outcome class, and negative signals in the retained evidence base. "
        "The paper therefore interprets the corpus cautiously.\n\n"
        "## Results\n\n"
        "Results text.\n"
    )
    manifest = {"receipts": [
        {"outcome_class": "cardiometabolic", "effect_direction": "null"},
        {"outcome_class": "muscle_function", "effect_direction": "positive"},
        {"outcome_class": "skeletal", "effect_direction": "negative"},
    ]}
    out, log = fixes.apply_fixes(paper, [], manifest=manifest)
    abstract = out.split("## Results", 1)[0]
    assert "Positive study-level signals are summarized in the muscle function outcome class" in abstract
    assert "null signals are summarized in the cardiometabolic outcome class" in abstract
    assert "negative signals are summarized in the skeletal outcome class" in abstract
    assert "Positive study-level signals are summarized in the cardiometabolic" not in abstract
    assert any(
        i["fix_type"] == "abstract_results_direction_consistency_repair"
        for i in log
    )


def test_apply_fixes_does_not_repair_abstract_without_receipts() -> None:
    paper = (
        "## Abstract\n\n"
        "Positive study-level signals are summarized in the cardiometabolic "
        "outcome class, null signals in the skeletal outcome class, and "
        "negative signals in the retained evidence base.\n\n"
        "## Results\n\n"
        "Results text.\n"
    )
    out, log = fixes.apply_fixes(paper, [], manifest={"receipts": []})
    assert (
        "Positive study-level signals are summarized in the cardiometabolic "
        "outcome class, null signals in the skeletal outcome class, and "
        "negative signals in the retained evidence base."
    ) in out
    assert not [
        i for i in log
        if i["fix_type"] == "abstract_results_direction_consistency_repair"
    ]


def test_lightweight_polish_repairs_accidental_h3_split() -> None:
    out, log = fixes.apply_lightweight_public_polish("## Results\n\n#\n\n## Immune Outcomes\n\nText.\n")
    assert "### Immune Outcomes" in out
    assert "#\n\n## Immune Outcomes" not in out
    assert any(i["fix_type"] == "heading_boundary_normalization" for i in log)
