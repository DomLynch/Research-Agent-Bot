from copy import deepcopy

import pytest

from agent.journal_surface_gate import _orphan_table_issue_messages
from agent.revision_quality import _stat_supported, manifest_row_finding


@pytest.mark.parametrize("locator", ["(Table 2 )", "( Table 4 ; Figures 2A , 3A–H )", "(Figures 2A, 3B)"])
def test_source_layout_only_parenthetical_is_omitted_without_changing_finding(locator):
    text = f"Resveratrol reduced symptoms by 12% (p < 0.05) {locator}."
    row = {"verified_source_sections": True, "source_result_excerpts": [text]}
    before = deepcopy(row)
    finding = manifest_row_finding(row)
    assert finding == "Resveratrol reduced symptoms by 12% (p < 0.05)."
    assert row == before
    assert not _orphan_table_issue_messages(finding)
    assert _orphan_table_issue_messages(finding + " Our results appear in Table 2.") == ("orphan table reference: Table 2",)


@pytest.mark.parametrize("annotation", ["(Table 2; p=0.05)", "(Table 2, 30g)", "(12%, p < 0.05)",
    "(Table 2: adjusted estimate 0.07)", "(Figure 2, 12 patients)"])
def test_ambiguous_or_statistical_parenthetical_is_preserved(annotation):
    text = f"The endpoint changed {annotation}."
    assert manifest_row_finding({"verified_source_sections": True, "source_result_excerpts": [text]}) == text


def test_unverified_excerpt_does_not_become_a_finding():
    assert manifest_row_finding({"source_result_excerpts": ["Mortality decreased (Table 2)."], "n_claims": 3}) == "3 extracted claim(s); receipt-level direction is the coded finding"


@pytest.mark.parametrize("change", [None, "value", "operator", "endpoint", "unverified", "source"])
def test_results_statistic_requires_verified_owned_complete_clause(change):
    source = "Symptoms decreased with treatment versus placebo (p < 0.05) (Table 2)."
    row = {"verified_abstract": "The study compared treatment and placebo.\nKeywords: symptoms, treatment",
           "verified_source_sections": True, "source_result_excerpts": [source]}
    claim = manifest_row_finding(row)
    if change == "value":
        claim = claim.replace("0.05", "0.01")
    elif change == "operator":
        claim = claim.replace("<", ">")
    elif change == "endpoint":
        claim = claim.replace("Symptoms", "Mortality")
    elif change == "unverified":
        row["verified_source_sections"] = False
    elif change == "source":
        row["source_result_excerpts"] = ["Mortality did not change (p > 0.05)."]
    assert _stat_supported("p < 0.05", row, context=claim) is (change is None)


def test_mixed_statistical_parenthetical_cannot_be_removed_from_source_match():
    source = "Symptoms decreased (Table 2; p < 0.05)."
    row = {"verified_source_sections": True, "source_result_excerpts": [source]}
    assert not _stat_supported("p < 0.05", row, context="Symptoms decreased.")


def test_rendered_methods_retains_required_directness_criteria():
    from agent.methods_pack import build_methods_pack, render_methods_md
    from revision_coverage import _directness_coding_criteria_are_stated
    pack = build_methods_pack(review_type="curated_evidence_map", topic="resveratrol",
        corpus_search_queries=[], n_retrieved=None, n_screened=None,
        n_included=37, n_rejected=None, outcome_classes=[])
    assert _directness_coding_criteria_are_stated(render_methods_md(pack, submission_id="test"))
