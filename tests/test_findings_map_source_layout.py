from copy import deepcopy

import pytest

from agent.journal_surface_gate import _orphan_table_issue_messages
from agent.revision_quality import _stat_supported, manifest_row_finding
from agent.publication_evidence import exact_source_quote


@pytest.mark.parametrize("endpoint", ["Memory", "Strength", "Blood pressure"])
def test_source_sentence_spacing_is_stable_before_review_without_changing_evidence(endpoint):
    from quant_claim_extract import readable_source_notation
    from apply_consistency_fixes import _normalize_sentence_spacing

    raw = f"{endpoint} was assessed.ResultsOf 52 participants, 12 improved (p = 0.05)."
    row = {"verified_source_sections": True, "source_result_excerpts": [raw]}
    before = deepcopy(row)
    rendered = readable_source_notation(manifest_row_finding(row))
    assert rendered == raw.replace(".ResultsOf", ". ResultsOf")
    assert _normalize_sentence_spacing(rendered) == (rendered, 0)
    # Core's cleaner rstrips every line; a trailing space before a blank line must not reach the package.
    assert _normalize_sentence_spacing(f"{rendered} \n\n| a | b |\n") == (f"{rendered}\n\n| a | b |\n", 0)
    assert readable_source_notation(rendered) == rendered
    assert row == before
    assert exact_source_quote(rendered, raw)
    assert not exact_source_quote(rendered.replace("52", "53"), raw)
    assert not exact_source_quote(rendered.replace("p =", "p >"), raw)


@pytest.mark.parametrize("endpoint", ["Memory", "Strength", "Blood pressure"])
def test_findings_map_keeps_other_arm_results_without_recognized_statistic(endpoint):
    from quant_claim_extract import source_result_excerpts

    target = f"{endpoint} improved by 1.43 more in the treatment group than control."
    qualification = "The difference was only observed at the first follow-up."
    other = f"{endpoint} improved by 5.15 in the alternative group compared with control (p = 0.065)."
    context = " ".join((target, qualification, other))
    record = {"sections": {"abstract": context}}
    assert source_result_excerpts(record) == (other,)
    excerpts = source_result_excerpts(record, require_numeric=False, complete_context=True)
    assert excerpts == (context,)
    assert manifest_row_finding({"verified_source_sections": record["sections"], "source_result_excerpts": excerpts}) == context
    assert exact_source_quote(context, record["sections"]["abstract"])


@pytest.mark.parametrize("endpoint", ["Strength", "Blood pressure", "Memory"])
def test_adjacent_result_sentences_preserve_context_and_typesetting(endpoint):
    raw = f"{endpoint} was assessed before and after treatment. <jats:italic>Results : </jats:italic> Adherence was 90.2 ± 14.5% and treatment improved the endpoint versus control (<jats:italic>p</jats:italic> < .05)."
    claim = f"{endpoint} was assessed before and after treatment. Results : Adherence was 90.2 ± 14.5% and treatment improved the endpoint versus control (p < .05)."
    row = {"verified_abstract": raw}
    assert exact_source_quote(claim, raw)
    assert _stat_supported("14.5%", row, context="finding=" + claim)
    assert _stat_supported("p < .05", row, context=claim)
    for changed in (claim.replace("14.5", "15.4"), claim.replace("<", ">"),
                    claim.replace("control", "baseline"), claim.replace(endpoint, "Survival"),
                    claim.replace("improved", "did not improve")):
        assert not exact_source_quote(changed, raw)
        assert not _stat_supported("p < .05", row, context=changed)
    interrupted = raw.replace(" <jats:italic>Results", " This result was not significant. <jats:italic>Results")
    assert not _stat_supported("p < .05", {"verified_abstract": interrupted}, context=claim)


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
    assert manifest_row_finding({"source_result_excerpts": ["Mortality decreased (Table 2)."], "n_claims": 3}) == "Source-level classification only; no result passage available in the frozen record."


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


def test_direction_count_includes_every_named_source_in_its_roster():
    from journal_finalizer import _manifest_direction_heterogeneity_note
    rows = [{"citation_token": f"Study{i} 2020", "outcome_class": "cognitive", "directness": "direct",
             "effect_direction": "unclear" if i < 4 else "positive"} for i in range(5)]
    note = _manifest_direction_heterogeneity_note(rows)
    assert "unclear=4" in note
    assert "direction=" not in note
    assert all(row["citation_token"] in note for row in rows)


def test_direction_note_uses_the_same_domain_as_the_displayed_findings():
    from journal_finalizer import _manifest_direction_heterogeneity_note
    from agent.revision_quality import findings_map_row

    rows = [
        {"citation_token": "Training 2025", "outcome_class": "muscle_function", "directness": "direct", "effect_direction": "positive"},
        {"citation_token": "Adjunct 2025", "source_title": "Resistance training with supplementation increases lean mass",
         "outcome_class": "muscle_function", "directness": "indirect", "effect_direction": "mixed"},
    ]
    assert [findings_map_row(row)[0] for row in rows] == ["Muscle Function", "Muscle Function"]
    assert _manifest_direction_heterogeneity_note(rows) == (
        "Direction heterogeneity note: Muscle Function: mixed=1 (Adjunct 2025); positive=1 (Training 2025)."
    )
