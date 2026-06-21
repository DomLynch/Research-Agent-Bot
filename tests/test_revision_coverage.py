from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import revision_coverage  # type: ignore[import-not-found]  # noqa: E402


def _chat(parsed: dict[str, Any]) -> Any:
    async def fake(**_kwargs: Any) -> Any:
        return type("Resp", (), {"parsed": parsed})()
    return fake


def _unmet(asks: list[str], parsed: dict[str, Any], monkeypatch) -> list[str]:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    return revision_coverage.unmet_asks("MANUSCRIPT BODY", asks, chat=_chat(parsed), settings=object())


def test_unmet_asks_empty_when_all_addressed(monkeypatch) -> None:
    assert _unmet(["a", "b"], {"addressed": [True, True]}, monkeypatch) == []


def test_unmet_asks_flags_unaddressed_in_order(monkeypatch) -> None:
    assert _unmet(["hedge claims", "clarify scope"], {"addressed": [True, False]}, monkeypatch) == ["clarify scope"]


def test_unmet_asks_failopen_on_malformed_verdict(monkeypatch) -> None:
    # Length mismatch / wrong shape must not block submit.
    assert _unmet(["a", "b"], {"addressed": [True]}, monkeypatch) == []
    assert _unmet(["a"], {"addressed": "nope"}, monkeypatch) == []


def test_unmet_asks_empty_for_no_asks(monkeypatch) -> None:
    assert _unmet([], {"addressed": []}, monkeypatch) == []


def test_unmet_asks_failopen_on_judge_error(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())

    async def boom(**_kwargs: Any) -> Any:
        raise revision_coverage.LLMError("judge down")

    assert revision_coverage.unmet_asks("M", ["a"], chat=boom, settings=object()) == []


def test_deterministic_unmet_flags_missing_classification_criteria() -> None:
    ask = "Define the classification criteria used to assign studies to outcome classes and to code directness."

    assert revision_coverage.deterministic_unmet_asks("## Methods\n\nMethods.\n", [ask]) == [ask]


def test_deterministic_unmet_accepts_classification_criteria_and_map() -> None:
    paper = (
        "## Methods\n\n"
        "### Classification criteria\n\n"
        "**Outcome class** records the endpoint family. **Directness** records whether evidence is direct, "
        "indirect, mechanistic, or review. **Evidence tier** records A1, A2, B1, B2, C1, or C2.\n\n"
        "### Source classification map\n\n"
        "- Smith 2024: outcome=cardiometabolic; directness=indirect; tier=B2.\n"
    )
    asks = [
        "Define the classification criteria used to assign studies to outcome classes and to code directness.",
        "Provide a mapping table or list showing which sources were assigned to which outcome class.",
    ]

    assert revision_coverage.deterministic_unmet_asks(paper, asks) == []


def test_deterministic_unmet_flags_missing_source_directness_breakdown() -> None:
    ask = (
        "Clarify source directness: explicitly note which of the 28 sources directly "
        "address deep sleep manipulation and aging-relevant hard endpoints versus which "
        "are adjacent (e.g., insomnia drug trials, general sleep architecture descriptions, "
        "preclinical models)."
    )
    paper = "## Evidence Landscape\n\nThe corpus is adjacent and mixed.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_source_directness_breakdown() -> None:
    ask = (
        "Clarify source directness: explicitly note which of the 28 sources directly "
        "address deep sleep manipulation and aging-relevant hard endpoints versus which "
        "are adjacent (e.g., insomnia drug trials, general sleep architecture descriptions, "
        "preclinical models)."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Source Directness Breakdown\n\n"
        "- Smith 2024: directly addresses deep sleep manipulation and aging-relevant hard endpoints; "
        "directness=direct_interventional.\n"
        "- Jones 2025: adjacent insomnia-drug trial evidence; directness=adjacent.\n"
        "- Lee 2026: mechanistic sleep-architecture model; directness=mechanistic.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_general_vs_direct_source_breakdown() -> None:
    ask = (
        "Clarify which of the 52 sources directly address a composite digital "
        "frailty index versus general digital biomarker research, and bound the "
        "synthesis claims accordingly."
    )
    paper = "## Evidence Landscape\n\nThe source set is heterogeneous.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_general_vs_direct_source_breakdown() -> None:
    ask = (
        "Clarify which of the 52 sources directly address a composite digital "
        "frailty index versus general digital biomarker research, and bound the "
        "synthesis claims accordingly."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Source Directness Breakdown\n\n"
        "- Smith 2024: directly addresses the composite index endpoint; directness=direct.\n"
        "- Jones 2025: broader general digital biomarker research; directness=contextual.\n"
        "- Lee 2026: adjacent frailty assessment evidence; directness=adjacent.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_topic_fit_rationale_for_umbrella_source_ask() -> None:
    ask = (
        "Add a note explaining why sources on opioid monitoring, sports workload, "
        "geolocation in psychiatric disorders, and Alzheimer's speech analysis are "
        "included under the 'digital frailty index' umbrella, given that none appear "
        "to operationalize a frailty index."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Topic-fit rationale: Sources are retained only when they operationalize "
        "digital frailty index directly or provide adjacent/contextual boundary "
        "evidence for the same construct. 0/4 retained sources are classified as "
        "direct; adjacent, contextual, review-level, or mechanistic sources are "
        "reclassified as boundary evidence rather than used for broad efficacy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_topic_fit_rationale_in_evidence_snapshot() -> None:
    ask = (
        "Add a note explaining why sources are included under the digital frailty "
        "index umbrella when they do not operationalize a frailty index."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "Topic-fit rationale: Sources are retained only when they operationalize "
        "digital frailty index directly or provide adjacent/contextual boundary "
        "evidence for the same construct. Adjacent sources are reclassified as "
        "boundary evidence rather than used for broad efficacy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_off_topic_source_audit_without_breakdown() -> None:
    ask = (
        "Audit the source bundle for sources that are clearly off-topic to hydrogen "
        "water in humans or animals and either remove them or explain their inclusion "
        "as contextual adjacent evidence."
    )
    paper = "## Evidence Landscape\n\nThe included sources are summarized below.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_evidence_type_metadata_inconsistency() -> None:
    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = "## Methods\n\nSources were grouped by topic.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_evidence_type_metadata_resolution() -> None:
    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = (
        "## Methods\n\n"
        "### Source Classification Map\n\n"
        "Evidence_type labels were resolved against excerpts: review records with RCT excerpt data "
        "were reclassified under classification criteria that separate review, RCT, and trial evidence.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_evidence_type_metadata_in_evidence_snapshot() -> None:
    ask = "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data."
    paper = (
        "## Evidence Snapshot\n\n"
        "### Source Classification Map\n\n"
        "Evidence_type metadata note: evidence_type labels are resolved against source excerpts; "
        "review, RCT/trial, and excerpt evidence are reclassified under the source classification map.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_off_topic_source_audit_breakdown() -> None:
    ask = (
        "Audit the source bundle for sources that are clearly off-topic to hydrogen "
        "water in humans or animals and either remove them or explain their inclusion "
        "as contextual adjacent evidence."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Source Directness Breakdown\n\n"
        "- Smith 2024: directly addresses the intervention and hard endpoints; directness=direct.\n"
        "- Jones 2025: contextual adjacent evidence retained for mechanism only; directness=contextual.\n"
        "- Lee 2026: mechanistic animal evidence; directness=mechanistic.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_remove_or_justify_off_topic_sources() -> None:
    ask = (
        "Remove or justify clearly off-topic sources from the corpus, and update "
        "the source count and evidence landscape accordingly."
    )
    paper = "## Evidence Landscape\n\nAll sources are summarized.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_umbrella_source_inclusion_without_rationale() -> None:
    ask = (
        "Add a note explaining why sources on opioid monitoring and geolocation are included "
        "under the digital frailty index umbrella, given that none appear to operationalize a frailty index."
    )
    paper = "## Evidence Landscape\n\nThe included sources are summarized.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_umbrella_source_inclusion_rationale() -> None:
    ask = (
        "Add a note explaining why sources on opioid monitoring and geolocation are included "
        "under the digital frailty index umbrella, given that none appear to operationalize a frailty index."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "### Source Classification Map\n\n"
        "Inclusion rationale: sources that directly addresses frailty-index operationalization are "
        "kept as direct; contextual digital-biomarker sources are reclassified as adjacent and not "
        "used for broad claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_weak_gaps_section() -> None:
    ask = "Rewrite the 'Gaps Identified' section to provide specific, actionable research gaps."
    paper = "## Gaps Identified\n\nMore research is needed because the current corpus is limited.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_actionable_gaps_section() -> None:
    ask = "Rewrite the 'Gaps Identified' section to provide specific, actionable future research directions."
    paper = (
        "## Gaps Identified\n\n"
        "The next study should use a powered randomized trial in an older adult priority population, "
        "with a prespecified comparator, 12-month follow-up duration, clinically meaningful endpoint "
        "selection, dose documentation, and safety monitoring. Measurement should separate sleep, "
        "functional, and cardiometabolic endpoints so the evidence gap is testable rather than generic.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_gaps_that_repeat_limitations() -> None:
    ask = (
        "Rewrite the 'Gaps Identified' section to provide specific, actionable "
        "research gaps instead of repeating the limitations."
    )
    paper = (
        "## Gaps Identified\n\n"
        "The main gaps are the same as the limitations: the corpus is indirect, "
        "heterogeneous, and lacks definitive evidence.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_gaps_rewritten_as_actionable_next_steps() -> None:
    ask = (
        "Rewrite the 'Gaps Identified' section to provide specific, actionable "
        "research gaps instead of repeating the limitations."
    )
    paper = (
        "## Gaps Identified\n\n"
        "1. Run a powered prospective trial in the priority population with a "
        "prespecified comparator, dose documentation, and clinical endpoint hierarchy.\n"
        "2. Extend follow-up duration to at least 24 months with safety monitoring and "
        "patient-relevant functional measurement.\n"
        "3. Standardize measurement timing across cardiometabolic and functional endpoints "
        "so future analyses can test pooled effects rather than restating heterogeneity.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_live_top_bucket_matrix() -> None:
    asks = [
        (
            "In the Evidence Landscape table, the column 'Strongest signal' states "
            "'no extracted directional signal in 20/20 sources'. Given that some sources "
            "report directional results, reconcile the table coding with the narrative."
        ),
        "Resolve the evidence_type metadata inconsistencies where a review label contains RCT excerpt data.",
        (
            "Verify that all 50 bundle sources actually address melatonin and aging; "
            "remove or reclassify sources whose excerpts clearly address unrelated topics."
        ),
        (
            "The manuscript's explicit absence of direct clinical evidence and reliance on "
            "adjacent/mechanistic data requires a revise status to signal that broad "
            "population-level proof is missing."
        ),
        (
            "Rewrite the 'Gaps Identified' section to provide specific, actionable "
            "research gaps instead of repeating the limitations."
        ),
    ]
    missing = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Strongest signal |\n|---|---|\n"
        "| Contextual Adjacent Evidence | no extracted directional signal in 20/20 sources |\n\n"
        "## Gaps Identified\n\nThe limitations are indirect evidence and heterogeneity.\n\n"
        "## Conclusion\n\nA broad geroscience rationale remains plausible.\n"
    )
    repaired = (
        "## Evidence Landscape\n\n"
        "Directional coding note: Null or no extracted directional signal means no coded positive, "
        "negative, or mixed effect was extracted for that specific outcome class; it is not an "
        "absence-of-support finding. Positive, negative, mixed, unclear, and null are "
        "outcome-specific codes, so signals in other outcome evidence are separately reported.\n\n"
        "Source directness breakdown: 1/3 retained sources directly address the stated topic and "
        "aging-relevant hard endpoints; 2/3 are adjacent, contextual, review-level, or mechanistic "
        "and are used only to bound interpretation.\n\n"
        "### Source Classification Map\n\n"
        "- Smith 2024: outcome=cardiometabolic; directness=direct; tier=A1.\n"
        "- Jones 2025: outcome=contextual adjacent evidence; directness=adjacent; tier=B2.\n\n"
        "Evidence_type metadata note: evidence_type labels are resolved against source excerpts; "
        "review, RCT/trial, and excerpt evidence are reclassified under the source classification map.\n\n"
        "## Gaps Identified\n\n"
        "1. Run a powered prospective trial in the priority population with a prespecified "
        "comparator, dose documentation, and clinical endpoint hierarchy.\n"
        "2. Extend follow-up duration to at least 24 months with safety monitoring and "
        "patient-relevant functional measurement.\n"
        "3. Standardize measurement timing across cardiometabolic and functional endpoints "
        "so future analyses can test pooled effects rather than restating heterogeneity.\n\n"
        "## Conclusion\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and includes adjacent/mechanistic evidence, "
        "this synthesis is hypothesis-generating and not definitive. It does not support "
        "broad causal or policy claims; broad population-level proof is missing.\n"
    )

    assert set(revision_coverage.deterministic_unmet_asks(missing, asks)) == set(asks)
    assert revision_coverage.deterministic_unmet_asks(repaired, asks) == []


def test_deterministic_unmet_flags_unbounded_null_signal_conclusion() -> None:
    ask = "Reconcile the null directional signals with the concluding claim that a bounded geroscience rationale exists."
    paper = "## Conclusion\n\nThis synthesis supports a bounded geroscience rationale for clinical use.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_supportive_null_signal_even_if_hypothesis_generating() -> None:
    ask = "Reconcile the null directional signals with the concluding claim that a bounded geroscience rationale exists."
    paper = (
        "## Conclusion\n\n"
        "Because most directional signals are null, this synthesis supports a bounded geroscience "
        "rationale and is hypothesis-generating for clinical translation.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_bounded_null_signal_conclusion() -> None:
    ask = "Reconcile the null directional signals with the concluding claim that a bounded geroscience rationale exists."
    paper = (
        "## Conclusion\n\n"
        "Because most directional signals are null or mixed, this synthesis is hypothesis-generating and "
        "does not support a clinical recommendation. The bounded rationale is limited to study design.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_evidence_boundary() -> None:
    ask = (
        "Clarify in the abstract and key findings that the evidence is mixed and does not "
        "support broad causal or policy claims. Explicitly state that the synthesis is "
        "mechanistic and hypothesis-generating rather than definitive."
    )
    paper = "## Abstract\n\nThe evidence supports a plausible anti-aging signal.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_evidence_boundary() -> None:
    ask = (
        "The manuscript is technically sound, but the absence of direct clinical evidence "
        "and reliance on adjacent/mechanistic data requires a revise status to signal that "
        "broad population-level proof is missing."
    )
    paper = (
        "## Abstract\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and adjacent/mechanistic evidence, this "
        "synthesis is hypothesis-generating and not definitive. It does not support broad "
        "causal or policy claims; broad population-level proof is missing.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_requires_abstract_and_key_findings_boundary() -> None:
    ask = (
        "Clarify in the abstract and key findings that the evidence is mixed and does not "
        "support broad causal or policy claims. Explicitly state that the synthesis is "
        "mechanistic and hypothesis-generating rather than definitive."
    )
    abstract_only = (
        "## Abstract\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and adjacent/mechanistic evidence, this "
        "synthesis is hypothesis-generating and not definitive. It does not support broad "
        "causal or policy claims; broad population-level proof is missing.\n\n"
        "## Key Findings\n\nThe signal is promising.\n"
    )
    both_sections = abstract_only.replace(
        "## Key Findings\n\nThe signal is promising.",
        (
            "## Key Findings\n\n"
            "Evidence-boundary note: Because the retained corpus relies on limited direct "
            "interventional hard-endpoint evidence and adjacent/mechanistic evidence, this "
            "synthesis is hypothesis-generating and not definitive. It does not support broad "
            "causal or policy claims; broad population-level proof is missing."
        ),
    )

    assert revision_coverage.deterministic_unmet_asks(abstract_only, [ask]) == [ask]
    assert revision_coverage.deterministic_unmet_asks(both_sections, [ask]) == []


def test_deterministic_unmet_flags_claims_not_bounded_by_tier_directness() -> None:
    ask = (
        "Ensure that all claims in the Key Findings and Conclusion sections are explicitly "
        "bounded by the evidence tiers and directness ratings provided in the manuscript."
    )
    paper = (
        "## Key Findings\n\nThe signal is promising.\n\n"
        "## Conclusion\n\nThe intervention is biologically plausible.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_claims_bounded_by_tier_directness() -> None:
    ask = (
        "Ensure that all claims in the Key Findings and Conclusion sections are explicitly "
        "bounded by the evidence tiers and directness ratings provided in the manuscript."
    )
    paper = (
        "## Key Findings\n\nA B2 indirect evidence tier supports only hypothesis-generating "
        "claims; directness is indirect/review rather than direct.\n\n"
        "## Conclusion\n\nThe conclusion is bounded to A1/B2 evidence tier patterns and "
        "directness ratings that separate direct, indirect, review, and mechanistic sources.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_directional_signal_explanation() -> None:
    ask = (
        "Clarify whether 'no extracted directional signal' means no signal for this specific outcome class, "
        "given that some sources report positive or mixed associations elsewhere."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "Directional coding is counted within each assigned outcome class only. A no extracted directional "
        "signal cell means null or unclear coding for that outcome slice; positive and mixed signals in "
        "other outcome classes remain separately reported and do not change that row.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_weak_directional_signal_explanation() -> None:
    ask = (
        "Clarify whether 'no extracted directional signal' means no signal for this specific outcome class, "
        "given that some sources report positive or mixed associations elsewhere."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "Directional coding is counted within the assigned outcome class only. A no extracted directional "
        "signal cell means the retained sources did not yield a coded null or unclear signal for that slice.\n\n"
        "### Source Classification Map\n\n"
        "- Hayashi 2025: outcome=contextual adjacent evidence; direction=positive.\n"
        "- Yiallourou 2025: outcome=contextual adjacent evidence; direction=mixed.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_contextual_claims_without_direction_explanation() -> None:
    ask = (
        "Clarify what the contextual claims contain if no directional signal was extracted, "
        "and explain the discrepancy between the organized evidence landscape and the near-total absence of directional findings."
    )
    paper = "## Evidence Landscape\n\nThe table reports no directional signal.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_contextual_claims_without_direction_explanation() -> None:
    ask = (
        "Clarify what the contextual claims contain if no directional signal was extracted, "
        "and explain the discrepancy between the organized evidence landscape and the near-total absence of directional findings."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Contextual claims are bibliographic and mechanistic context, not effect-direction findings. "
        "A no extracted directional signal row means the extracted statistic was not directional for "
        "that outcome slice; it is not directional evidence of benefit.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_contextual_claims_explanation_in_evidence_snapshot() -> None:
    ask = (
        "Clarify what the contextual claims contain if no directional signal was extracted, "
        "and explain the discrepancy between the organized evidence landscape and the near-total absence of directional findings."
    )
    paper = (
        "## Evidence Snapshot\n\n"
        "Directional coding note: Null or no extracted directional signal means no coded effect was "
        "extracted for that outcome class. Contextual claims contain bibliographic background, "
        "mechanistic context, methods, or population context rather than effect-direction evidence.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_directional_table_narrative_contradiction() -> None:
    ask = (
        "Resolve the contradiction between the Evidence Landscape table showing no directional signal "
        "and the narrative claiming positive associations in frailty-outcome studies. Either the table "
        "coding or the narrative needs correction."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Strongest signal |\n"
        "|---|---|\n"
        "| Frailty | no directional signal in 20/20 sources |\n\n"
        "## Key Findings\n\n"
        "The corpus shows positive associations in frailty-outcome studies.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_reconciled_directional_table_narrative() -> None:
    ask = (
        "Resolve the contradiction between the Evidence Landscape table showing no directional signal "
        "and the narrative claiming positive associations in frailty-outcome studies. Either the table "
        "coding or the narrative needs correction."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Strongest signal |\n"
        "|---|---|\n"
        "| Frailty | no directional signal in 20/20 sources |\n\n"
        "## Key Findings\n\n"
        "Positive associations are separately reported in other outcome classes; the frailty row's "
        "no directional signal coding does not mean absence of support across the whole corpus.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_null_directional_vs_positive_narrative() -> None:
    ask = (
        "Resolve the inconsistency between the Evidence Landscape table (all null "
        "directional signals) and the rest of the manuscript (references to positive, "
        "mixed, and negative signals in the frailty class)."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Direction |\n"
        "|---|---|\n"
        "| Frailty | all null directional signals |\n\n"
        "## Key Findings\n\n"
        "The frailty class shows positive signals in several sources.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_null_directional_reconciled_narrative() -> None:
    ask = (
        "Resolve the inconsistency between the Evidence Landscape table (all null "
        "directional signals) and the rest of the manuscript (references to positive, "
        "mixed, and negative signals in the frailty class)."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Direction |\n"
        "|---|---|\n"
        "| Frailty | all null directional signals |\n\n"
        "## Key Findings\n\n"
        "Positive and mixed signals are separately reported in other outcome classes; "
        "the frailty row's null directional signal does not mean absence of support "
        "outside that specific coded slice.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_internal_duplication() -> None:
    ask = "Remove internal duplication of content across the Evidence Landscape and Key Findings sections."
    repeated = (
        "This synthesis separates direct intervention evidence from indirect biomarker evidence and "
        "shows that the current evidence base remains mixed, hypothesis-generating, and not sufficient "
        "for broad clinical or policy claims."
    )
    paper = f"## Evidence Landscape\n\n{repeated}\n\n## Key Findings\n\n{repeated}\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_near_duplicate_narrative() -> None:
    ask = "Remove repetitive narrative across the Evidence Landscape and Key Findings sections."
    paper = (
        "## Evidence Landscape\n\n"
        "This synthesis separates direct intervention evidence from indirect biomarker evidence and shows "
        "that the current evidence base remains mixed, hypothesis-generating, and insufficient for broad "
        "clinical or policy claims.\n\n"
        "## Key Findings\n\n"
        "The synthesis separates direct intervention evidence from indirect biomarker evidence, showing "
        "that the current evidence base remains mixed and hypothesis-generating rather than sufficient "
        "for broad clinical policy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_duplication_check_scopes_to_named_sections() -> None:
    ask = "Streamline the Gaps Identified and Discussion sections to avoid verbatim repetition."
    repeated_results = (
        "92 included sources were assigned to this outcome class. Directional coding includes mixed, "
        "negative, null, positive, and unclear signals. Directness coding includes direct, indirect, "
        "mechanistic, and review sources."
    )
    paper = (
        "## Results\n\n"
        f"{repeated_results}\n\n"
        "14 included sources were assigned to this outcome class. Directional coding includes mixed, "
        "negative, null, positive, and unclear signals. Directness coding includes direct, indirect, "
        "mechanistic, and review sources.\n\n"
        "## Gaps Identified\n\n"
        "Future trials should define endpoints, comparators, follow-up duration, and safety monitoring.\n\n"
        "## Discussion\n\n"
        "The discussion interprets the evidence without repeating the gap list or corpus statistics.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_duplication_check_flags_named_section_overlap() -> None:
    ask = "Streamline the Gaps Identified and Discussion sections to avoid verbatim repetition."
    repeated = (
        "The current corpus is mixed and hypothesis-generating, with evidence distribution statistics "
        "showing indirect and review evidence rather than settled clinical translation."
    )
    paper = (
        f"## Gaps Identified\n\n{repeated}\n\n"
        f"## Discussion\n\n{repeated}\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_duplication_check_does_not_fallback_when_named_sections_absent() -> None:
    ask = "Streamline the Gaps Identified and Discussion sections to avoid verbatim repetition."
    paper = (
        "## Results\n\n"
        "92 included sources were assigned to this outcome class. Directional coding includes mixed, "
        "negative, null, positive, and unclear signals. Directness coding includes direct, indirect, "
        "mechanistic, and review sources.\n\n"
        "14 included sources were assigned to this outcome class. Directional coding includes mixed, "
        "negative, null, positive, and unclear signals. Directness coding includes direct, indirect, "
        "mechanistic, and review sources.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_non_repetitive_sections() -> None:
    ask = "Remove internal duplication and present a single, non-repetitive narrative."
    paper = (
        "## Evidence Landscape\n\n"
        "The evidence landscape separates direct intervention evidence from indirect biomarker evidence "
        "and identifies mixed signals across outcome domains.\n\n"
        "## Key Findings\n\n"
        "The key finding is that clinical translation remains premature because source directness and "
        "endpoint maturity vary across the corpus.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_long_term_safety_scope() -> None:
    ask = "Add a brief statement in the abstract and conclusion about the lack of long-term safety data in older adults."
    paper = "## Abstract\n\nThe evidence is mixed.\n\n## Conclusion\n\nClinical translation remains premature.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_long_term_safety_scope() -> None:
    ask = "Add a brief statement in the abstract and conclusion about the lack of long-term safety data in older adults."
    paper = (
        "## Abstract\n\n"
        "The evidence is mixed, and long-term safety data in older adults remain insufficient.\n\n"
        "## Conclusion\n\n"
        "Because long-term safety in older adults is not established, clinical translation remains premature.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_reference_without_identifier() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults.\n"
        "- Jones 2025. Cohort evidence. DOI: 10.1000/example.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_reference_identifiers() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults. DOI: 10.1000/example.\n"
        "- Jones 2025. Cohort evidence. PMID: 12345678.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_reference_identifier_caveat() -> None:
    ask = "Make every reference traceable to the source bundle and clarify missing DOI/PMID entries."
    paper = (
        "## References\n\n"
        "- Smith 2024. Registered trial. Trial registration: NCT01234567.\n"
        "- Jones 2025. Registry protocol. Identifier unavailable; no DOI or PMID in source metadata.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_ignores_reference_headings_and_notes() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults. DOI: 10.1000/example.\n\n"
        "### Background References\n\n"
        "*Canonical clinical thresholds cited in prose; entries below remain source-traceable.*\n\n"
        "- Jones 2025. Cohort evidence. PMID: 12345678.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_still_flags_identifierless_reference_entry() -> None:
    ask = (
        "Ensure all cited sources in the reference list have verifiable bibliographic identifiers "
        "(DOI/PMID) and are traceable to the source bundle."
    )
    paper = (
        "## References\n\n"
        "- Smith 2024. Trial of intervention in older adults. DOI: 10.1000/example.\n\n"
        "### Background References\n\n"
        "*Canonical clinical thresholds cited in prose; entries below remain source-traceable.*\n\n"
        "- Jones 2025. Cohort evidence without a public identifier.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_missing_prior_publication_differentiation() -> None:
    ask = (
        "High overlap with publication 5f852f5b. Differentiate angle, "
        "findings, or population to resubmit."
    )
    paper = "## Introduction\n\nThis evidence brief summarizes the current corpus.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_prior_publication_differentiation() -> None:
    ask = (
        "High overlap with publication 5f852f5b. Differentiate angle, "
        "findings, or population to resubmit."
    )
    paper = (
        "## Introduction\n\n"
        "Prior-brief differentiation: This revision makes the angle, findings, "
        "and population boundary explicit. The angle is a source-bounded synthesis; "
        "the findings are limited to cardiometabolic and sleep outcomes; and the "
        "population boundary follows the included corpus.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_source_verification_transparency() -> None:
    ask = (
        "Add a verification transparency statement acknowledging that the reference-only source bundle "
        "limits external verification of detailed quantitative claims, and direct readers to "
        "supplementary artifacts (manifest.json, methods_pack.json) for full traceability."
    )
    paper = "## Limitations\n\nThe corpus is limited.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_source_verification_transparency() -> None:
    ask = (
        "Add a verification transparency statement acknowledging that the reference-only source bundle "
        "limits external verification of detailed quantitative claims, and direct readers to "
        "supplementary artifacts (manifest.json, methods_pack.json) for full traceability."
    )
    paper = (
        "## Limitations\n\n"
        "The source bundle is reference-only, so exact statistics may not be independently verified "
        "from the public manuscript alone. Readers should use the supplementary artifacts, including "
        "manifest.json and methods_pack.json, for source-bundle traceability.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_section_source_grounding() -> None:
    ask = (
        "Strengthen source_grounding by ensuring every claim in Key Findings, Limitations, "
        "and Conclusion can be traced to at least one source whose excerpt or title directly "
        "supports that specific claim."
    )
    paper = (
        "## Limitations\n\n"
        "The corpus is heterogeneous, but no source trace is provided.\n\n"
        "## Conclusion\n\n"
        "The conclusion is bounded, but no source trace is provided.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_section_source_grounding() -> None:
    ask = (
        "Strengthen source_grounding by ensuring every claim in Key Findings, Limitations, "
        "and Conclusion can be traced to at least one source whose excerpt or title directly "
        "supports that specific claim."
    )
    paper = (
        "## Key Findings\n\n"
        "Movahedian 2025 supports the cardiometabolic signal, while Casper 2024 supports the "
        "sleep-outcome boundary condition.\n\n"
        "## Limitations\n\n"
        "Bradfield 2025 and Gupta 2025 are adjacent-context sources, so the claim is bounded "
        "to source-traceable context rather than direct aging efficacy.\n\n"
        "## Conclusion\n\n"
        "Mohammadi 2025 supports the review-level synthesis boundary; the conclusion does not "
        "add claims beyond those source-traced observations.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_admission_funnel_equal_opposite_counts() -> None:
    ask = (
        "Resolve the numerical inconsistency in the admission funnel where "
        "'No extractable claims' and 'Admitted final sources' both equal 56."
    )
    paper = (
        "## Source Admission Funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| No extractable claims | 56 |\n"
        "| Admitted final sources | 56 |\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_admission_funnel_distinct_opposite_counts() -> None:
    ask = (
        "Resolve the numerical inconsistency in the admission funnel where "
        "'No extractable claims' and 'Admitted final sources' both equal 56."
    )
    paper = (
        "## Source Admission Funnel\n\n"
        "| Admission bucket | n |\n"
        "|---|---:|\n"
        "| No extractable claims | 24 |\n"
        "| Admitted final sources | 13 |\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_single_source_proportionality() -> None:
    ask = (
        "For single-source outcome classes (frailty, immune/inflammation, muscle function), "
        "explicitly state upfront that these are hypothesis-generating only and reduce "
        "narrative depth accordingly to maintain proportionality."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Frailty and immune outcomes are discussed as major findings.\n\n"
        "## Conclusion\n\n"
        "The paper summarizes these outcome classes as part of the overall synthesis.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_single_source_proportionality_statement() -> None:
    ask = (
        "For single-source outcome classes (frailty, immune/inflammation, muscle function), "
        "explicitly state upfront that these are hypothesis-generating only and reduce "
        "narrative depth accordingly to maintain proportionality."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Single-source outcome classes are treated as hypothesis-generating and receive "
        "proportional narrative depth rather than standalone evidentiary weight.\n\n"
        "## Conclusion\n\n"
        "The synthesis keeps one-source findings bounded.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


_PAPER = "## Abstract\n\nEGCG reverses aging in humans.\n\n## Results\n\nMixed, mostly null.\n"


def _claims(parsed: dict[str, Any], monkeypatch) -> list[str]:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    return revision_coverage.unsupported_abstract_claims(_PAPER, chat=_chat(parsed), settings=object())


def test_unsupported_abstract_claims_flags_overclaim(monkeypatch) -> None:
    assert _claims({"unsupported": ["EGCG reverses aging in humans."]}, monkeypatch) == ["EGCG reverses aging in humans."]


def test_unsupported_abstract_claims_ignores_neutral_profile_summaries(monkeypatch) -> None:
    parsed = {
        "unsupported": [
            "The evidence profile contains no sources classified primarily as mechanistic evidence.",
            "Positive study-level signals concentrate in no dominant outcome class.",
            "positive signals concentrated in contextual cardioprotection, negative signals in cardiometabolic domains",
            "EGCG reverses aging in humans.",
        ],
    }
    assert _claims(parsed, monkeypatch) == ["EGCG reverses aging in humans."]


def test_unsupported_abstract_claims_empty_when_supported(monkeypatch) -> None:
    assert _claims({"unsupported": []}, monkeypatch) == []


def test_unsupported_abstract_claims_no_abstract_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())
    assert revision_coverage.unsupported_abstract_claims("## Results\n\nx\n", chat=_chat({"unsupported": ["x"]}), settings=object()) == []


def test_unsupported_abstract_claims_failopen_on_error(monkeypatch) -> None:
    monkeypatch.setattr(revision_coverage, "build_judge_chain", lambda _s: ())

    async def boom(**_kwargs: Any) -> Any:
        raise revision_coverage.LLMError("judge down")

    assert revision_coverage.unsupported_abstract_claims(_PAPER, chat=boom, settings=object()) == []


def test_numeric_effect_direction_flags_non_significant_p_value_called_significant() -> None:
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Results\n\nThe body reports the same source.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == [
        "non-significant p-value described as significant: Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08)."
    ]


def test_deterministic_unmet_flags_numeric_effect_revision_still_wrong() -> None:
    ask = (
        "Correct factual error in abstract regarding Waghmare 2024: source excerpt reports "
        "non-significant result (p = 0.08), not significant reduction. Audit all reported "
        "p-values and effect directions."
    )
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Conclusion\n\nThe corpus remains mixed.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_corrected_numeric_effect_revision() -> None:
    ask = (
        "Correct factual error in abstract regarding Waghmare 2024: source excerpt reports "
        "non-significant result (p = 0.08), not significant reduction. Audit all reported "
        "p-values and effect directions."
    )
    paper = (
        "## Methods\n\n"
        "Numeric effect audit: all reported p-values and effect directions were checked against "
        "source excerpt statistics from the source bundle.\n\n"
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant trend in LF HRV power (p = 0.08).\n\n"
        "## Conclusion\n\nThe corpus remains mixed.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_numeric_effect_direction_allows_explicit_non_significant_language() -> None:
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant reduction in LF HRV power (p = 0.08).\n\n"
        "## Results\n\nThe body reports the same source.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == []


def test_numeric_effect_direction_allows_not_significantly_language() -> None:
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 did not significantly reduce LF HRV power (p = 0.08).\n\n"
        "## Results\n\nThe body reports the same source.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == []


def test_numeric_effect_direction_flags_ci_crossing_null_called_significant() -> None:
    paper = (
        "## Abstract\n\n"
        "The pooled effect was statistically significant (95% CI 0.84-1.18).\n\n"
        "## Results\n\nThe confidence interval crosses the null.\n"
    )
    assert revision_coverage.numeric_effect_direction_issues(paper) == [
        "CI crossing null described as significant: The pooled effect was statistically significant (95% CI 0.84-1.18)."
    ]


def test_deterministic_unmet_flags_missing_numeric_effect_audit_statement() -> None:
    ask = "Audit all reported p-values and effect directions in the manuscript against source bundle excerpts."
    paper = (
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant trend in LF HRV power (p = 0.08).\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_numeric_effect_audit_statement() -> None:
    ask = "Audit all reported p-values and effect directions in the manuscript against source bundle excerpts."
    paper = (
        "## Methods\n\n"
        "Numeric effect audit: all reported p-values and effect directions were checked against "
        "source excerpt statistics from the source bundle.\n\n"
        "## Abstract\n\n"
        "Waghmare 2024 showed a non-significant trend in LF HRV power (p = 0.08).\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_prisma_all_included_without_rationale() -> None:
    ask = "Clarify why 100% of retrieved records were included given the PRISMA-ScR eligibility criteria."
    paper = "## Methods\n\nThe PRISMA-ScR flow retained all records.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_prisma_all_included_rationale() -> None:
    ask = "Clarify why 100% of retrieved records were included given the PRISMA-ScR eligibility criteria."
    paper = (
        "## Methods\n\n"
        "100% of retrieved records were included because the screening scope used prequalified "
        "eligibility criteria from the topic pack; the rationale is that all retrieved records "
        "already met the source-bound inclusion scope.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_known_grammar_artifact() -> None:
    ask = "Correct the grammatical error in the abstract: 'is insufficient to is consistent with therapeutic efficacy'."
    paper = "## Abstract\n\nThe evidence is insufficient to is consistent with therapeutic efficacy.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_known_grammar_artifact_repair() -> None:
    ask = "Correct the grammatical error in the abstract: 'is insufficient to is consistent with therapeutic efficacy'."
    paper = "## Abstract\n\nThe evidence is insufficient to establish therapeutic efficacy.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_source_statistics_missing_from_landscape() -> None:
    ask = (
        "For cited sources with specific statistics, ensure these appear in the evidence landscape "
        "and are connected to the appropriate outcome class rather than buried in the source bundle."
    )
    paper = "## Evidence Landscape\n\nThe corpus includes several sources.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_flags_missing_source_outcome_class_map() -> None:
    ask = (
        "Provide a mapping table or list showing which of the 28 bundle sources were "
        "assigned to which outcome class, to allow external verification of the evidence landscape table."
    )
    paper = "## Evidence Landscape\n\nThe corpus includes several sources.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_source_outcome_class_map() -> None:
    ask = (
        "Provide a mapping table or list showing which of the 28 bundle sources were "
        "assigned to which outcome class, to allow external verification of the evidence landscape table."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Source outcome-class map: Smith 2024 -> outcome=cardiometabolic; "
        "Jones 2025 -> outcome=immune.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_source_statistics_in_landscape() -> None:
    ask = (
        "For cited sources with specific statistics, ensure these appear in the evidence landscape "
        "and are connected to the appropriate outcome class rather than buried in the source bundle."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Weiss 2026 is mapped to outcome class=longevity and reports a 33% lifespan increase; "
        "the statistic is visible in the outcome-class landscape rather than only in the source bundle.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_soft_human_longevity_conclusion() -> None:
    ask = (
        "Strengthen the conclusion to explicitly state that longevity benefits are currently "
        "unproven in humans, not merely incomplete or biologically plausible."
    )
    paper = "## Conclusion\n\nThe human longevity evidence remains biologically plausible but incomplete.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_unproven_human_longevity_conclusion() -> None:
    ask = (
        "Strengthen the conclusion to explicitly state that longevity benefits are currently "
        "unproven in humans, not merely incomplete or biologically plausible."
    )
    paper = "## Conclusion\n\nLongevity benefits are currently unproven in humans and not established clinically.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_population_proof_calibration_boundary() -> None:
    ask = (
        "The manuscript is technically sound and highly bounded, but per calibration rules, "
        "the explicit absence of direct clinical evidence and the reliance on adjacent/mechanistic "
        "data requires a 'revise' status to signal that broad population-level proof is missing."
    )
    paper = "## Abstract\n\nThis synthesis is bounded but does not state the population proof boundary.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_population_proof_calibration_boundary() -> None:
    ask = (
        "The manuscript is technically sound and highly bounded, but per calibration rules, "
        "the explicit absence of direct clinical evidence and the reliance on adjacent/mechanistic "
        "data requires a 'revise' status to signal that broad population-level proof is missing."
    )
    paper = (
        "## Abstract\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and includes adjacent/mechanistic evidence, "
        "this synthesis is hypothesis-generating and not definitive. It does not support "
        "broad causal or policy claims; broad population-level proof is missing.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_mixed_indirect_overclaim_boundary() -> None:
    ask = (
        "Add explicit language in the abstract and conclusion highlighting the mixed "
        "and indirect nature of the evidence base to preempt any overclaiming."
    )
    paper = "## Abstract\n\nEvidence is promising.\n\n## Conclusion\n\nTranslation remains limited.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_mixed_indirect_overclaim_boundary() -> None:
    ask = (
        "Add explicit language in the abstract and conclusion highlighting the mixed "
        "and indirect nature of the evidence base to preempt any overclaiming."
    )
    paper = (
        "## Abstract\n\n"
        "Evidence-boundary note: Because the retained corpus relies on limited direct "
        "interventional hard-endpoint evidence and includes mixed, indirect, adjacent/mechanistic "
        "evidence, this synthesis is hypothesis-generating and not definitive. It does not "
        "support broad causal or policy claims.\n\n"
        "## Conclusion\n\n"
        "Evidence-boundary note: Because the retained corpus relies on mixed, indirect evidence, "
        "this synthesis is not definitive and does not support broad causal or policy claims.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_missing_no_signal_proportion_note() -> None:
    ask = (
        "Ensure all outcome-class summaries in the 'Evidence Landscape' table explicitly "
        "note the proportion of sources with no extracted directional signal to avoid ambiguity."
    )
    paper = "## Evidence Landscape\n\n| Outcome | Signal |\n|---|---|\n| Immune | no extracted directional signal |\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_no_signal_proportion_note() -> None:
    ask = (
        "Ensure all outcome-class summaries in the 'Evidence Landscape' table explicitly "
        "note the proportion of sources with no extracted directional signal to avoid ambiguity."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Directional coding note: Null or no extracted directional signal means no coded positive, "
        "negative, or mixed effect was extracted for that specific outcome class. When an outcome-class "
        "summary uses no extracted directional signal, it states the source proportion, such as X/Y "
        "sources, to avoid ambiguity.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_named_numeric_correction_without_audit_ask() -> None:
    ask = (
        "Correct the factual error in the abstract regarding Waghmare 2024: the source excerpt "
        "reports a non-significant result (p = 0.08), not a significant reduction in LF HRV power."
    )
    paper = "## Abstract\n\nWaghmare 2024 reported a non-significant result in LF HRV power (p = 0.08).\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_flags_unclear_table_vs_positive_negative_narrative() -> None:
    ask = (
        "Reconcile the Evidence Landscape table signals (predominantly 'unclear') with the "
        "narrative claims of positive/negative signals in each outcome section."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Signal |\n|---|---|\n| HRV | predominantly unclear |\n\n"
        "## Results\n\nPositive/negative signals are emphasized in the outcome sections.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == [ask]


def test_deterministic_unmet_accepts_unclear_table_reconciled_with_narrative() -> None:
    ask = (
        "Reconcile the Evidence Landscape table signals (predominantly 'unclear') with the "
        "narrative claims of positive/negative signals in each outcome section."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "| Outcome class | Signal |\n|---|---|\n| HRV | predominantly unclear |\n\n"
        "## Results\n\nPositive/negative signals are separately reported in other outcome classes; "
        "directional coding for the HRV row is reconciled and does not mean absence of support.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_null_coded_directional_reconciliation() -> None:
    ask = (
        "Resolve the disconnect between the '47/48 null-coded' framing and the clearly directional "
        "findings visible in the source bundle excerpts."
    )
    paper = (
        "## Evidence Landscape\n\n"
        "Directional coding note: Null or no extracted directional signal means no coded positive, "
        "negative, or mixed effect was extracted for that specific outcome class. Positive and mixed "
        "signals in other outcome classes are separately reported.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_removed_unbundled_citations() -> None:
    ask = (
        "Remove or add to the source bundle the citations Ioannidis 2005, Studenski 2011, "
        "and Perera 2006, which appear in the prose but are not in the source_bundle list."
    )
    paper = "## References\n\n- **Huang 2025.** Registry-backed source.\n"

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_accepts_replaced_structured_table_stubs() -> None:
    ask = (
        "Replace the 'See the structured evidence table' stubs with one or two short prose "
        "paragraphs per outcome class that name the specific sources driving the dominant signal."
    )
    paper = (
        "## Results\n\n"
        "The frailty slice is driven by Sanz 2021, with no second same-outcome source to "
        "create a direct disagreement. The muscle-function slice is driven by Correa 2022 "
        "and Oliveira 2026, while the broader clinical bridge remains uncertain.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []


def test_deterministic_unmet_requires_consistent_source_count_bundle_reconciliation() -> None:
    ask = (
        "Reconcile the in-text source count (52) with the actual source bundle and either "
        "restore missing bundle entries or correct the count; for every named author-year "
        "citation in the prose, verify a plausible bundle counterpart exists."
    )
    reconciled = (
        "## Methods\n\n"
        "Of 172 records in the receipt-candidate union, 52 were classified as source "
        "candidates and 52 were admitted as traceable synthesis sources. The source bundle "
        "therefore contains 52 references with DOI/PMID traceability where available; "
        "author-year citations in the prose are matched to the reference list.\n"
    )
    inconsistent = reconciled + "\n## Results\n\nThis paper synthesizes 49 included sources.\n"

    assert revision_coverage.deterministic_unmet_asks(reconciled, [ask]) == []
    assert revision_coverage.deterministic_unmet_asks(inconsistent, [ask]) == [ask]


def test_deterministic_unmet_accepts_concrete_tensions_and_gap_priority() -> None:
    ask = (
        "Expand the Tensions and Gaps section with at least 3–5 concrete tensions "
        "(e.g. source A vs source B) and tie each to specific sources."
    )
    paper = (
        "## Cross-Domain Synthesis\n\n"
        "### Load-Bearing Tensions\n\n"
        "- Severity 5 disagreement: Paradoxical 2026 vs Nong 2025; the sources report opposing longevity directions.\n"
        "- Severity 5 disagreement: Pei 2023 vs Gan 2026; the sources disagree on safety comorbidity direction.\n"
        "- Severity 5 disagreement: Zhuang 2025 vs Zeng 2025; the sources conflict on deficiency prevalence.\n\n"
        "### Evidence-Gap Priority\n\n"
        "| Priority | Gap | Rationale |\n|---|---|---|\n| P1 | longevity conflict-resolution gap | opposing source directions |\n"
    )
    weak = (
        "## Cross-Domain Synthesis\n\n"
        "There are several tensions. Future research should resolve the gaps.\n"
    )

    assert revision_coverage.deterministic_unmet_asks(paper, [ask]) == []
    assert revision_coverage.deterministic_unmet_asks(weak, [ask]) == [ask]


def test_revision_asks_splits_soften_and_mark_actions() -> None:
    feedback = (
        "Expand the Tensions and Gaps section with at least 3–5 concrete tensions; "
        "Soften or qualify the positive signal coding for single-source slices; "
        "Mark external non-corpus references as illustrative rather than bundle sources."
    )

    assert revision_coverage.revision_asks(feedback) == [
        "Expand the Tensions and Gaps section with at least 3–5 concrete tensions",
        "Soften or qualify the positive signal coding for single-source slices",
        "Mark external non-corpus references as illustrative rather than bundle sources.",
    ]
